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
    MovePlugin,
    RemovePlugin,
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
        process_manager_proxy: Any = None,
        bindings: Any = None,
    ) -> None:
        self._services = services
        # GuiStateBindings — для actual-телеметрии камеры в инспекторе (Phase 3).
        self._bindings = bindings
        # Этап 1 pipeline-live-control: IPC-фасад управления живым backend
        # (apply_topology / start / stop / restart). Runtime-объект (RuntimeDeps,
        # Q-F1=B), не AppServices. None → кнопки управления дают понятный статус.
        self._pm_proxy = process_manager_proxy
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
        # Зафиксированные ноды (session-only): не двигаются drag'ом и пропускаются
        # авто-раскладкой. Применяется в _topology_to_graph (NodeData.locked).
        self._locked_nodes: set[str] = set()
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
        # D.2: держим ссылку на панель — _on_inspector_field_changed читает
        # current_plugin_index (какой плагин процесса редактируется).
        self._inspector = panel
        panel.set_services(
            self._services,
            registers_manager=self._registers_manager,
            bindings=self._bindings,
        )
        panel.field_changed.connect(self._on_inspector_field_changed)
        panel.target_process_changed.connect(self._on_target_process_changed)
        panel.display_id_changed.connect(self._on_display_id_changed)
        panel.move_to_process_requested.connect(self._on_move_to_process_requested)
        panel.node_lock_set_requested.connect(self.set_node_lock)

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

        # D.2: per-plugin редактирование. Индекс выбранного плагина читаем из панели
        # (current_plugin_index) — нода=плагин, в процессе может быть цепочка. Default 0
        # совместим с прямым field_changed.emit (тесты, 1 плагин/процесс).
        inspector = getattr(self, "_inspector", None)
        plugin_index = getattr(inspector, "current_plugin_index", 0) if inspector is not None else 0
        cmd = SetPluginConfig(
            process_name=process_name,
            plugin_index=plugin_index,
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

    def _on_move_to_process_requested(self, from_process: str, to_process: str) -> None:
        """Phase B: перенести ВСЕ плагины узла в другой процесс (merge nodes).

        G.4.2-стиль: dispatch(MovePlugin) → store.save → TopologyReplaced → reload.
        Узел=процесс, поэтому «перенести ноду в процесс» = перенести все его плагины
        туда по одному (index 0 каждый раз; на последнем источник опустеет и удалится).
        coalesce_key объединяет серию в одну undo-запись. Domain переписывает концы
        проводов и убирает ставшие внутрипроцессными.
        """
        if self._suppress or not to_process or from_process == to_process:
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

    def on_plugin_dropped(
        self,
        node_id: str,
        from_process: str,
        from_index: int,
        to_process: str,
        to_index: int,
    ) -> None:
        """D.3: плагин-нода перетащена (drag между контейнерами / reorder внутри).

        Решение по сигналу scene.plugin_drop_requested:
          - дроп вне контейнеров (to_process=="") или без изменения позиции →
            snap-back: reload scene из модели (топология не менялась);
          - иначе dispatch(MovePlugin(from, from_index, to, to_index)) — cross-process
            или reorder; reload придёт из TopologyReplaced. Domain переписывает
            концы проводов и убирает ставшие внутрипроцессными.
        """
        if self._suppress:
            return

        no_change = (not to_process) or (to_process == from_process and to_index == from_index)
        if no_change:
            self._reload_scene_from_model()  # snap-back на исходную позицию
            return

        try:
            self._services.commands.dispatch(
                MovePlugin(
                    from_process=from_process,
                    from_index=from_index,
                    to_process=to_process,
                    to_index=to_index,
                )
            )
        except DomainError as exc:
            logger.warning(
                "MovePlugin (drag) %s[%d]→%s[%d] отклонён: %s",
                from_process,
                from_index,
                to_process,
                to_index,
                exc,
            )
            self._report(f"Перенос плагина отклонён: {exc}")
            self._reload_scene_from_model()  # откатить визуальный сдвиг
        # Успех → scene обновится из _on_topology_replaced (синхронный dispatch)

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
        node = self._scene.get_node(node_id) if self._scene else None
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

    def _reload_scene_from_model(self) -> None:
        """Перерисовать scene из текущей модели (без dispatch).

        Используется для snap-back после drag без изменения топологии: позиции
        восстанавливаются из gui_positions/дефолтов. Тот же конвейер, что
        _on_topology_replaced, с сохранением выделения.
        """
        if not self._scene:
            return
        selected_ids = self._capture_selection()
        with self._block_signals():
            nodes, edges = self._topology_to_graph(self._model.to_topology_dict())
            self.load_scene_with_ports(nodes, edges)
            self._restore_selection(selected_ids)

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
                # D.1/D.3: node_id может быть плагин-нодой `{process}.{plugin}` или
                # именем процесса (legacy/тесты). Удаление плагин-ноды:
                #   - процесс с >1 плагином → RemovePlugin(index) (удалить ТОЛЬКО плагин);
                #   - последний плагин / process-нода → RemoveProcess (удалить процесс).
                self._gui_positions.pop(node_id, None)
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

    def set_node_lock(self, node_id: str, locked: bool) -> None:
        """Зафиксировать/освободить ноду явно (session-only).

        Locked-нода не перетаскивается (ItemIsMovable=False) и пропускается
        auto_layout_scene. Состояние живёт в _locked_nodes и переприменяется в
        _topology_to_graph при reload (переживает мутации в рамках сессии).
        """
        if not node_id:
            return
        if locked:
            self._locked_nodes.add(node_id)
        else:
            self._locked_nodes.discard(node_id)
        if self._scene:
            self._scene.set_node_locked(node_id, locked)

    def toggle_node_lock(self, node_id: str) -> None:
        """Переключить фиксацию ноды (правый клик по ноде)."""
        self.set_node_lock(node_id, node_id not in self._locked_nodes)

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
        # Сохранить ТЕКУЩИЕ позиции нод из scene перед перестройкой: ручной drag
        # пишет позицию только в scene, а reload берёт позиции из _gui_positions.
        # Без этого sync любая мутация (TopologyReplaced) сбрасывала бы вручную
        # передвинутые ноды на дефолт/предыдущую позицию («ноды сами сдвигаются»).
        if self._scene:
            self._gui_positions.update(self._scene.get_all_node_positions())
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
        """Применить Sugiyama auto-layout на уровне ПРОЦЕССОВ, плагины — группой.

        D.1: нода = плагин, но раскладка считается по процессам (рамкам): каждый
        процесс — один узел Sugiyama, его плагины раскладываются слева-направо
        внутри по индексу. Ширина узла = макс ширина контейнера (по числу
        плагинов), чтобы колонки не накладывались. Display-боксы участвуют как
        узлы-стоки (binding-ребро source-процесс → бокс).
        """
        if not self._scene:
            return
        from .graph.constants import CONTAINER_HEADER_H, CONTAINER_INNER_GAP, CONTAINER_PADDING, NODE_WIDTH

        topo = self._model.to_topology_dict()
        # Карта процесс → число плагинов (для ширины колонки и offset плагинов).
        plugin_counts: dict[str, int] = {}
        for proc in topo.get("processes", []):
            if proc.get("protected", False) if isinstance(proc, dict) else getattr(proc, "protected", False):
                continue
            pn = proc.get("process_name", "") if isinstance(proc, dict) else getattr(proc, "process_name", "")
            pls = proc.get("plugins", []) if isinstance(proc, dict) else getattr(proc, "plugins", [])
            if pn:
                plugin_counts[pn] = len(pls)

        nodes = list(plugin_counts.keys())
        edges = list(self._model.get_edges_as_tuples())

        # Display-боксы (id = display_id) + binding-рёбра source-процесс → box.
        display_ids: set[str] = set(self._placed_display_ids)
        for d in self._model.get_displays():
            display_id = d.get("display_id", "")
            if not display_id:
                continue
            display_ids.add(display_id)
            source_proc = d.get("node_id", "").split(".")[0]
            if source_proc:
                edges.append((source_proc, display_id))
        for display_id in display_ids:
            if display_id not in nodes:
                nodes.append(display_id)

        # Ширина колонки = макс ширина контейнера (учесть цепочку плагинов).
        max_plugins = max(plugin_counts.values(), default=1) or 1
        column_width = max_plugins * (NODE_WIDTH + CONTAINER_INNER_GAP) + 2 * CONTAINER_PADDING
        positions = auto_layout(nodes, edges, node_width=column_width)

        inner_dy = CONTAINER_HEADER_H + CONTAINER_PADDING
        with self._block_signals():
            for layout_id, (x, y) in positions.items():
                if layout_id in plugin_counts:
                    # Процесс: разложить его плагин-ноды слева-направо группой.
                    members = self._scene.members_of(layout_id)
                    # Сортируем по plugin_index для стабильного порядка цепочки.
                    members.sort(key=lambda m: m.plugin_index)
                    for j, member in enumerate(members):
                        # Зафиксированную ноду авто-раскладка не трогает.
                        if getattr(member.data, "locked", False):
                            continue
                        mx = x + CONTAINER_PADDING + j * (NODE_WIDTH + CONTAINER_INNER_GAP)
                        my = y + inner_dy
                        member.setPos(mx, my)
                        self._gui_positions[member.node_id] = (mx, my)
                else:
                    # Display-бокс (или fallback) — двигаем сам узел (если не locked).
                    node_item = self._scene.get_node(layout_id)
                    if node_item is not None and getattr(getattr(node_item, "data", None), "locked", False):
                        continue
                    self._gui_positions[layout_id] = (x, y)
                    if node_item is not None:
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

        D.1: **нода = плагин**. Один процесс → N плагин-нод (node_id=`{proc}.{plugin}`)
        + рамка-контейнер (строит scene по NodeData.process_name) + неявные стрелки
        цепочки (implicit edges) между соседними плагинами. Процесс без плагинов
        рендерится одной process-fallback нодой (node_id=process_name, plugin_index=-1).

        G.4.2: port_schemas реконструируются из services.plugins.resolve() ПО КАЖДОМУ
        плагину (не только первому) и кэшируются в _port_schemas_cache по node_id
        плагин-ноды (передаётся в scene через load_from_data(port_schemas_map=...)).

        Внешние wires (`proc.plugin.* → proc2.plugin2.*`) мапятся на конкретные
        плагин-ноды (НЕ схлопываются до процесса). Display-боксы — из topo["displays"]
        (binding-ребро source-плагин-нода → бокс).
        """
        nodes: list[NodeData] = []
        edges: list[EdgeData] = []
        self._port_schemas_cache = {}
        self._display_nodes_cache = []

        processes = topo_dict.get("processes", [])
        used_ids: set[str] = set()  # уникальность node_id (дубликаты plugin_name)

        for pi, proc in enumerate(processes):
            protected = proc.get("protected", False) if isinstance(proc, dict) else getattr(proc, "protected", False)
            if protected:
                # protected-процессы (gui из base.yaml) — фундамент, не рисуем.
                continue

            if isinstance(proc, dict):
                name = proc.get("process_name", "unnamed")
                plugins = proc.get("plugins", [])
            else:
                name = getattr(proc, "process_name", "unnamed")
                plugins = getattr(proc, "plugins", [])

            if not plugins:
                # Процесс без плагинов → одна process-fallback нода (node_id=process).
                x, y = self._node_position(name, name, pi, 0)
                nodes.append(
                    NodeData(
                        node_id=name,
                        title=name,
                        subtitle="(пусто)",
                        category="utility",
                        x=x,
                        y=y,
                        process_name=name,
                        plugin_index=-1,
                        plugin_name="",
                        locked=name in self._locked_nodes,
                    )
                )
                used_ids.add(name)
                continue

            prev_node_id: str | None = None
            for j, pl in enumerate(plugins):
                pname = pl.get("plugin_name", "") if isinstance(pl, dict) else getattr(pl, "plugin_name", "")
                category = "utility"
                port_schemas: list[PortSchema] | None = None
                if pname:
                    spec = self._services.plugins.resolve(pname)
                    if spec is not None:
                        category = spec.category
                        try:
                            schemas = [
                                PortSchema(
                                    name=ps.name,
                                    direction=ps.direction,
                                    dtype=ps.dtype,
                                    optional=ps.optional,
                                )
                                for ps in spec.ports
                            ]
                            port_schemas = schemas or None
                        except Exception:
                            port_schemas = None

                node_id = self._unique_plugin_node_id(name, pname, j, used_ids)
                used_ids.add(node_id)
                if port_schemas:
                    self._port_schemas_cache[node_id] = port_schemas

                x, y = self._node_position(node_id, name, pi, j)
                nodes.append(
                    NodeData(
                        node_id=node_id,
                        title=pname or name,
                        subtitle=category,
                        category=category,
                        x=x,
                        y=y,
                        process_name=name,
                        plugin_index=j,
                        plugin_name=pname,
                        locked=node_id in self._locked_nodes,
                    )
                )

                # Неявная стрелка цепочки: предыдущий плагин → текущий.
                if prev_node_id is not None:
                    edges.append(EdgeData(source_id=prev_node_id, target_id=node_id, implicit=True))
                prev_node_id = node_id

        # Внешние wires → конкретные плагин-ноды.
        for w in topo_dict.get("wires", []):
            if isinstance(w, dict):
                source = w.get("source", "")
                target = w.get("target", "")
            else:
                source = getattr(w, "source", "")
                target = getattr(w, "target", "")
            if source and target:
                s_node = self._endpoint_to_node_id(source, topo_dict)
                t_node = self._endpoint_to_node_id(target, topo_dict)
                if s_node and t_node:
                    edges.append(EdgeData(source_id=s_node, target_id=t_node))

        # G.4.2b: display-боксы + binding-рёбра из topo["displays"]
        self._build_display_nodes(topo_dict, edges)

        return nodes, edges

    # ------------------------------------------------------------------ #
    #  Хелперы node=plugin (D.1)                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _unique_plugin_node_id(process: str, plugin_name: str, index: int, used: set[str]) -> str:
        """node_id плагин-ноды = `{process}.{plugin_name}`.

        Дубликаты plugin_name в одном процессе (против конвенции «1 плагин/процесс»
        и неразличимы в endpoint-схеме domain) получают суффикс `#i` для GUI-
        уникальности. Первое вхождение — без суффикса, чтобы wire-endpoint
        (`proc.plugin`) мапился на него. См. план pipeline-process-container-nodes.
        """
        base = f"{process}.{plugin_name}" if plugin_name else f"{process}.plugin{index}"
        if base not in used:
            return base
        suffixed = f"{base}#{index}"
        logger.warning(
            "Дубликат plugin_name '%s' в процессе '%s' — GUI node_id '%s' (endpoint неразличим)",
            plugin_name,
            process,
            suffixed,
        )
        return suffixed

    def _node_position(
        self,
        node_id: str,
        process_name: str,
        process_index: int,
        plugin_index: int,
    ) -> tuple[float, float]:
        """Позиция плагин-ноды: из gui_positions или дефолтный кластер по процессу.

        Приоритет: (1) позиция самой плагин-ноды (`proc.plugin`) — обычный путь
        после auto_layout/сохранения; (2) anchor процесса в gui_positions —
        legacy-рецепты и add_process_from_plugin кладут позицию по имени процесса,
        плагин 0 встаёт в anchor, остальные смещаются вправо; (3) дефолтный
        кластер (процесс=колонка). auto_layout_scene переразложит группами.
        """
        from .graph.constants import CONTAINER_HEADER_H, CONTAINER_INNER_GAP, CONTAINER_PADDING, NODE_WIDTH

        if node_id in self._gui_positions:
            return self._gui_positions[node_id]
        if process_name in self._gui_positions:
            base_x, base_y = self._gui_positions[process_name]
        else:
            base_x = 60.0 + process_index * 340.0
            base_y = 60.0 + CONTAINER_HEADER_H + CONTAINER_PADDING
        x = base_x + plugin_index * (NODE_WIDTH + CONTAINER_INNER_GAP)
        return x, base_y

    @staticmethod
    def _endpoint_to_node_id(endpoint: str, topo_dict: dict) -> str:
        """endpoint `proc.plugin.port` → node_id плагин-ноды (`proc.plugin`).

        Процесс без плагинов → node_id = process (process-fallback нода). При
        отсутствии plugin-сегмента берётся первый плагин процесса.
        """
        parts = endpoint.split(".")
        proc = parts[0]
        # Найти процесс и его плагины.
        plugins: list = []
        for p in topo_dict.get("processes", []):
            pn = p.get("process_name", "") if isinstance(p, dict) else getattr(p, "process_name", "")
            if pn == proc:
                plugins = p.get("plugins", []) if isinstance(p, dict) else getattr(p, "plugins", [])
                break
        if not plugins:
            return proc
        if len(parts) >= 2:
            return f"{proc}.{parts[1]}"
        first = plugins[0]
        first_name = first.get("plugin_name", "") if isinstance(first, dict) else getattr(first, "plugin_name", "")
        return f"{proc}.{first_name}" if first_name else proc

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

            # Binding-ребро source-плагин-нода → бокс (D.1: node=plugin).
            if source_endpoint:
                source_node = self._endpoint_to_node_id(source_endpoint, topo_dict)
                edges.append(EdgeData(source_id=source_node, target_id=display_id))

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

        # Шаг 4: обновить top-level секции v3-рецепта (displays ВНУТРЬ blueprint) через
        # единый нормализатор (one source of truth): без legacy data:-вложения, прочие
        # ключи (name/version/active_services) сохраняются. save_raw — ruamel round-trip.
        try:
            from multiprocess_prototype.recipes.format import normalize_recipe_v3_raw

            bp_dict["displays"] = bindings
            store.save_raw(active_slug, normalize_recipe_v3_raw(raw_recipe, bp_dict, gui_positions))

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
        """Запустить активный рецепт через ProcessManager-proxy (request/response).

        Получает blueprint из активного рецепта и вызывает
        ``proxy.apply_topology(blueprint, on_result=...)`` — горячую замену
        процессов с РЕАЛЬНЫМ результатом (command-result-bridge, Task 4.1).

        В отличие от прежнего fire-and-forget (показывал «отправлено» без знания
        факта): request исполняется на worker-потоке (UI не фризится), а реальный
        ответ PM (``success``/``replaced``/``rolled_back``) приходит в
        :meth:`_on_recipe_launch_result` в Qt main-thread и показывается
        пользователю как успех (с числом заменённых процессов) или ошибка/rollback.

        Task F.4: использует RecipeStore Protocol (services.recipes).

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True если запрос отправлен в работу (результат придёт асинхронно в
            ``_on_recipe_launch_result``); False при pre-flight ошибке (нет
            активного рецепта / blueprint / proxy / ошибка отправки).

        Note:
            Feedback не-модальный: статус и результат идут в статусную строку
            (``_notify``) и лог (терминал), без блокирующих QMessageBox.
        """
        store = self._services.recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            self._notify_status("Запуск рецепта: не выбран активный рецепт", level="warning")
            return False

        # Шаг 2: прочитать рецепт через RecipeStore Protocol
        current = store.read_raw(active_slug)
        if current is None:
            self._notify_status(f"Запуск рецепта: не удалось прочитать рецепт '{active_slug}'", level="error")
            return False

        # Шаг 3: извлечь blueprint
        blueprint = current.get("blueprint") or current.get("data", {}).get("blueprint") or {}
        if not blueprint:
            self._notify_status(f"Запуск рецепта: рецепт '{active_slug}' не содержит blueprint", level="warning")
            return False

        # Шаг 4: ProcessManager-proxy с async request/response (Task 4.1: topology.apply).
        proxy = self._pm_proxy
        if proxy is None or not hasattr(proxy, "apply_topology"):
            self._notify_status(
                "Запуск рецепта: ProcessManager-proxy недоступен (система не запущена)",
                level="warning",
            )
            return False

        # Шаг 5: request/response — реальный результат придёт в on_result (main-thread),
        # request исполняется на worker-потоке (UI не фризится). До ответа показываем
        # «выполняется…» в статусной строке (не модально, чтобы не блокировать UI).
        self._notify_status(f"Запуск рецепта '{active_slug}': выполняется…")
        try:
            proxy.apply_topology(
                blueprint,
                on_result=lambda resp: self._on_recipe_launch_result(resp, active_slug),
            )
        except Exception as exc:
            logger.exception("launch_active_recipe dispatch failed")
            self._notify_status(f"Запуск рецепта '{active_slug}': ошибка отправки — {exc}", level="error")
            return False
        return True

    def _on_recipe_launch_result(self, resp: dict, slug: str) -> None:
        """Главный поток: показать реальный результат активации рецепта (P3).

        Не-модально (статус-строка + лог). Форма ответа:
        - полный PM-ответ ``{"success": bool, "result": {success, replaced,
          rolled_back, error, ...}}`` (через ``router.request`` → reply PM);
        - error/timeout-обёртка ``{"success": False, "error": "..."}`` (без
          ``result``) — от RequestRunner/``request()``.

        Приоритет вердикту самого PM (``result["success"]``); при его отсутствии —
        транспортный ``success``.
        """
        resp = resp if isinstance(resp, dict) else {}
        inner = resp.get("result")
        inner = inner if isinstance(inner, dict) else {}
        ok = bool(inner["success"]) if "success" in inner else bool(resp.get("success"))

        if ok:
            replaced = inner.get("replaced")
            count = len(replaced) if isinstance(replaced, list) else replaced
            detail = f"заменено процессов: {count}" if count is not None else "горячая замена применена"
            self._notify_status(f"Рецепт '{slug}' запущен ({detail})")
            return

        # Ошибка / rollback
        error = inner.get("error") or resp.get("error") or "неизвестная ошибка"
        if inner.get("rolled_back"):
            error = f"{error}; изменения откачены (rollback) — прежняя топология сохранена"
        self._notify_status(f"Рецепт '{slug}': ошибка запуска — {error}", level="error")

    # ------------------------------------------------------------------ #
    #  Этап 1 pipeline-live-control — кнопки управления процессами         #
    # ------------------------------------------------------------------ #

    def restart_topology(self, parent: "QWidget | None" = None) -> bool:
        """Применить ТЕКУЩИЙ граф редактора к живому backend (горячая замена).

        В отличие от ``launch_active_recipe`` (берёт сохранённый рецепт) — берёт
        in-memory модель редактора (``graph_to_blueprint``), тот же формат blueprint,
        что принимает ``apply_topology`` (Task 4.1). Fire-and-forget IPC.

        Сценарий: удалить ноду → «Перезапустить» → эффект ноды пропадает на дисплее.

        Args:
            parent: родитель для QMessageBox.

        Returns:
            True если команда отправлена, False при отсутствии proxy / ошибке.
        """
        from PySide6.QtWidgets import QMessageBox

        from .io import graph_to_blueprint

        proxy = self._pm_proxy
        if proxy is None or not hasattr(proxy, "apply_topology"):
            QMessageBox.warning(
                parent,
                "Перезапустить",
                "ProcessManager-proxy недоступен.\nУправление возможно только при работающей системе.",
            )
            return False

        bp_dict, _bindings, _gui_positions = graph_to_blueprint(self._model)
        try:
            result = proxy.apply_topology(bp_dict)
            if result is not None and result.get("success", False):
                self._notify_status("Команда перезапуска топологии отправлена в backend")
                return True
            QMessageBox.critical(
                parent,
                "Перезапустить",
                f"Не удалось отправить команду: {(result or {}).get('error') or 'неизвестная ошибка'}",
            )
            return False
        except Exception as exc:
            logger.exception("restart_topology failed")
            QMessageBox.critical(parent, "Перезапустить", f"Ошибка: {exc}")
            return False

    def control_process(self, action: str, process_name: str, parent: "QWidget | None" = None) -> bool:
        """Управление одним процессом по имени (Task 1.2): start / stop / restart.

        Args:
            action: "start" | "stop" | "restart".
            process_name: имя процесса (НЕ адрес — per-worker управление это Этап 3).
            parent: родитель для QMessageBox.

        Returns:
            True если команда отправлена, False при отсутствии proxy / неизвестном action.
        """
        from PySide6.QtWidgets import QMessageBox

        proxy = self._pm_proxy
        method = {
            "start": getattr(proxy, "start_process", None) if proxy else None,
            "stop": getattr(proxy, "stop_process", None) if proxy else None,
            "restart": getattr(proxy, "restart_process", None) if proxy else None,
        }.get(action)

        if proxy is None or method is None:
            QMessageBox.warning(
                parent,
                "Управление процессом",
                "ProcessManager-proxy недоступен или действие не поддержано.",
            )
            return False
        if not process_name:
            QMessageBox.warning(parent, "Управление процессом", "Не выбран процесс")
            return False

        try:
            method(process_name)
            labels = {"start": "запуск", "stop": "остановка", "restart": "перезапуск"}
            self._notify_status(f"Команда '{labels[action]}' процесса '{process_name}' отправлена")
            return True
        except Exception as exc:
            logger.exception("control_process(%s, %s) failed", action, process_name)
            QMessageBox.critical(parent, "Управление процессом", f"Ошибка: {exc}")
            return False

    def _notify_status(self, message: str, *, level: str = "info") -> None:
        """Показать статус через notify-callback (statusBar) + лог в терминал.

        Не-модально: вместо блокирующих QMessageBox результат команды виден в
        статусной строке и в логе (терминал). ``level`` — уровень логгера
        ("info"/"warning"/"error").
        """
        getattr(logger, level, logger.info)(message)
        if self._notify is not None:
            self._notify(message)

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
