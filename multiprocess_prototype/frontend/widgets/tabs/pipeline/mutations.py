# -*- coding: utf-8 -*-
"""Мутации графа Pipeline через domain dispatch (Трек F, Task F.4 + F.7).

Добавление/удаление процессов, плагинов, проводов и display-боксов,
inspector-driven правки полей, смена целевого процесса/канала, перенос плагинов
между процессами. Поведение заморожено тестами
(``test_presenter_domain_dispatch.py``, ``test_place_display.py``,
``test_presenter_inspector_integration.py``, ``test_plugin_drag.py``, ``test_g6_ux.py``).

Все мутации проходят через ``services.commands.dispatch`` (undo/redo, персист в
editor-топологию); scene обновляется реактивно из ``TopologyReplaced`` в
presenter-core.

Зависимости (F.7): стабильные коллабораторы (``services`` / ``model`` / ``report``)
инжектятся снимком; GUI-состояние (``placed_display_ids`` / ``gui_positions``)
берётся у ВЛАДЕЛЬЦА — :class:`LayoutController` (``self._layout``), а не из
presenter; Qt-реакции (scene, подавление сигналов, рендер, выделение, валидация
портов) — через узкий host-контракт :class:`PipelineHost` (``self._host``). Прямого
доступа к приватным полям presenter больше нет.

Qt-зависимость: контроллер Qt-free по прямым импортам. QMessageBox port-валидации
живёт в host (``validate_wire_ports`` — GUI-реакция на несовместимые порты),
контроллер лишь вызывает его; параметр ``parent: QWidget`` пробрасывается туда.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from multiprocess_prototype.domain.commands import (
    AddProcess,
    BindDisplay,
    ConnectWire,
    DisconnectWire,
    MovePlugin,
    RemovePlugin,
    RemoveProcess,
    SetPluginConfig,
    UnbindDisplay,
)
from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.errors import DomainError

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_prototype.domain.app_services import AppServices

    from ._host import PipelineHost
    from .layout_controller import LayoutController
    from .model import PipelineModel

logger = logging.getLogger(__name__)


class PipelineMutations:
    """Контроллер мутаций графа для вкладки Pipeline.

    Коллабораторы инжектятся: ``services`` (dispatch), ``model`` (проекция),
    ``report`` (notify-статус). GUI-состояние — у ``self._layout``
    (LayoutController, владелец). Qt-реакции — через ``self._host`` (PipelineHost).
    """

    def __init__(
        self,
        host: "PipelineHost",
        *,
        services: "AppServices",
        model: "PipelineModel",
        layout: "LayoutController",
        report: Callable[[str], None],
    ) -> None:
        self._host = host
        self._services = services
        self._model = model
        # Владелец GUI-состояния (placed_display_ids / gui_positions).
        self._layout = layout
        self._report = report

    # ------------------------------------------------------------------ #
    #  Inspector-driven правки                                            #
    # ------------------------------------------------------------------ #

    def _on_inspector_field_changed(
        self,
        process_name: str,
        field_name: str,
        new_value: Any,
    ) -> None:
        """Обработчик изменения поля из NodeInspectorPanel.

        G.4.3: dispatch(SetPluginConfig) → domain персистит config в editor-топологию
        + undo/redo. rm-sync выполняет отдельный listener (app.py) по событию
        PluginConfigChanged → rm.set_value → IPC в живой процесс.

        _suppress гасит TopologyReplaced → scene full reload НЕ происходит при
        field-edit (графовая структура не меняется). coalesce_key объединяет
        slider-burst (десятки правок/сек) в одну undo-запись.
        """
        # Защитный re-entry guard: не запускать новый dispatch, пока presenter в
        # suppressed-окне (собственный dispatch ниже либо full reload в
        # _on_topology_replaced). Прямой rm→field_changed обратной связи сейчас нет,
        # поэтому guard — дешёвая страховка, а не обязательная защита от живого пути.
        if self._host.is_suppressed:
            return

        # D.2: per-plugin редактирование. Индекс выбранного плагина читаем из панели
        # (current_plugin_index) — нода=плагин, в процессе может быть цепочка. Default 0
        # совместим с прямым field_changed.emit (тесты, 1 плагин/процесс).
        inspector = self._host.inspector
        plugin_index = getattr(inspector, "current_plugin_index", 0) if inspector is not None else 0
        cmd = SetPluginConfig(
            process_name=process_name,
            plugin_index=plugin_index,
            field=field_name,
            value=new_value,
        )
        try:
            with self._host.block_signals():
                self._services.commands.dispatch(
                    cmd,
                    coalesce_key=f"set_config:{process_name}:{field_name}",
                )
        except DomainError as exc:
            logger.warning(
                "SetPluginConfig отклонён для %s.%s = %s: %s",
                process_name,
                field_name,
                new_value,
                exc,
            )
            self._report(f"Изменение поля отклонено: {exc}")
            return

        # FIX (field-edit-persist): SetPluginConfig обновил domain-топологию (истину),
        # но _on_topology_replaced подавлен _suppress (чтобы не дёргать scene на каждый
        # тик слайдера) → self._model оставался со СТАРЫМ конфигом, и save_to_active_recipe
        # (graph_to_blueprint(self._model)) сериализовал устаревшие значения — правки полей
        # НЕ персистились в рецепт. Точечно пересинхронизируем view-модель из domain БЕЗ
        # rebuild scene: from_topology_dict — чистая dict-операция (deepcopy), без Qt/сигналов.
        self._model.from_topology_dict(self._services.topology.load().to_dict())

    def _on_target_process_changed(self, node_id: str, new_process: str) -> None:
        """Обработчик выбора нового целевого процесса для plugin-узла.

        Записывает target_process как мета-поле в запись процесса в topology.
        Это метаданные для сериализации в blueprint (Task 7a.4), не переименование.

        Args:
            node_id: идентификатор узла (обычно совпадает с process_name).
            new_process: имя целевого процесса из активного рецепта.
        """
        if self._host.is_suppressed:
            return

        # D.1: node_id может быть плагин-нодой `{process}.{plugin}` — извлекаем процесс.
        process_name = node_id.split(".")[0] if node_id else node_id

        processes = self._model._topology.get("processes", [])

        # Найти запись узла и записать target_process как мета-поле
        found = False
        for proc in processes:
            if isinstance(proc, dict):
                if proc.get("process_name") == process_name:
                    proc["target_process"] = new_process
                    found = True
                    break
            else:
                if getattr(proc, "process_name", "") == process_name:
                    try:
                        proc.target_process = new_process
                    except AttributeError:
                        pass
                    found = True
                    break

        if found:
            logger.debug(
                "target_process обновлён: узел '%s' → процесс '%s'",
                node_id,
                new_process,
            )
        else:
            logger.warning(
                "_on_target_process_changed: узел '%s' не найден в topology",
                node_id,
            )

    def _on_display_id_changed(self, node_id: str, new_display_id: str) -> None:
        """Обработчик выбора нового display-канала для display-бокса.

        G.4.2b: смена канала бокса = ребиндинг всех привязок на этот бокс через
        domain dispatch (Unbind старого + Bind нового на каждый источник). id бокса
        = старый display_id. Undoable через services.commands.

        Args:
            node_id: идентификатор display-бокса (= старый display_id канала).
            new_display_id: новый выбранный display_id.
        """
        if self._host.is_suppressed:
            return

        old_display_id = node_id  # id бокса = display_id канала
        if not new_display_id or new_display_id == old_display_id:
            return

        # Снимок привязок на этот бокс ДО мутаций (dispatch перестроит модель)
        sources = [
            d.get("node_id", "")
            for d in self._model.get_displays()
            if d.get("display_id") == old_display_id and d.get("node_id")
        ]
        if not sources:
            logger.warning("_on_display_id_changed: бокс '%s' без привязок", old_display_id)
            return

        # coalesce_key объединяет все Unbind+Bind ребиндинга в ОДНУ undo-запись —
        # один Ctrl+Z отменяет смену канала целиком (важно при fan-in: N источников).
        coalesce_key = f"rebind-display:{old_display_id}->{new_display_id}"
        for src in sources:
            try:
                self._services.commands.dispatch(
                    UnbindDisplay(node_id=src, display_id=old_display_id),
                    coalesce_key=coalesce_key,
                )
                self._services.commands.dispatch(
                    BindDisplay(node_id=src, display_id=new_display_id),
                    coalesce_key=coalesce_key,
                )
            except DomainError as exc:
                logger.warning("Ребиндинг display %s→%s отклонён: %s", old_display_id, new_display_id, exc)
                self._report(f"Смена канала дисплея отклонена: {exc}")

    def _on_move_to_process_requested(self, from_process: str, to_process: str) -> None:
        """Phase B: перенести ВСЕ плагины узла в другой процесс (merge nodes).

        G.4.2-стиль: dispatch(MovePlugin) → store.save → TopologyReplaced → reload.
        Узел=процесс, поэтому «перенести ноду в процесс» = перенести все его плагины
        туда по одному (index 0 каждый раз; на последнем источник опустеет и удалится).
        coalesce_key объединяет серию в одну undo-запись. Domain переписывает концы
        проводов и убирает ставшие внутрипроцессными.
        """
        if self._host.is_suppressed or not to_process or from_process == to_process:
            return

        # Счётчик плагинов источника СНИМАЕМ до серии (модель меняется после каждого dispatch).
        plugin_count = 0
        for proc in self._model.to_topology_dict().get("processes", []):
            name = proc.get("process_name", "") if isinstance(proc, dict) else getattr(proc, "process_name", "")
            if name == from_process:
                plugins = proc.get("plugins", []) if isinstance(proc, dict) else getattr(proc, "plugins", [])
                plugin_count = len(plugins)
                break
        if plugin_count == 0:
            return

        coalesce_key = f"move-node:{from_process}->{to_process}"
        for _ in range(plugin_count):
            try:
                self._services.commands.dispatch(
                    MovePlugin(from_process=from_process, from_index=0, to_process=to_process),
                    coalesce_key=coalesce_key,
                )
            except DomainError as exc:
                logger.warning("MovePlugin %s→%s отклонён: %s", from_process, to_process, exc)
                self._report(f"Перенос в процессе отклонён: {exc}")
                break
        # Scene обновится из _on_topology_replaced (синхронный dispatch)

    def _delete_command_for(self, node_id: str):
        """Команда удаления для плагин-ноды/процесса (D.3).

        Плагин-нода `{process}.{plugin}` в процессе с >1 плагином → RemovePlugin
        (удалить только этот плагин). Иначе (последний плагин, process-fallback нода
        или legacy-имя процесса) → RemoveProcess. Индекс берём из scene-ноды
        (надёжно при дубликатах plugin_name); fallback — поиск по plugin_name.
        """
        proc = node_id.split(".")[0] if "." in node_id else node_id

        # Плагины процесса из модели.
        plugins: list = []
        for p in self._model.to_topology_dict().get("processes", []):
            pn = p.get("process_name", "") if isinstance(p, dict) else getattr(p, "process_name", "")
            if pn == proc:
                plugins = p.get("plugins", []) if isinstance(p, dict) else getattr(p, "plugins", [])
                break

        if "." not in node_id or len(plugins) <= 1:
            return RemoveProcess(process_name=proc)

        # Индекс удаляемого плагина: из scene-ноды, иначе по plugin_name.
        scene = self._host.scene
        node = scene.get_node(node_id) if scene else None
        index = getattr(node, "plugin_index", -1) if node is not None else -1
        if index < 0:
            plugin_name = node_id.split(".", 1)[1]
            for i, pl in enumerate(plugins):
                pn = pl.get("plugin_name", "") if isinstance(pl, dict) else getattr(pl, "plugin_name", "")
                if pn == plugin_name:
                    index = i
                    break
        if index < 0:
            return RemoveProcess(process_name=proc)
        return RemovePlugin(process_name=proc, index=index)

    # ------------------------------------------------------------------ #
    #  Мутации через domain dispatch (process); display — legacy (G.4.2b)  #
    # ------------------------------------------------------------------ #

    def add_process_from_plugin(self, plugin_name: str, x: float = 0.0, y: float = 0.0) -> str | None:
        """Добавить процесс из палитры плагинов через domain dispatch.

        G.4.2: dispatch(AddProcess) → store.save → TopologyReplaced → full scene reload.
        Оптимистичные scene-апдейты убраны — scene обновляется из _on_topology_replaced.

        Returns: имя процесса или None если не удалось.
        """
        # Генерировать уникальное имя (модель синхронна после прошлого reload)
        base_name = plugin_name.replace("_", "-")
        existing = set(self._model.get_process_names())
        name = base_name
        counter = 1
        while name in existing:
            name = f"{base_name}_{counter}"
            counter += 1

        # Определить категорию через PluginCatalog
        category = "utility"
        spec = self._services.plugins.resolve(plugin_name)
        if spec is not None:
            category = spec.category

        # Запомнить позицию ДО dispatch (reload читает gui_positions)
        self._layout.gui_positions[name] = (x, y)

        # G.4.2: domain dispatch — AddProcess обязан нести плагин (иначе нода пустая)
        cmd = AddProcess(
            process_name=name,
            plugins=(PluginInstance(plugin_name=plugin_name, category=category),),
        )
        try:
            self._services.commands.dispatch(cmd)
        except DomainError as exc:
            logger.error("AddProcess отклонён: %s", exc)
            self._report(f"Не удалось добавить процесс: {exc}")
            self._layout.gui_positions.pop(name, None)
            return None

        # Scene обновится из _on_topology_replaced (синхронный dispatch → reload уже произошёл)
        return name

    def remove_selected(self, selected_node_ids: list[str]) -> None:
        """Удалить выбранные ноды (process-узлы и display-боксы).

        G.4.2: process-ноды → dispatch(RemoveProcess) (domain каскадит wires+displays).
        G.4.2b: display-боксы → dispatch(UnbindDisplay) для каждой привязки на канал
        (id бокса = display_id). Всё персистится и undoable через services.commands.
        Task 2.1: placed-but-unbound боксы (нет binding) удаляются БЕЗ dispatch —
        нечего отвязывать; чистим только GUI-состояние и перерисовываем scene.

        follow-up ФИКС #2 (бокс-призрак при смешанном удалении): метод двухпроходный.
        Раньше unbound-ветка делала discard ВНУТРИ единого цикла; при смешанном
        selected (process + чисто-unbound-бокс) и порядке «process первым» синхронный
        _on_topology_replaced от RemoveProcess отрабатывал, когда unbound-id ещё был в
        set → бокс дорисовывался и оставался призраком (финальная перерисовка
        пропускалась, т.к. dispatched=True). Порядок selected_node_ids не гарантирован.
        Решение: pre-pass очищает set/позиции для чисто-unbound ДО любого dispatch,
        поэтому любой синхронный reload видит уже очищенный placed_display_ids.
        """
        # Display-боксы адресуются по display_id (id бокса = канал), не по node_id
        # (node_id привязки = source endpoint). Снимок — для разведения веток.
        display_box_ids = {d.get("display_id", "") for d in self._model.get_displays()}

        gui_positions = self._layout.gui_positions
        placed_display_ids = self._layout.placed_display_ids

        # ФИКС #2, проход 1 (pre-pass): чисто-unbound боксы (в placed_display_ids,
        # но НЕТ в topo["displays"]). Чистим GUI-состояние ДО любого dispatch, чтобы
        # синхронный _on_topology_replaced от process/bound-ветки во втором проходе
        # уже не дорисовал такой бокс как placed-but-unbound (иначе — призрак).
        # pure_unbound — множество уже обработанных id: во втором проходе их нужно
        # ПРОПУСТИТЬ, иначе узел (уже убранный из set) провалится в process-ветку и
        # ошибочно вызовет dispatch(RemoveProcess) на несуществующий процесс.
        pure_unbound: set[str] = set()
        for node_id in selected_node_ids:
            if node_id in placed_display_ids and node_id not in display_box_ids:
                placed_display_ids.discard(node_id)
                gui_positions.pop(node_id, None)
                pure_unbound.add(node_id)
        had_pure_unbound = bool(pure_unbound)

        # Task 2.1: был ли хотя бы один dispatch (bound-display / process). Если все
        # удаляемые узлы — только чисто-unbound-боксы, _on_topology_replaced НЕ
        # сработает (dispatch'а нет) → нужна явная перерисовка scene в конце.
        dispatched = False

        # ФИКС #2, проход 2: dispatch'ащие ветки (bound display → UnbindDisplay;
        # process → RemoveProcess). Чисто-unbound уже обработаны в pre-pass и
        # пропускаются явно (см. pure_unbound).
        for node_id in selected_node_ids:
            if node_id in pure_unbound:
                # Уже очищен pre-pass'ом — нечего dispatch'ить.
                continue

            if node_id in display_box_ids:
                # G.4.2b: удаление display-бокса = отвязать все binding на этот канал.
                # get_displays() — снимок (deep copy) на входе в цикл: dispatch внутри
                # перестраивает модель, но мы итерируем исходный список пар.
                # Task 2.1 (смешанный placed+bound случай): после ФИКСА #1 bound-бокс
                # ОСТАЁТСЯ в placed_display_ids → снимаем его из set ДО dispatch, чтобы
                # reload из _on_topology_replaced после UnbindDisplay не дорисовал бокс
                # заново как placed-but-unbound.
                gui_positions.pop(node_id, None)
                placed_display_ids.discard(node_id)
                for di in self._model.get_displays():
                    if di.get("display_id") != node_id:
                        continue
                    cmd = UnbindDisplay(node_id=di.get("node_id", ""), display_id=node_id)
                    try:
                        self._services.commands.dispatch(cmd)
                        dispatched = True
                    except DomainError as exc:
                        logger.warning("UnbindDisplay отклонён: %s", exc)
                        self._report(f"Не удалось отвязать дисплей: {exc}")
                # Scene обновится из _on_topology_replaced (синхронный dispatch)
            elif node_id in placed_display_ids:
                # Защитный остаток: чисто-unbound уже обработан pre-pass'ом. Сюда узел
                # дойти не должен — оставлено как страховка на случай рассинхрона.
                gui_positions.pop(node_id, None)
                placed_display_ids.discard(node_id)
            else:
                # D.1/D.3: node_id может быть плагин-нодой `{process}.{plugin}` или
                # именем процесса (legacy/тесты). Удаление плагин-ноды:
                #   - процесс с >1 плагином → RemovePlugin(index) (удалить ТОЛЬКО плагин);
                #   - последний плагин / process-нода → RemoveProcess (удалить процесс).
                gui_positions.pop(node_id, None)
                cmd = self._delete_command_for(node_id)
                try:
                    self._services.commands.dispatch(cmd)
                    dispatched = True
                except DomainError as exc:
                    logger.error("%s отклонён: %s", type(cmd).__name__, exc)
                    self._report(f"Не удалось удалить узел: {exc}")
                # Scene обновится из _on_topology_replaced (синхронный)

        # Task 2.1: явная перерисовка нужна только если удаляли исключительно
        # чисто-unbound боксы (dispatch'а, а значит и _on_topology_replaced, не было).
        # Тот же путь, что place_display: _topology_to_graph пройдёт по уже
        # очищенному placed_display_ids и не дорисует удалённый бокс.
        if had_pure_unbound and not dispatched and self._host.scene:
            with self._host.block_signals():
                nodes, edges = self._host.topology_to_graph(self._model.to_topology_dict())
                self._host.load_scene_with_ports(nodes, edges)

    def add_wire(self, source: str, target: str, parent: "QWidget | None" = None) -> bool:
        """Добавить wire с валидацией совместимости портов.

        G.4.2: process→process wire → dispatch(ConnectWire). Port-валидация (QMessageBox)
        и guard дубликата сохраняются ДО dispatch (в host.validate_wire_ports).
        G.4.2b: wire-to-display → dispatch(BindDisplay) — соединение source→бокс есть
        привязка (node_id=source endpoint, display_id=канал бокса), не wire.

        Args:
            source: endpoint источника в формате "process.plugin.port"
            target: endpoint приёмника в формате "process.plugin.port"
                    или "display.<display_id>.frame" для display-боксов
            parent: родительский виджет для QMessageBox (может быть None)

        Returns:
            True если wire/binding создан, False если заблокирован.
        """
        # --- Валидация совместимости портов (GUI-concern, host) ---
        if not self._host.validate_wire_ports(source, target, parent):
            return False

        is_display_target = target.split(".")[0] == "display"

        if is_display_target:
            # G.4.2b: соединение source→display-бокс = dispatch(BindDisplay).
            # target = "display.<display_id>.frame" (id бокса = display_id).
            parts = target.split(".")
            display_id = parts[1] if len(parts) >= 2 else ""
            if not display_id:
                logger.warning("BindDisplay: некорректный display-target '%s'", target)
                return False
            cmd = BindDisplay(node_id=source, display_id=display_id)
            try:
                self._services.commands.dispatch(cmd)
            except DomainError as exc:
                logger.warning("BindDisplay отклонён: %s", exc)
                self._report(f"Не удалось привязать дисплей: {exc}")
                return False
            # Task 2.1 / follow-up ФИКС #1 (потеря данных при undo):
            # display_id НАМЕРЕННО остаётся в placed_display_ids после BindDisplay.
            # Дедуп по display_id в _build_display_nodes и так не плодит дубль (бокс из
            # topo["displays"] строится первым и имеет приоритет — placed-ветка
            # пропускает уже существующий id). А сохранение записи в set держит бокс
            # живым при Ctrl+Z: undo BindDisplay → _on_topology_replaced → topo больше
            # НЕ содержит этот display_id, но placed-ветка дорисует бокс заново как
            # placed-but-unbound (корректный UX — возврат в «размещён, но не привязан»).
            # Прежний discard здесь убивал бокс из ОБОИХ источников безвозвратно.
            # Запись чистится при явном удалении (bound-ветка remove_selected делает
            # discard) и при смене рецепта (_on_recipe_activated.clear()). Это вариант,
            # прямо разрешённый планом («оставить в set до смены рецепта ИЛИ снять
            # после bind — выбрать»). См. plans/pipeline-place-display-node.md (Task 2.1).
            # Scene обновится из _on_topology_replaced (синхронный dispatch)
            return True

        # G.4.2: process→process wire через domain dispatch
        # Guard дубликата (domain не отвергает дубликаты, находка #5 аудита)
        for w in self._model.get_wires():
            if isinstance(w, dict) and w.get("source") == source and w.get("target") == target:
                logger.warning("Wire %s -> %s уже существует (дубликат)", source, target)
                return False

        cmd = ConnectWire(source=source, target=target)
        try:
            self._services.commands.dispatch(cmd)
        except DomainError as exc:
            # Цикл или dangling process → graceful return False, repo не мутирован
            logger.warning("ConnectWire отклонён: %s", exc)
            self._report(f"Соединение отклонено: {exc}")
            return False

        # Scene обновится из _on_topology_replaced (синхронный dispatch → reload уже произошёл)
        return True

    def remove_wire(self, source: str, target: str) -> bool:
        """Удалить wire/привязку source→target — обратное к add_wire.

        process→process → dispatch(DisconnectWire); source→display-бокс
        ("display.<id>.frame") → dispatch(UnbindDisplay). Scene перерисуется
        реактивно из TopologyReplaced. Graceful на DomainError (repo не мутирован).
        """
        is_display_target = target.split(".")[0] == "display"
        if is_display_target:
            parts = target.split(".")
            display_id = parts[1] if len(parts) >= 2 else ""
            if not display_id:
                logger.warning("UnbindDisplay: некорректный display-target '%s'", target)
                return False
            cmd = UnbindDisplay(node_id=source, display_id=display_id)
        else:
            cmd = DisconnectWire(source=source, target=target)
        try:
            self._services.commands.dispatch(cmd)
        except DomainError as exc:
            logger.warning("%s отклонён: %s", type(cmd).__name__, exc)
            self._report(f"Не удалось удалить связь: {exc}")
            return False
        return True

    def place_display(self, display_id: str, x: float, y: float) -> None:
        """Разместить пустой (непривязанный) display-бокс на холсте (Task 1.1).

        Бокс ещё НЕ имеет binding (нет источника кадра), поэтому в topo["displays"]
        его нет и domain dispatch здесь НЕ вызывается (binding появится позже, когда
        пользователь протянет провод → add_wire → BindDisplay). Вместо dispatch
        фиксируем GUI-состояние (у владельца LayoutController):
          - позицию в gui_positions (чтобы бокс встал в точку клика);
          - display_id в placed_display_ids (чтобы _build_display_nodes дорисовал
            бокс при каждом reload — иначе призрак исчез бы при первой мутации).

        Способ перерисовки: переиспользуем штатный путь scene reload — строим
        nodes/edges из текущей модели (topology_to_graph) и зовём
        load_scene_with_ports внутри block_signals(). topology_to_graph →
        _build_display_nodes дорисует placed-but-unbound боксы (включая этот).
        Это тот же конвейер, что _on_topology_replaced, поэтому поведение боксов
        идентично «настоящему» reload. block_signals() гасит обратные сигналы
        scene (selectionChanged), как и в остальных programmatic-апдейтах.

        Идемпотентно: повторный вызов того же display_id лишь обновляет позицию
        (set дедуплицирует). Канал без записи в каталоге допустим — имя резолвится
        в пустое, подзаголовок бокса = display_id.

        follow-up ФИКС #5 (потеря selection): reload здесь делает clear_all сцены,
        из-за чего прежнее выделение терялось и inspector очищался (tab не проверяет
        _suppress в _on_selection_changed). Оборачиваем reload в capture/restore
        selection по аналогии с _on_topology_replaced — прежнее выделение сохраняется.
        Новый размещённый бокс выделять не обязательно.
        """
        self._layout.gui_positions[display_id] = (x, y)
        self._layout.placed_display_ids.add(display_id)

        if not self._host.scene:
            return
        selected_ids = self._host.capture_selection()
        with self._host.block_signals():
            nodes, edges = self._host.topology_to_graph(self._model.to_topology_dict())
            self._host.load_scene_with_ports(nodes, edges)
            self._host.restore_selection(selected_ids)


__all__ = ["PipelineMutations"]
