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
from typing import TYPE_CHECKING, Any, Callable, ContextManager, Iterator

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.events import RecipeActivated, TopologyReplaced

from .graph.data import DisplayNodeData, EdgeData, NodeData, PortSchema
from .graph_codec import GraphViewState, TopologyGraphCodec
from .layout_controller import LayoutController
from .model import PipelineModel
from .mutations import PipelineMutations
from .runtime_control import RuntimeController
from .telemetry import WireMetricsModel
from .wire_validation import validate_wire_ports

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_prototype.domain.protocols import Subscription

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
        command_sender: Any = None,
        topology_bridge: Any = None,
        topology_session: Any = None,
    ) -> None:
        self._services = services
        # RS-4 dirty-контур: сессия редактора топологии. mark_saved (сохранение в
        # рецепт), mark_applied («Перезапустить» = граф→backend), mark_loaded (загрузка
        # из файла). Правки/undo помечает dirty сам EventBus-мост в app.py (TopologyReplaced).
        # None → без dirty-контура (характеризация: поведение до RS-4).
        self._topology_session = topology_session
        # GuiStateBindings — для actual-телеметрии камеры в инспекторе (Phase 3).
        self._bindings = bindings
        # command_sender + topology_bridge — для встраиваемых контролов камеры
        # Hikvision в инспекторе ноды (request/response enum/params + live-команды).
        self._command_sender = command_sender
        self._topology_bridge = topology_bridge
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
        # F.2: чистый (Qt-free) codec топология→граф. GUI-состоянием
        # (позиции/локи/placed-боксы) владеет LayoutController (F.7); presenter
        # берёт его снимком у контроллера и передаёт GraphViewState; кэши
        # портов/боксов codec возвращает, presenter кладёт их в свои поля.
        self._codec = TopologyGraphCodec(services.plugins, services.displays)
        self._scene: GraphScene | None = None
        self._suppress = False
        # G.4.2: кэш port_schemas (node_id → схемы), заполняется _topology_to_graph,
        # читается load_scene_with_ports. Инициализируем здесь, чтобы метод рендера
        # не падал AttributeError при вызове до первого _topology_to_graph.
        self._port_schemas_cache: dict[str, list[PortSchema]] = {}
        # G.4.2b: кэш display-боксов (по одному на display_id), заполняется
        # _topology_to_graph из topo["displays"], читается load_scene_with_ports.
        self._display_nodes_cache: list[DisplayNodeData] = []

        # Модель телеметрии wire-соединений (Task 7b.3)
        self._wire_metrics_model = WireMetricsModel()

        # F.3: контроллер команд управления живым backend (launch/restart/control).
        # Runtime-объекты (pm_proxy, recipes, model) стабильны за время жизни
        # presenter — передаём их снимком; scene/позиций контроллер не касается.
        self._runtime = RuntimeController(
            pm_proxy=process_manager_proxy,
            recipes=services.recipes,
            model=self._model,
            notify=notify,
            # RS-4 (Fable #3): diverged снимается ТОЛЬКО при подтверждённом success apply
            # (в _on_restart_result), не по факту отправки fire-and-forget.
            on_applied=(self._topology_session.mark_applied if self._topology_session is not None else None),
        )

        # Ленивый импорт TopologyPresenter (для load/save YAML)
        from multiprocess_prototype.frontend.widgets.topology.presenter import TopologyPresenter

        self._topo = TopologyPresenter()

        # F.4/F.7: контроллеры layout-состояния и graph-мутаций. ВЛАДЕЛЕЦ GUI-
        # состояния (gui_positions/locked_nodes/placed_display_ids/persist_timer) —
        # LayoutController (F.7); presenter и PipelineMutations читают/пишут его
        # ТОЛЬКО через публичный API контроллера. Стабильные зависимости
        # (services/model/topo) инжектятся снимком (по образцу RuntimeController,
        # F.3); Qt-реакции presenter отдаёт через host-контракт PipelineHost (self).
        # Публичные методы presenter — тонкие делегаты в контроллеры.
        self._layout = LayoutController(self, services=services, model=self._model, topo=self._topo)
        self._mutations = PipelineMutations(
            self,
            services=services,
            model=self._model,
            layout=self._layout,
            report=self._report,
        )

        # Scene reload через typed EventBus (G.1): store публикует TopologyReplaced
        # при каждом save/set_topology (G.3). dispatch() внутри себя вызывает
        # topology_repo.save() → publish → _on_topology_replaced (full reload).
        self._topology_sub: "Subscription | None" = services.events.subscribe(
            TopologyReplaced, self._on_topology_replaced
        )

        # Task 2.1: смена рецепта = «новая сессия редактора». Очищаем placed-but-unbound
        # боксы ИМЕННО здесь, а НЕ в _on_topology_replaced. Обоснование точкой в коде:
        # domain Project._apply_activate_recipe (project.py:781-784) эмитит ДВА события —
        # TopologyReplaced (общий reload, на него же завязаны add/remove/wire/undo/redo)
        # и RecipeActivated (только при ActivateRecipe). Обычная мутация в рамках сессии
        # шлёт ТОЛЬКО TopologyReplaced. Поэтому RecipeActivated — единственный надёжный
        # маркер «новая сессия»: чистить set в _on_topology_replaced убило бы непривязанный
        # бокс при первой же мутации (главный риск задачи, см. plans/pipeline-place-display-node.md).
        self._recipe_activated_sub: "Subscription | None" = services.events.subscribe(
            RecipeActivated, self._on_recipe_activated
        )

    def dispose(self) -> None:
        """Teardown presenter'а: отписки EventBus + остановка таймера + разрыв ссылок.

        Волна B (M-leak-3): подписки TopologyReplaced/RecipeActivated нигде не
        отписывались — EventBus держит сильную ссылку на handler → на presenter →
        на scene, и разрушенная вкладка продолжала получать события (обновление
        мёртвых Qt-объектов). Вызывается из PipelineTab.dispose()
        (closeEvent / destroyed). Идемпотентен — повторный вызов безопасен.

        Трогает только Python-состояние (подписки, ссылки) и parentless-QTimer,
        поэтому безопасен и в destroyed-пути, когда дочерние Qt-виджеты уже мертвы.
        """
        if self._topology_sub is not None:
            self._topology_sub.unsubscribe()
            self._topology_sub = None
        if self._recipe_activated_sub is not None:
            self._recipe_activated_sub.unsubscribe()
            self._recipe_activated_sub = None
        # Н-3: дебаунс-таймер авто-персиста — владелец LayoutController (F.7).
        # stop_persist_timer идемпотентен и безопасен в destroyed-пути (singleShot
        # QTimer БЕЗ parent; без stop() отложенный timeout дёрнул бы персист на
        # мёртвом окружении, scene уже удалена).
        self._layout.stop_persist_timer()
        # Разорвать ссылки на Qt-объекты: presenter после dispose scene/inspector не трогает.
        self._scene = None
        self._inspector = None

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
            command_sender=self._command_sender,
            topology_bridge=self._topology_bridge,
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
        """Изменение поля из NodeInspectorPanel (делегат PipelineMutations, F.4)."""
        self._mutations._on_inspector_field_changed(process_name, field_name, new_value)

    def _on_target_process_changed(self, node_id: str, new_process: str) -> None:
        """Выбор нового целевого процесса plugin-узла (делегат PipelineMutations, F.4)."""
        self._mutations._on_target_process_changed(node_id, new_process)

    def _on_display_id_changed(self, node_id: str, new_display_id: str) -> None:
        """Смена display-канала бокса (делегат PipelineMutations, F.4)."""
        self._mutations._on_display_id_changed(node_id, new_display_id)

    def _on_move_to_process_requested(self, from_process: str, to_process: str) -> None:
        """Перенос всех плагинов узла в другой процесс (делегат PipelineMutations, F.4)."""
        self._mutations._on_move_to_process_requested(from_process, to_process)

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
    #  Host-контракт для контроллеров (PipelineHost, F.7)                  #
    # ------------------------------------------------------------------ #
    # Узкий публичный GUI-реакционный интерфейс: контроллеры (LayoutController,
    # PipelineMutations) обращаются к presenter ТОЛЬКО через эти члены, без
    # доступа к приватным полям. Приватные методы/поля (_scene/_block_signals/…)
    # сохранены дословно — их дёргают напрямую характеризационные тесты presenter.

    @property
    def scene(self) -> "GraphScene | None":
        """Текущая GraphScene (host-контракт)."""
        return self._scene

    @property
    def inspector(self) -> Any:
        """Привязанная NodeInspectorPanel или None (host-контракт)."""
        return getattr(self, "_inspector", None)

    def block_signals(self) -> ContextManager[None]:
        """Контекст подавления сигналов (host-контракт, делегат _block_signals)."""
        return self._block_signals()

    def topology_to_graph(self, topo_dict: dict) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертация topology dict → граф (host-контракт, делегат _topology_to_graph)."""
        return self._topology_to_graph(topo_dict)

    def capture_selection(self) -> list[str]:
        """Снять выделение до reload (host-контракт, делегат _capture_selection)."""
        return self._capture_selection()

    def restore_selection(self, node_ids: list[str]) -> None:
        """Восстановить выделение после reload (host-контракт, делегат _restore_selection)."""
        self._restore_selection(node_ids)

    def validate_wire_ports(
        self,
        source: str,
        target: str,
        parent: "QWidget | None" = None,
    ) -> bool:
        """Проверка портов + QMessageBox (host-контракт, делегат _validate_wire_ports)."""
        return self._validate_wire_ports(source, target, parent)

    def report(self, message: str) -> None:
        """Notify-статус пользователю (host-контракт, делегат _report)."""
        self._report(message)

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load_topology_from_config(self) -> tuple[list[NodeData], list[EdgeData]]:
        """Загрузить topology из живого источника (делегат LayoutController, F.4)."""
        return self._layout.load_topology_from_config()

    def load_topology_from_file(self, path: Path) -> tuple[list[NodeData], list[EdgeData]]:
        """Загрузить topology из YAML файла (делегат LayoutController, F.4)."""
        result = self._layout.load_topology_from_file(path)
        # RS-4 (Fable #4): загруженный из внешнего файла граф не существует ни в одном
        # рецепте → это НЕсохранённое содержимое (dirty=True) и не применённое к живой
        # системе (diverged=True) — mark_edited. Иначе класс C-2/C-5 вернулся бы, как
        # только появится import-кнопка.
        if self._topology_session is not None:
            self._topology_session.mark_edited()
        return result

    def export_topology_with_positions(self) -> dict:
        """Экспортировать topology dict с gui_positions (делегат LayoutController, F.4)."""
        return self._layout.export_topology_with_positions()

    def save_topology_to_file(self, path: Path) -> None:
        """Сохранить topology с позициями в YAML (делегат LayoutController, F.4)."""
        self._layout.save_topology_to_file(path)

    # ------------------------------------------------------------------ #
    #  Мутации через domain dispatch (process); display — legacy (G.4.2b)  #
    # ------------------------------------------------------------------ #

    def add_process_from_plugin(self, plugin_name: str, x: float = 0.0, y: float = 0.0) -> str | None:
        """Добавить процесс из палитры плагинов (делегат PipelineMutations, F.4)."""
        return self._mutations.add_process_from_plugin(plugin_name, x, y)

    def remove_selected(self, selected_node_ids: list[str]) -> None:
        """Удалить выбранные ноды и display-боксы (делегат PipelineMutations, F.4)."""
        self._mutations.remove_selected(selected_node_ids)

    def add_wire(self, source: str, target: str, parent: "QWidget | None" = None) -> bool:
        """Добавить wire/binding с валидацией портов (делегат PipelineMutations, F.4)."""
        return self._mutations.add_wire(source, target, parent)

    def remove_wire(self, source: str, target: str) -> bool:
        """Удалить wire/binding source→target (делегат PipelineMutations)."""
        return self._mutations.remove_wire(source, target)

    def place_display(self, display_id: str, x: float, y: float) -> None:
        """Разместить пустой display-бокс на холсте (делегат PipelineMutations, F.4)."""
        self._mutations.place_display(display_id, x, y)

    def _validate_wire_ports(
        self,
        source: str,
        target: str,
        parent: "QWidget | None" = None,
    ) -> bool:
        """Проверить совместимость портов + показать QMessageBox при отказе (делегат).

        F.3: чистая проверка совместимости вынесена в
        :func:`wire_validation.validate_wire_ports` (Qt-free, заморожена
        ``tests/test_wire_validation.py``). presenter отвечает только за GUI-реакцию:
        на несовместимость поднимает QMessageBox с типами портов. Graceful
        degradation (каталог/плагин/порт не найден) → ``ok=True`` → wire разрешён.

        Returns:
            True -- wire можно создать, False -- wire заблокирован.
        """
        result = validate_wire_ports(source, target, self._services.plugins)
        if result.ok:
            return True

        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            parent,
            "Несовместимые порты",
            f"Невозможно соединить порты:\n"
            f"  Источник: {source}\n"
            f"  Тип: {result.src_dtype}\n\n"
            f"  Приёмник: {target}\n"
            f"  Тип: {result.tgt_dtype}\n\n"
            f"Типы данных несовместимы.",
        )
        return False

    def on_node_moved(self, node_id: str, new_x: float, new_y: float) -> None:
        """Свободное перемещение ноды free-layout (делегат LayoutController, F.4)."""
        self._layout.on_node_moved(node_id, new_x, new_y)

    def set_node_lock(self, node_id: str, locked: bool) -> None:
        """Зафиксировать/освободить ноду явно (делегат LayoutController, F.4)."""
        self._layout.set_node_lock(node_id, locked)

    def _sync_positions_from_scene(self) -> None:
        """Синхронизировать _gui_positions со сценой (делегат LayoutController, F.4)."""
        self._layout._sync_positions_from_scene()

    def _persist_layout_to_recipe(self) -> None:
        """Тихо сохранить позиции/фиксацию в рецепт (делегат LayoutController, F.4)."""
        self._layout._persist_layout_to_recipe()

    def toggle_node_lock(self, node_id: str) -> None:
        """Переключить фиксацию ноды (делегат LayoutController, F.4)."""
        self._layout.toggle_node_lock(node_id)

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
        # пишет позицию только в scene, а reload берёт позиции из gui_positions
        # (владелец — LayoutController, F.7). Без этого sync любая мутация
        # (TopologyReplaced) сбрасывала бы вручную передвинутые ноды на дефолт.
        if self._scene:
            self._layout.gui_positions.update(self._scene.get_all_node_positions())
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
        if not self._layout.placed_display_ids:
            return
        self._layout.placed_display_ids.clear()
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
        """Применить Sugiyama auto-layout на уровне процессов (делегат LayoutController, F.4)."""
        self._layout.auto_layout_scene()

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
        from .recipe_io import recipe_blueprint

        store = self._services.recipes
        active = store.get_active()
        if active is None:
            return None
        raw = store.read_raw(active)
        if raw is None:
            logger.warning("compute_active_recipe_diff: рецепт '%s' нечитаем", active)
            return None
        # SC-12: единая READ-точка разбора формата рецепта (v3 top-level / legacy
        # data.blueprint) — recipe_io.recipe_blueprint поверх backend.unwrap_recipe.
        saved = recipe_blueprint(raw)
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
        """Конвертировать topology dict → NodeData/EdgeData (делегат codec'а).

        F.2: чистая логика вынесена в :class:`TopologyGraphCodec` (graph_codec.py,
        Qt-free, заморожена характеризационными тестами). presenter владеет GUI-
        состоянием — передаёт его снимком ``GraphViewState`` и раскладывает
        возвращённые кэши по своим полям (``_port_schemas_cache``/
        ``_display_nodes_cache``), сохраняя прежний контракт метода: возвращает
        ``(nodes, edges)`` и наполняет кэши как побочный эффект.
        """
        view = GraphViewState(
            gui_positions=self._layout.gui_positions,
            locked_nodes=self._layout.locked_nodes,
            placed_display_ids=self._layout.placed_display_ids,
        )
        result = self._codec.topology_to_graph(topo_dict, view)
        self._port_schemas_cache = result.port_schemas
        self._display_nodes_cache = result.display_nodes
        return result.nodes, result.edges

    def _resolve_display_name(self, display_id: str) -> str:
        """Человекочитаемое имя канала из DisplayCatalog (делегат codec'а)."""
        return self._codec.resolve_display_name(display_id)

    def _blueprint_to_graph(self, bp) -> tuple[list[NodeData], list[EdgeData]]:
        """Конвертировать SystemBlueprint в граф-данные."""
        data = bp.model_dump() if hasattr(bp, "model_dump") else {}
        return self._topology_to_graph(data)

    # ------------------------------------------------------------------ #
    #  Сохранение в рецепт                                                #
    # ------------------------------------------------------------------ #

    def save_to_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Сохранить текущий граф в активный рецепт (делегат LayoutController, F.4)."""
        ok = self._layout.save_to_active_recipe(parent)
        # RS-4: граф записан в рецепт → снять dirty (diverged держится: файл ≠ live).
        if ok and self._topology_session is not None:
            self._topology_session.mark_saved()
        return ok

    # ------------------------------------------------------------------ #
    #  Runtime-контроль живого backend (делегаты RuntimeController, F.3)   #
    # ------------------------------------------------------------------ #
    # Логика вынесена в :class:`runtime_control.RuntimeController` (launch/
    # restart/control + разбор PM-ответа + notify). presenter сохраняет
    # публичные методы как тонкие делегаты — контракт вкладки не изменён.

    def launch_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Запустить активный рецепт через ProcessManager-proxy (делегат F.3)."""
        return self._runtime.launch_active_recipe(parent)

    def restart_topology(self, parent: "QWidget | None" = None) -> bool:
        """Применить текущий граф редактора к живому backend (делегат F.3).

        RS-4 (Fable #3): diverged снимается НЕ здесь (по факту отправки), а в
        RuntimeController._on_restart_result при ПОДТВЕРЖДЁННОМ success apply —
        через on_applied=session.mark_applied (async request/response).
        """
        return self._runtime.restart_topology(parent)

    def control_process(self, action: str, process_name: str, parent: "QWidget | None" = None) -> bool:
        """Start / stop / restart процесса по имени (делегат F.3)."""
        return self._runtime.control_process(action, process_name, parent)

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
