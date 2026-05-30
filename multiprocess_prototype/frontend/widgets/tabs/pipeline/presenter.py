"""PipelinePresenter -- центральный координатор Pipeline Editor.

Task E.1: мигрирован на AppServices DI. Принимает services: AppServices.
G.4.2: process-мутации и undo/redo — через domain dispatch
(services.commands.dispatch / undo / redo). ActionBus bridge удалён.
Scene reload — через typed event TopologyReplaced (services.events), Phase G G.1.

Координирует: PipelineModel (проекция) + Commands (dispatch) + GraphScene + TopologyRepo.
Signal suppression предотвращает циклы при programmatic update.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.commands import (
    AddProcess,
    BindDisplay,
    ConnectWire,
    RemoveProcess,
    SetPluginConfig,
    UnbindDisplay,
)
from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.events import RecipeActivated, TopologyReplaced

from .graph.node_item import NodeData
from .graph.edge_item import EdgeData
from .graph.display_node_item import DisplayNodeData
from .graph.port_schema import PortSchema
from .model import PipelineModel
from .layout import auto_layout
from .telemetry import WireMetricsModel

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_framework.modules.registers_module import RegistersManager

    from .diff import TopologyDiff
    from .graph.graph_scene import GraphScene
    from .inspector.inspector_panel import NodeInspectorPanel

logger = logging.getLogger(__name__)


class PipelinePresenter:
    """Enhanced presenter для Pipeline Editor.

    Координирует:
    - PipelineModel (проекция domain topology) — read-only модель
    - services.commands (CommandDispatcher) — dispatch/undo/redo
    - GraphScene — визуализация
    - services.topology (TopologyRepository) — load + TopologyReplaced events
    - TopologyBridge — IPC (опционально)

    G.4.2: process-мутации (add/remove/wire) через domain dispatch.
    Scene обновляется из TopologyReplaced (unidirectional, без оптимистичных scene-апдейтов).
    Display-мутации временно остаются на legacy PipelineModel+save пути (G.4.2b).
    """

    def __init__(
        self,
        services: AppServices,
        *,
        registers_manager: "RegistersManager | None" = None,
        notify: "Callable[[str], None] | None" = None,
    ) -> None:
        self._services = services
        # G.2: live RegistersManager — runtime-объект (FieldInfo-схемы + значения)
        # для inspector-карточек. Передаётся через RuntimeDeps (Q-F1=B), НЕ через
        # services.registers (domain RegistersBackend не может экспонировать framework FieldInfo).
        self._registers_manager = registers_manager
        # G.6.2: callback для показа отклонённых мутаций пользователю (statusBar).
        # presenter не знает про Qt — tab передаёт реализацию. None → только лог.
        self._notify = notify
        self._model = PipelineModel()
        self._scene: GraphScene | None = None
        self._suppress = False
        self._gui_positions: dict[str, tuple[float, float]] = {}
        # G.4.2: кэш port_schemas (node_id → схемы), заполняется _topology_to_graph,
        # читается load_scene_with_ports. Инициализируем здесь, чтобы метод рендера
        # не падал AttributeError при вызове до первого _topology_to_graph.
        self._port_schemas_cache: dict[str, list[PortSchema]] = {}
        # G.4.2b: кэш display-боксов (по одному на display_id), заполняется
        # _topology_to_graph из topo["displays"], читается load_scene_with_ports.
        self._display_nodes_cache: list[DisplayNodeData] = []
        # Task 1.1: GUI-состояние «размещённые, но непривязанные» display-боксы.
        # Модель хранит дисплеи только как binding в topo["displays"]; пустой бокс
        # там не живёт. _build_display_nodes дорисовывает боксы для этих display_id,
        # чтобы они переживали full scene reload в рамках сессии. Полный жизненный
        # цикл (сброс/удаление) — Task 2.1. См. plans/pipeline-place-display-node.md.
        self._placed_display_ids: set[str] = set()

        # Модель телеметрии wire-соединений (Task 7b.3)
        self._wire_metrics_model = WireMetricsModel()

        # Ленивый импорт TopologyPresenter (для load/save YAML)
        from multiprocess_prototype.frontend.widgets.topology.presenter import TopologyPresenter

        self._topo = TopologyPresenter()

        # Scene reload через typed EventBus (G.1): store публикует TopologyReplaced
        # при каждом save/set_topology (G.3). dispatch() внутри себя вызывает
        # topology_repo.save() → publish → _on_topology_replaced (full reload).
        self._topology_sub = services.events.subscribe(TopologyReplaced, self._on_topology_replaced)

        # Task 2.1: смена рецепта = «новая сессия редактора». Очищаем placed-but-unbound
        # боксы ИМЕННО здесь, а НЕ в _on_topology_replaced. Обоснование точкой в коде:
        # domain Project._apply_activate_recipe (project.py:781-784) эмитит ДВА события —
        # TopologyReplaced (общий reload, на него же завязаны add/remove/wire/undo/redo)
        # и RecipeActivated (только при ActivateRecipe). Обычная мутация в рамках сессии
        # шлёт ТОЛЬКО TopologyReplaced. Поэтому RecipeActivated — единственный надёжный
        # маркер «новая сессия»: чистить set в _on_topology_replaced убило бы непривязанный
        # бокс при первой же мутации (главный риск задачи, см. plans/pipeline-place-display-node.md).
        self._recipe_activated_sub = services.events.subscribe(RecipeActivated, self._on_recipe_activated)

    def set_scene(self, scene: "GraphScene") -> None:
        """Привязать GraphScene для обновления визуализации."""
        self._scene = scene

    def set_inspector(self, panel: "NodeInspectorPanel") -> None:
        """Привязать NodeInspectorPanel.

        Передаёт AppServices в panel и подписывается на field_changed,
        target_process_changed, display_id_changed.
        """
        panel.set_services(self._services, registers_manager=self._registers_manager)
        panel.field_changed.connect(self._on_inspector_field_changed)
        panel.target_process_changed.connect(self._on_target_process_changed)
        panel.display_id_changed.connect(self._on_display_id_changed)

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
        if self._suppress:
            return

        # Convention: один плагин на процесс (AddProcess создаёт процесс с единственным
        # PluginInstance) → plugin_index=0. Multi-plugin (index > 0) — вне scope G.4.3,
        # см. plans/2026-05-27_cross-tab-architecture/phase-g.md.
        cmd = SetPluginConfig(
            process_name=process_name,
            plugin_index=0,
            field=field_name,
            value=new_value,
        )
        try:
            with self._block_signals():
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

    def _on_target_process_changed(self, node_id: str, new_process: str) -> None:
        """Обработчик выбора нового целевого процесса для plugin-узла.

        Записывает target_process как мета-поле в запись процесса в topology.
        Это метаданные для сериализации в blueprint (Task 7a.4), не переименование.

        Args:
            node_id: идентификатор узла (обычно совпадает с process_name).
            new_process: имя целевого процесса из активного рецепта.
        """
        if self._suppress:
            return

        processes = self._model._topology.get("processes", [])

        # Найти запись узла и записать target_process как мета-поле
        found = False
        for proc in processes:
            if isinstance(proc, dict):
                if proc.get("process_name") == node_id:
                    proc["target_process"] = new_process
                    found = True
                    break
            else:
                if getattr(proc, "process_name", "") == node_id:
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
        if self._suppress:
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

    # ------------------------------------------------------------------ #
    #  Signal suppression (из v1)                                         #
    # ------------------------------------------------------------------ #

    @contextmanager
    def _block_signals(self) -> Iterator[None]:
        """Подавить обработку сигналов при programmatic update."""
        prev = self._suppress
        self._suppress = True
        try:
            yield
        finally:
            self._suppress = prev

    @property
    def is_suppressed(self) -> bool:
        return self._suppress

    def _report(self, message: str) -> None:
        """G.6.2: показать сообщение пользователю (statusBar) через notify-callback.

        No-op если notify не задан (тесты / headless). Лог остаётся отдельно
        в каждом catch-сайте.
        """
        if self._notify is not None:
            self._notify(message)

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load_topology_from_config(self) -> tuple[list[NodeData], list[EdgeData]]:
        """Загрузить topology из живого источника (services.topology, TopologyRepository).

        F.2b: ранее читалось из config["topology"] — устаревший стартовый snapshot,
        который не обновлялся. Теперь источник один — TopologyRepository (живой).
        Dict at Boundary: presenter работает с dict, поэтому .to_dict().

        follow-up ФИКС #4 (Task 2.1, шаг 4): явная загрузка топологии из config —
        семантически «новая сессия редактора», как и активация рецепта. Сбрасываем
        placed-but-unbound боксы здесь же: непривязанные боксы не сериализуются (binding
        нет), поэтому при загрузке новой топологии они не должны протекать из прошлой
        сессии. Раньше сброс был только в _on_recipe_activated.
        См. plans/pipeline-place-display-node.md (Task 2.1, шаг 4).
        """
        self._placed_display_ids.clear()
        topology = self._services.topology.load().to_dict()
        self._model.from_topology_dict(topology)

        # Восстановить позиции из metadata
        metadata = topology.get("metadata", {})
        if isinstance(metadata, dict):
            gui_pos = metadata.get("gui_positions", {})
            if isinstance(gui_pos, dict):
                self._gui_positions = {k: tuple(v) for k, v in gui_pos.items()}

        return self._topology_to_graph(topology)

    def load_topology_from_file(self, path: Path) -> tuple[list[NodeData], list[EdgeData]]:
        """Загрузить topology из YAML файла."""
        self._topo.load_from_file(path)
        bp = self._topo.blueprint
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        self._model.from_topology_dict(data)
        return self._topology_to_graph(data)

    def export_topology_with_positions(self) -> dict:
        """Экспортировать topology dict с gui_positions в metadata."""
        topo = self._model.to_topology_dict()

        # Обновить позиции из scene (если привязана)
        if self._scene:
            self._gui_positions.update(self._scene.get_all_node_positions())

        # Записать позиции в metadata
        topo.setdefault("metadata", {})
        topo["metadata"]["gui_positions"] = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}
        return topo

    def save_topology_to_file(self, path: Path) -> None:
        """Сохранить topology с позициями в YAML файл."""
        import yaml

        topo = self.export_topology_with_positions()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(topo, f, default_flow_style=False, allow_unicode=True)

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
        self._gui_positions[name] = (x, y)

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
            self._gui_positions.pop(name, None)
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
        поэтому любой синхронный reload видит уже очищенный _placed_display_ids.
        """
        # Display-боксы адресуются по display_id (id бокса = канал), не по node_id
        # (node_id привязки = source endpoint). Снимок — для разведения веток.
        display_box_ids = {d.get("display_id", "") for d in self._model.get_displays()}

        # ФИКС #2, проход 1 (pre-pass): чисто-unbound боксы (в _placed_display_ids,
        # но НЕТ в topo["displays"]). Чистим GUI-состояние ДО любого dispatch, чтобы
        # синхронный _on_topology_replaced от process/bound-ветки во втором проходе
        # уже не дорисовал такой бокс как placed-but-unbound (иначе — призрак).
        # pure_unbound — множество уже обработанных id: во втором проходе их нужно
        # ПРОПУСТИТЬ, иначе узел (уже убранный из set) провалится в process-ветку и
        # ошибочно вызовет dispatch(RemoveProcess) на несуществующий процесс.
        pure_unbound: set[str] = set()
        for node_id in selected_node_ids:
            if node_id in self._placed_display_ids and node_id not in display_box_ids:
                self._placed_display_ids.discard(node_id)
                self._gui_positions.pop(node_id, None)
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
                # ОСТАЁТСЯ в _placed_display_ids → снимаем его из set ДО dispatch, чтобы
                # reload из _on_topology_replaced после UnbindDisplay не дорисовал бокс
                # заново как placed-but-unbound.
                self._gui_positions.pop(node_id, None)
                self._placed_display_ids.discard(node_id)
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
            elif node_id in self._placed_display_ids:
                # Защитный остаток: чисто-unbound уже обработан pre-pass'ом. Сюда узел
                # дойти не должен — оставлено как страховка на случай рассинхрона.
                self._gui_positions.pop(node_id, None)
                self._placed_display_ids.discard(node_id)
            else:
                # G.4.2: process removal через domain dispatch
                self._gui_positions.pop(node_id, None)
                cmd = RemoveProcess(process_name=node_id)
                try:
                    self._services.commands.dispatch(cmd)
                    dispatched = True
                except DomainError as exc:
                    logger.error("RemoveProcess отклонён: %s", exc)
                    self._report(f"Не удалось удалить процесс: {exc}")
                # Scene обновится из _on_topology_replaced (синхронный)

        # Task 2.1: явная перерисовка нужна только если удаляли исключительно
        # чисто-unbound боксы (dispatch'а, а значит и _on_topology_replaced, не было).
        # Тот же путь, что place_display: _topology_to_graph пройдёт по уже
        # очищенному _placed_display_ids и не дорисует удалённый бокс.
        if had_pure_unbound and not dispatched and self._scene:
            with self._block_signals():
                nodes, edges = self._topology_to_graph(self._model.to_topology_dict())
                self.load_scene_with_ports(nodes, edges)

    def add_wire(self, source: str, target: str, parent: "QWidget | None" = None) -> bool:
        """Добавить wire с валидацией совместимости портов.

        G.4.2: process→process wire → dispatch(ConnectWire). Port-валидация (QMessageBox)
        и guard дубликата сохраняются в presenter ДО dispatch.
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
        # --- Валидация совместимости портов (GUI-concern, остаётся в presenter) ---
        if not self._validate_wire_ports(source, target, parent):
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
            # display_id НАМЕРЕННО остаётся в _placed_display_ids после BindDisplay.
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

    def place_display(self, display_id: str, x: float, y: float) -> None:
        """Разместить пустой (непривязанный) display-бокс на холсте (Task 1.1).

        Бокс ещё НЕ имеет binding (нет источника кадра), поэтому в topo["displays"]
        его нет и domain dispatch здесь НЕ вызывается (binding появится позже, когда
        пользователь протянет провод → add_wire → BindDisplay). Вместо dispatch
        фиксируем GUI-состояние:
          - позицию в _gui_positions (чтобы бокс встал в точку клика);
          - display_id в _placed_display_ids (чтобы _build_display_nodes дорисовал
            бокс при каждом reload — иначе призрак исчез бы при первой мутации).

        Способ перерисовки: переиспользуем штатный путь scene reload — строим
        nodes/edges из текущей модели (_topology_to_graph) и зовём
        load_scene_with_ports внутри _block_signals(). _topology_to_graph →
        _build_display_nodes дорисует placed-but-unbound боксы (включая этот).
        Это тот же конвейер, что _on_topology_replaced, поэтому поведение боксов
        идентично «настоящему» reload. _block_signals() гасит обратные сигналы
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
        self._gui_positions[display_id] = (x, y)
        self._placed_display_ids.add(display_id)

        if not self._scene:
            return
        selected_ids = self._capture_selection()
        with self._block_signals():
            nodes, edges = self._topology_to_graph(self._model.to_topology_dict())
            self.load_scene_with_ports(nodes, edges)
            self._restore_selection(selected_ids)

    def _validate_wire_ports(
        self,
        source: str,
        target: str,
        parent: "QWidget | None" = None,
    ) -> bool:
        """Проверить совместимость портов source и target перед созданием wire.

        Task F.5: использует PluginCatalog Protocol (resolve -> PluginSpec.ports)
        вместо raw _registry bridge. PortSpec конвертируется в framework Port
        для проверки через are_ports_compatible.

        Graceful degradation:
        - PluginSpec не найден -> лог warning, вернуть True (legacy compat)
        - Port не найден -> лог warning, вернуть True
        - Display-цель -> использует wildcard Port(dtype="image/*")

        Returns:
            True -- wire можно создать, False -- wire заблокирован.
        """
        from multiprocess_framework.modules.process_module.plugins.port import (
            Port,
            are_ports_compatible,
        )
        from multiprocess_prototype.domain.protocols.plugin_catalog import PortSpec

        catalog = self._services.plugins

        def _find_port_spec(
            plugin_name: str,
            port_name: str,
            direction: str,
        ) -> "PortSpec | None":
            """Найти PortSpec по имени плагина, порта и направлению."""
            spec = catalog.resolve(plugin_name)
            if spec is None:
                return None
            for ps in spec.ports:
                if ps.name == port_name and ps.direction == direction:
                    return ps
            return None

        def _portspec_to_port(ps: "PortSpec") -> Port:
            """Сконструировать framework Port из domain PortSpec."""
            return Port(
                name=ps.name,
                dtype=ps.dtype,
                shape=ps.shape,
                optional=ps.optional,
            )

        # Шаг 1: разобрать source endpoint -> (process, plugin, port)
        src_parts = source.split(".")
        if len(src_parts) < 3:
            logger.debug("_validate_wire_ports: некорректный source endpoint '%s', пропуск", source)
            return True

        src_plugin_name = src_parts[1]
        src_port_name = src_parts[2]

        # Шаг 2: найти выходной порт источника через PluginCatalog Protocol
        src_spec = catalog.resolve(src_plugin_name)
        if src_spec is None:
            logger.warning(
                "_validate_wire_ports: плагин '%s' не найден в catalog (source=%s), пропуск",
                src_plugin_name,
                source,
            )
            return True

        out_ps = _find_port_spec(src_plugin_name, src_port_name, "output")
        if out_ps is None:
            logger.warning(
                "_validate_wire_ports: выходной порт '%s' не найден у плагина '%s', пропуск",
                src_port_name,
                src_plugin_name,
            )
            return True

        out_port = _portspec_to_port(out_ps)

        # Шаг 3: определить входной порт приёмника
        tgt_parts = target.split(".")
        is_display_target = tgt_parts[0] == "display"

        if is_display_target:
            # Display-узел принимает любой image-выход через wildcard
            in_port = Port(name="frame", dtype="image/*", shape="")
        else:
            if len(tgt_parts) < 3:
                logger.debug(
                    "_validate_wire_ports: некорректный target endpoint '%s', пропуск",
                    target,
                )
                return True

            tgt_plugin_name = tgt_parts[1]
            tgt_port_name = tgt_parts[2]

            tgt_spec = catalog.resolve(tgt_plugin_name)
            if tgt_spec is None:
                logger.warning(
                    "_validate_wire_ports: плагин '%s' не найден в catalog (target=%s), пропуск",
                    tgt_plugin_name,
                    target,
                )
                return True

            in_ps = _find_port_spec(tgt_plugin_name, tgt_port_name, "input")
            if in_ps is None:
                logger.warning(
                    "_validate_wire_ports: входной порт '%s' не найден у плагина '%s', пропуск",
                    tgt_port_name,
                    tgt_plugin_name,
                )
                return True

            in_port = _portspec_to_port(in_ps)

        # Шаг 4: проверить совместимость
        ok = are_ports_compatible(out_port, in_port)
        if not ok:
            logger.warning(
                "Несовместимые порты: %s (%s) -> %s (%s)",
                source,
                out_port.dtype,
                target,
                in_port.dtype,
            )
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                parent,
                "Несовместимые порты",
                f"Невозможно соединить порты:\n"
                f"  Источник: {source}\n"
                f"  Тип: {out_port.dtype}\n\n"
                f"  Приёмник: {target}\n"
                f"  Тип: {in_port.dtype}\n\n"
                f"Типы данных несовместимы.",
            )
            return False

        return True

    def on_node_moved(self, node_id: str, new_x: float, new_y: float) -> None:
        """Обработчик перемещения ноды.

        G.4.4: NODE_MOVE — GUI-only (позиции в _gui_positions/metadata),
        не topology-domain. Остаётся на отдельном пути.
        """
        if self._suppress:
            return
        self._gui_positions[node_id] = (new_x, new_y)

    # ------------------------------------------------------------------ #
    #  Topology sync                                                       #
    # ------------------------------------------------------------------ #

    def _on_topology_replaced(self, _event: "TopologyReplaced") -> None:
        """Подписчик EventBus — топология заменена (полный refresh).

        TopologyReplaced несёт только reason, поэтому актуальную топологию тянем
        из repository (services.topology.load). Обновляет модель и scene с signal
        suppression.

        G.4.2: рендерит scene через load_scene_with_ports, чтобы порты были на месте
        для wire-тяжения после reload (находка #7 аудита).
        """
        if self._suppress:
            return
        new_topology = self._services.topology.load().to_dict()
        # G.6.3: сохранить выделение через reload — load_from_data делает clear_all,
        # иначе после undo/redo (и любой мутации) выделение сбрасывается, inspector
        # очищается, и пользователь не видит откатанные значения без переселекта.
        selected_ids = self._capture_selection()
        with self._block_signals():
            self._model.from_topology_dict(new_topology)
            if self._scene:
                nodes, edges = self._topology_to_graph(new_topology)
                self.load_scene_with_ports(nodes, edges)
                # Восстановить ПОСЛЕ reload, внутри suppress-окна: setSelected →
                # selectionChanged → tab populate'ит inspector (читает обновлённую
                # модель + синхронный rm), а field_changed-сигналы формы гасятся _suppress.
                self._restore_selection(selected_ids)

    def _on_recipe_activated(self, _event: "RecipeActivated") -> None:
        """Task 2.1: подписчик EventBus — активирован новый рецепт (новая сессия).

        Сбрасывает GUI-состояние placed-but-unbound боксов: непривязанные боксы не
        сериализуются в рецепт (binding нет — нечего сохранять), поэтому при загрузке
        нового рецепта они должны исчезнуть. bound-дисплеи нового рецепта рисуются из
        topo["displays"] штатным _build_display_nodes — их не трогаем.

        Порядок событий важен: domain эмитит TopologyReplaced ПЕРЕД RecipeActivated
        (project.py:781-784). К моменту вызова этого handler scene уже перерисована
        _on_topology_replaced'ом и могла дорисовать «старые» unbound-боксы (set ещё не
        пуст). Поэтому после clear() инициируем повторный reload — иначе призраки
        прошлой сессии остались бы на холсте до следующей мутации.

        _gui_positions для unbound-боксов НЕ чистим точечно: позиции — безвредный кэш,
        перезатрутся при повторном place_display, а bound-позиции нового рецепта придут
        из его metadata через load_topology_from_config (если рецепт грузится этим путём).
        """
        if not self._placed_display_ids:
            return
        self._placed_display_ids.clear()
        if not self._scene:
            return
        with self._block_signals():
            nodes, edges = self._topology_to_graph(self._services.topology.load().to_dict())
            self.load_scene_with_ports(nodes, edges)

    def _capture_selection(self) -> list[str]:
        """G.6.3: снять node_id выделенных нод ДО scene reload."""
        if not self._scene:
            return []
        return [item.node_id for item in self._scene.selectedItems() if hasattr(item, "node_id")]

    def _restore_selection(self, node_ids: list[str]) -> None:
        """G.6.3: восстановить выделение ПОСЛЕ reload (узлы, пережившие мутацию)."""
        if not self._scene:
            return
        for node_id in node_ids:
            item = self._scene.get_node(node_id)
            if item is not None:
                item.setSelected(True)

    def load_scene_with_ports(
        self,
        nodes: list[NodeData],
        edges: list[EdgeData],
    ) -> None:
        """Отрисовать ноды (с port_schemas) и рёбра в scene.

        G.4.2: тонкая обёртка над scene.load_from_data — передаёт _port_schemas_cache
        (заполняется _topology_to_graph) как port_schemas_map, чтобы ноды получили
        корректные порты. Layout-логика живёт в одном месте — в load_from_data.
        Публичный метод: вызывается также из PipelineTab при initial load.

        G.4.2b: пробрасывает _display_nodes_cache (display-боксы) — scene рисует их
        из topo["displays"], рёбра source→box уже в edges.
        """
        if not self._scene:
            return
        self._scene.load_from_data(
            nodes,
            edges,
            port_schemas_map=self._port_schemas_cache,
            display_nodes=self._display_nodes_cache,
        )

    # ------------------------------------------------------------------ #
    #  Auto-layout                                                         #
    # ------------------------------------------------------------------ #

    def auto_layout_scene(self) -> None:
        """Применить Sugiyama auto-layout."""
        if not self._scene:
            return
        nodes = self._model.get_process_names()
        edges = self._model.get_edges_as_tuples()
        positions = auto_layout(nodes, edges)

        with self._block_signals():
            for node_id, (x, y) in positions.items():
                self._gui_positions[node_id] = (x, y)
                node_item = self._scene.get_node(node_id)
                if node_item:
                    node_item.setPos(x, y)

    # ------------------------------------------------------------------ #
    #  Валидация и утилиты                                                 #
    # ------------------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Валидация topology через PipelineModel."""
        return self._model.validate()

    def compute_active_recipe_diff(self) -> "TopologyDiff | None":
        """G.6.4: дифф текущей editor-топологии vs blueprint активного рецепта.

        Returns:
            TopologyDiff, или None если активного рецепта нет/рецепт нечитаем.
        """
        from .diff import topology_diff

        store = self._services.recipes
        active = store.get_active()
        if active is None:
            return None
        raw = store.read_raw(active)
        if raw is None:
            logger.warning("compute_active_recipe_diff: рецепт '%s' нечитаем", active)
            return None
        # Оба формата рецепта встречаются (см. launch_active_recipe): blueprint на
        # верхнем уровне либо внутри data.
        saved = raw.get("blueprint") or raw.get("data", {}).get("blueprint") or {}
        current = self._services.topology.load().to_dict()
        return topology_diff(current, saved)

    def get_yaml_preview(self) -> str:
        """YAML превью."""
        return self._topo.get_yaml_preview()

    @property
    def model(self) -> PipelineModel:
        """Доступ к модели (read-only intent)."""
        return self._model

    @property
    def wire_metrics_model(self) -> WireMetricsModel:
        """Доступ к модели телеметрии wire-соединений (Task 7b.3).

        Returns:
            WireMetricsModel — источник данных для WireMetricsController.
        """
        return self._wire_metrics_model

    # ------------------------------------------------------------------ #
    #  Конвертация (оставлена для обратной совместимости)                   #
    # ------------------------------------------------------------------ #

    def _topology_to_graph(self, topo_dict: dict) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертировать topology dict → NodeData/EdgeData.

        G.4.2: реконструирует port_schemas из services.plugins.resolve() при reload,
        чтобы ноды имели корректные порты после dispatch (находка #7 аудита).
        port_schemas хранятся во внутреннем кэше _port_schemas_cache для передачи
        в scene через load_from_data(port_schemas_map=...).

        G.4.2b: рендерит display-боксы из topo["displays"] (binding-формат
        {node_id: <source endpoint>, display_id}). Один бокс на display_id (канал),
        binding-ребро source→box на каждый DisplayInstance. Боксы кладутся в
        _display_nodes_cache, рёбра — в общий список edges.
        """
        nodes = []
        edges = []
        self._port_schemas_cache: dict[str, list[PortSchema]] = {}
        self._display_nodes_cache = []

        processes = topo_dict.get("processes", [])

        for proc in processes:
            if isinstance(proc, dict):
                name = proc.get("process_name", "unnamed")
                plugins = proc.get("plugins", [])
            else:
                name = getattr(proc, "process_name", "unnamed")
                plugins = getattr(proc, "plugins", [])

            category = "utility"
            port_schemas: list[PortSchema] | None = None
            if plugins:
                pname = (
                    plugins[0].get("plugin_name", "")
                    if isinstance(plugins[0], dict)
                    else getattr(plugins[0], "plugin_name", "")
                )
                if pname:
                    spec = self._services.plugins.resolve(pname)
                    if spec is not None:
                        category = spec.category
                        # G.4.2: реконструкция port_schemas из PluginCatalog
                        try:
                            schemas: list[PortSchema] = []
                            for port_spec in spec.ports:
                                schemas.append(
                                    PortSchema(
                                        name=port_spec.name,
                                        direction=port_spec.direction,
                                        dtype=port_spec.dtype,
                                        optional=port_spec.optional,
                                    )
                                )
                            port_schemas = schemas if schemas else None
                        except Exception:
                            port_schemas = None

            # Кэшировать port_schemas для поэлементной установки после load_from_data
            if port_schemas:
                self._port_schemas_cache[name] = port_schemas

            # Восстановить позицию из gui_positions
            x, y = self._gui_positions.get(name, (0.0, 0.0))
            nodes.append(
                NodeData(
                    node_id=name,
                    title=name,
                    subtitle=category,
                    category=category,
                    x=x,
                    y=y,
                )
            )

        wires = topo_dict.get("wires", [])
        for w in wires:
            if isinstance(w, dict):
                source = w.get("source", "")
                target = w.get("target", "")
            else:
                source = getattr(w, "source", "")
                target = getattr(w, "target", "")

            if source and target:
                source_proc = source.split(".")[0] if "." in source else source
                target_proc = target.split(".")[0] if "." in target else target
                edges.append(EdgeData(source_id=source_proc, target_id=target_proc))

        # G.4.2b: display-боксы + binding-рёбра из topo["displays"]
        self._build_display_nodes(topo_dict, edges)

        return nodes, edges

    def _build_display_nodes(self, topo_dict: dict, edges: list[EdgeData]) -> None:
        """Построить display-боксы и binding-рёбра из topo["displays"] (G.4.2b).

        Binding-формат: {node_id: <source endpoint>, display_id, display_name?}.
        Один бокс на display_id (fan-in: N источников → 1 бокс), binding-ребро
        source-процесс → бокс на каждый DisplayInstance. Боксы накапливаются в
        _display_nodes_cache (id бокса = display_id), рёбра дописываются в edges.
        """
        boxes_by_display_id: dict[str, DisplayNodeData] = {}
        next_fallback_index = 0

        for disp in topo_dict.get("displays", []):
            if isinstance(disp, dict):
                source_endpoint = disp.get("node_id", "")
                display_id = disp.get("display_id", "")
                binding_name = disp.get("display_name") or ""
            else:
                source_endpoint = getattr(disp, "node_id", "")
                display_id = getattr(disp, "display_id", "")
                binding_name = getattr(disp, "display_name", "") or ""

            if not display_id:
                continue

            # Бокс на display_id (дедуп при fan-in)
            if display_id not in boxes_by_display_id:
                display_name = self._resolve_display_name(display_id) or binding_name
                x, y = self._gui_positions.get(
                    display_id,
                    (600.0, 50.0 + next_fallback_index * 120.0),
                )
                next_fallback_index += 1
                boxes_by_display_id[display_id] = DisplayNodeData(
                    node_id=display_id,
                    display_id=display_id,
                    display_name=display_name,
                    x=x,
                    y=y,
                )

            # Binding-ребро source-процесс → бокс
            if source_endpoint:
                source_proc = source_endpoint.split(".")[0]
                edges.append(EdgeData(source_id=source_proc, target_id=display_id))

        # Task 1.1: дорисовать placed-but-unbound боксы — display_id, которые
        # пользователь разместил через меню, но ещё не привязал проводом. Их нет
        # в topo["displays"], поэтому без этого шага они исчезли бы при reload.
        # Идём ПОСЛЕ построения из topo["displays"] и пропускаем уже существующие
        # display_id (дедуп) — иначе после bind на scene было бы два бокса.
        for display_id in self._placed_display_ids:
            if display_id in boxes_by_display_id:
                continue
            x, y = self._gui_positions.get(display_id, (600.0, 50.0))
            boxes_by_display_id[display_id] = DisplayNodeData(
                node_id=display_id,
                display_id=display_id,
                display_name=self._resolve_display_name(display_id),
                x=x,
                y=y,
            )

        self._display_nodes_cache = list(boxes_by_display_id.values())

    def _resolve_display_name(self, display_id: str) -> str:
        """Получить человекочитаемое имя канала из DisplayCatalog (best-effort)."""
        try:
            spec = self._services.displays.resolve(display_id)
            if spec is not None:
                return spec.display_name
        except Exception:
            logger.debug("Не удалось получить имя display '%s'", display_id, exc_info=True)
        return ""

    def _blueprint_to_graph(self, bp) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертировать SystemBlueprint в граф-данные."""
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        return self._topology_to_graph(data)

    # ------------------------------------------------------------------ #
    #  Сохранение в рецепт                                                #
    # ------------------------------------------------------------------ #

    def save_to_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Сохранить текущий граф в активный рецепт.

        Вызывает graph_to_blueprint для сериализации модели,
        читает текущий YAML рецепта через store.read_raw(), обновляет секции
        blueprint/display_bindings/gui_positions и записывает через store.save_raw().

        Task F.4: использует RecipeStore Protocol (services.recipes) вместо
        legacy bridge через adapter._rm.

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True при успешном сохранении, False при любой ошибке.
        """
        from PySide6.QtWidgets import QMessageBox

        from .io import graph_to_blueprint

        store = self._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Сохранение рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 2: сериализовать модель
        bp_dict, bindings, gui_positions = graph_to_blueprint(self._model)

        # Обновить gui_positions из scene (если привязана)
        if self._scene:
            self._gui_positions.update(self._scene.get_all_node_positions())
        gui_positions = {node_id: list(pos) for node_id, pos in self._gui_positions.items()}

        # Шаг 3: прочитать текущий YAML рецепта через RecipeStore Protocol
        raw_recipe = store.read_raw(active_slug)
        if raw_recipe is None:
            QMessageBox.critical(parent, "Сохранение рецепта", "Не удалось прочитать рецепт")
            return False

        # Шаг 4: обновить секции в data-части рецепта
        try:
            recipe_data = raw_recipe.get("data", {})
            if not isinstance(recipe_data, dict):
                recipe_data = {}

            recipe_data["blueprint"] = bp_dict
            recipe_data["display_bindings"] = bindings
            recipe_data["gui_positions"] = gui_positions

            raw_recipe["data"] = recipe_data

            # Записать через RecipeStore Protocol
            store.save_raw(active_slug, raw_recipe)

            logger.info("Pipeline сохранён в рецепт '%s'", active_slug)
        except Exception as exc:
            logger.exception("Ошибка при сохранении рецепта '%s'", active_slug)
            QMessageBox.critical(parent, "Сохранение рецепта", f"Ошибка: {exc}")
            return False

        QMessageBox.information(parent, "Сохранение рецепта", f"Рецепт сохранён: {active_slug}")
        return True

    # ------------------------------------------------------------------ #
    #  Запуск активного рецепта                                           #
    # ------------------------------------------------------------------ #

    def launch_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Запустить активный рецепт через ProcessManager-proxy.

        Получает blueprint из активного рецепта и вызывает
        ``proxy.replace_blueprint(blueprint)`` — горячую замену процессов
        без остановки GUI.

        Task F.4: использует RecipeStore Protocol (services.recipes).

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True при успешном запуске, False при любой ошибке или при
            отсутствии proxy.
        """
        from PySide6.QtWidgets import QMessageBox

        store = self._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            QMessageBox.warning(parent, "Запуск рецепта", "Не выбран активный рецепт")
            return False

        # Шаг 2: прочитать рецепт через RecipeStore Protocol
        current = store.read_raw(active_slug)
        if current is None:
            QMessageBox.critical(parent, "Запуск рецепта", "Не удалось прочитать рецепт")
            return False

        # Шаг 4: извлечь blueprint
        blueprint = current.get("blueprint") or current.get("data", {}).get("blueprint") or {}
        if not blueprint:
            QMessageBox.warning(
                parent,
                "Запуск рецепта",
                f"Рецепт '{active_slug}' не содержит blueprint",
            )
            return False

        # Шаг 5: найти ProcessManager-proxy
        # By design (Q-F1=B): process_manager_proxy — runtime layer, не AppServices Protocol.
        # Остаётся тихим bridge через config / RuntimeDeps.
        proxy = None

        # Попытка получить proxy через config extras (не deprecated ключи)
        pm_proxy = self._services.config.get("process_manager_proxy")
        if pm_proxy is not None:
            proxy = pm_proxy

        if proxy is None or not hasattr(proxy, "replace_blueprint"):
            QMessageBox.warning(
                parent,
                "Запуск рецепта",
                "ProcessManager-proxy недоступен в GUI-процессе.\nЗапуск возможен только при работающей системе.",
            )
            return False

        # Шаг 6: вызвать replace_blueprint
        try:
            result = proxy.replace_blueprint(blueprint)
            success = result.get("success", False)
            if success:
                replaced = result.get("replaced", [])
                skipped = result.get("skipped_protected", [])
                QMessageBox.information(
                    parent,
                    "Запуск рецепта",
                    f"Рецепт '{active_slug}' запущен.\n"
                    f"Заменено процессов: {len(replaced)}\n"
                    f"Пропущено (protected): {len(skipped)}",
                )
                return True
            else:
                error = result.get("error") or "неизвестная ошибка"
                rolled_back = result.get("rolled_back", False)
                QMessageBox.critical(
                    parent,
                    "Запуск рецепта",
                    f"Ошибка: {error}\nRollback: {'выполнен' if rolled_back else 'не выполнен'}",
                )
                return False
        except Exception as exc:
            logger.exception("launch_active_recipe failed")
            QMessageBox.critical(parent, "Запуск рецепта", f"Ошибка: {exc}")
            return False

    # ------------------------------------------------------------------ #
    #  Legacy API compatibility                                            #
    # ------------------------------------------------------------------ #

    def add_process(self, name: str, category: str = "utility") -> NodeData:
        """Legacy: добавить процесс (без ActionBus)."""
        self._topo.add_process(name)
        return NodeData(node_id=name, title=name, subtitle=category, category=category)

    def remove_process(self, name: str) -> None:
        """Legacy: удалить процесс."""
        self._topo.remove_process(name)
