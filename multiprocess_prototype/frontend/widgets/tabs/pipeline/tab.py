# -*- coding: utf-8 -*-
"""PipelineTab — визуальный конструктор pipeline на едином columnar-шаблоне.

Task E.1: мигрирован на AppServices DI. Принимает services: AppServices.
Task F.9: create(services, runtime) — Q-F1=B. AppContext bridge убран.
G.4.2: ActionBus bridge удалён; undo/redo через services.commands (domain dispatch).

3 колонки + мастер-скролл через ``DiffScrollTabLayout``:

- **action-колонка (1-я)**: все кнопки управления (Delete / Layout / Validate /
  Fit / Zoom+ / Zoom-);
- **nav-колонка (2-я)**: ``PluginPalette`` — дерево плагинов по категориям +
  поиск + D&D на canvas;
- **content-колонка (3-я)**: вертикальный QSplitter с canvas (``GraphView``)
  сверху и ``NodeInspectorPanel`` (параметры выбранной ноды) снизу.

Внутренний скролл canvas НЕ передаётся в master-scrollbar — wheel на канве
выполняет zoom (нативное поведение ``GraphView``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.events import ProcessAdded
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .graph.graph_scene import GraphScene
from .graph.graph_view import GraphView
from .inspector import NodeInspectorPanel
from .palette import PipelineDropTarget, PluginPalette
from .presenter import PipelinePresenter

if TYPE_CHECKING:
    from PySide6.QtCore import QPointF

    from multiprocess_framework.modules.registers_module import RegistersManager


# Размеры колонок:
# - action_width: 180 — нужно место под 6 кнопок управления (Delete..Zoom);
# - nav_width:   345 — как в Plugins (русские имена категорий + tooltip).
_ACTION_WIDTH = 180
_NAV_WIDTH = 345


class PipelineTab(QWidget):
    """Таб визуального конструктора pipeline на ``DiffScrollTabLayout``.

    3 колонки (actions / palette / canvas+inspector) + мастер-скролл +
    QGroupBox-заголовок. Тулбар разнесён по action-колонке; Undo/Redo —
    в статичной зоне. Палитра плагинов — во 2-й колонке (дерево + поиск).
    Canvas + Inspector — в 3-й колонке через вертикальный сплиттер.
    """

    _MUTATING_ACTIONS = frozenset({"delete", "auto_layout", "save_recipe", "launch_recipe"})
    # Этап 1 pipeline-live-control: команды управления живым backend через proxy.
    # Привилегированные (gating под tabs.pipeline.edit), но не мутируют граф-модель.
    _CONTROL_ACTIONS = frozenset({"restart_topology", "proc_start", "proc_stop", "proc_restart"})

    def __init__(
        self,
        services: AppServices,
        *,
        registers_manager: "RegistersManager | None" = None,
        process_manager_proxy: object | None = None,
        bindings: object | None = None,
        command_sender: object | None = None,
        topology_bridge: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        # Волна B (M-leak-3): guard идемпотентности teardown (см. dispose()).
        self._disposed = False
        self._presenter = PipelinePresenter(
            services,
            registers_manager=registers_manager,
            notify=self._show_status,
            process_manager_proxy=process_manager_proxy,
            bindings=bindings,
            command_sender=command_sender,
            topology_bridge=topology_bridge,
        )

        self._tab_layout = DiffScrollTabLayout(
            title="Pipeline",
            action_width=_ACTION_WIDTH,
            nav_width=_NAV_WIDTH,
        )

        # --- Action column: 6 кнопок (undo/redo — в статичной зоне) ---
        self._tab_layout.set_action_widget(self._build_action_widget())

        # --- Nav column: PluginPalette (дерево + поиск + D&D) ---
        self._palette = PluginPalette()
        self._tab_layout.set_nav_widget(self._palette)

        # --- Content column: canvas + inspector через QSplitter ---
        self._scene = GraphScene()
        self._view = GraphView(self._scene)
        self._inspector = NodeInspectorPanel()
        self._content_splitter = QSplitter(Qt.Orientation.Vertical)
        self._content_splitter.addWidget(self._view)
        self._content_splitter.addWidget(self._inspector)
        self._content_splitter.setStretchFactor(0, 3)  # canvas — 3/4
        self._content_splitter.setStretchFactor(1, 1)  # inspector — 1/4
        self._tab_layout.set_content_widget(self._content_splitter)

        # ВАЖНО: на canvas viewport DiffScrollTabLayout автоматически
        # устанавливает event filter и перехватывает wheel в master-scrollbar.
        # Это ломает zoom в GraphView. Снимаем filter — wheel на канве уйдёт
        # в её собственный wheelEvent (zoom).
        self._view.viewport().removeEventFilter(self._tab_layout)

        # G.4.4: undo/redo кнопки подключены к domain CommandDispatcher.
        # services.commands удовлетворяет UndoRedoController (undo/redo/can_undo/
        # can_redo/add_change_callback) → layout сам рефрешит enabled-состояние
        # кнопок по change-callback после каждого dispatch/undo/redo.
        # Глобальные Ctrl+Z/Y вешает MainWindow.set_undo_controller на ту же шину.
        self._tab_layout.enable_undo_redo(self._services.commands)

        # Передать scene и inspector в presenter.
        self._presenter.set_scene(self._scene)
        self._presenter.set_inspector(self._inspector)

        # Task 1.1: прокинуть display-каналы в scene для подменю «Add Display →».
        # Scene не имеет доступа к services — список каналов всегда приходит из tab.
        channels = [(s.display_id, s.display_name) for s in self._services.displays.list_displays()]
        self._scene.set_display_channels(channels)

        # Создать контроллер телеметрии edges (Task 7b.3)
        from .telemetry import WireMetricsController

        self._wire_metrics_controller = WireMetricsController(
            self._scene,
            self._presenter.wire_metrics_model,
            parent=self,
        )
        self._wire_metrics_controller.start()

        # Drop target для D&D из палитры на canvas: плагины → процесс,
        # дисплеи → display-бокс (place_display).
        self._drop_target = PipelineDropTarget(
            self._view,
            self._on_plugin_dropped,
            on_display_drop=self._on_display_dropped,
        )

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        main_layout.addWidget(self._tab_layout)

        self._connect_signals()
        self._load_topology()
        self._load_palette()

        # Волна B (M-leak-3): teardown-хук на оба реальных пути уничтожения вкладки.
        # closeEvent приходит не всегда (вкладка в QTabWidget обычно умирает через
        # deleteLater/разрушение родителя без close()), поэтому дублируем на destroyed.
        # dispose() идемпотентен и в destroyed-пути трогает только Python-состояние
        # (подписки), не C++-объекты. Lambda, а не bound-метод: PySide6 хранит
        # bound-методы QObject-получателя слабой связью, и на умирающем объекте
        # такой слот мог бы не сработать.
        self.destroyed.connect(lambda *_, tab=self: tab.dispose())

    def dispose(self) -> None:
        """Teardown вкладки: снять EventBus-подписки presenter'а/таба и cam-подписки инспектора.

        Волна B (M-leak-3 + Н-3 + Н-4). Идемпотентен — повторный вызов no-op.
        Вызывается из closeEvent И по сигналу destroyed — каким бы путём вкладка
        ни уничтожалась (close(), deleteLater, разрушение родителя), подписки
        снимаются ровно один раз.
        """
        if self._disposed:
            return
        self._disposed = True
        # G.6.1-подписка auto-reveal (ProcessAdded) — та же категория утечки:
        # EventBus держит сильную ссылку на handler → на tab.
        sub = getattr(self, "_process_added_sub", None)
        if sub is not None:
            sub.unsubscribe()
            self._process_added_sub = None
        self._presenter.dispose()
        self._inspector.dispose()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Снять подписки при закрытии вкладки (штатный Qt-путь teardown)."""
        self.dispose()
        super().closeEvent(event)

    @classmethod
    def create(
        cls,
        services: AppServices,
        runtime: RuntimeDeps = RuntimeDeps(),
    ) -> "PipelineTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        G.2: registers_manager — runtime-объект (live-регистры) для inspector-карточек.
        Этап 1: process_manager_proxy — IPC-фасад управления живым backend.
        """
        return cls(
            services,
            registers_manager=runtime.registers_manager,
            process_manager_proxy=runtime.process_manager_proxy,
            bindings=runtime.bindings,
            command_sender=runtime.command_sender,
            topology_bridge=runtime.topology_bridge,
        )

    # ------------------------------------------------------------------ #
    #  Build helpers                                                       #
    # ------------------------------------------------------------------ #

    def _build_action_widget(self) -> QWidget:
        """6 кнопок управления в action-колонке."""
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        self._action_buttons: dict[str, QPushButton] = {}
        for action_id, label in [
            ("delete", "Удалить"),
            ("auto_layout", "Раскладка"),
            ("validate", "Валидация"),
            ("diff", "Изменения"),
            ("save_recipe", "Сохранить"),
            ("launch_recipe", "Запустить"),
            ("restart_topology", "Перезапустить"),
            ("proc_start", "Старт процесса"),
            ("proc_stop", "Стоп процесса"),
            ("proc_restart", "Рестарт процесса"),
            ("fit", "По размеру"),
            ("zoom_in", "Zoom +"),
            ("zoom_out", "Zoom −"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_toolbar_action(aid))
            action_layout.addWidget(btn)
            self._action_buttons[action_id] = btn

        action_layout.addStretch(1)

        # Permission gating через AuthFacade Protocol (F.6).
        for aid in ("delete", "auto_layout", "save_recipe", "launch_recipe", *self._CONTROL_ACTIONS):
            install_permission_aware_enable(
                self._action_buttons[aid],
                "tabs.pipeline.edit",
                self._services.auth,
            )

        return action_widget

    # ------------------------------------------------------------------ #
    #  Signals / topology / palette                                        #
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        """Подключить сигналы виджетов."""
        self._view.wire_created.connect(self._on_wire_created)
        self._scene.selectionChanged.connect(self._on_selection_changed)
        # Task 1.1: размещение пустого display-бокса через меню фона.
        self._scene.add_display_requested.connect(self._on_add_display_requested)
        # Follow-up #6: контекстное меню узлов — Delete / Inspect.
        # Работает для NodeItem и DisplayNodeItem (оба имеют node_id).
        self._scene.node_delete_requested.connect(self._on_node_delete_requested)
        self._scene.node_inspect_requested.connect(self._on_node_inspect_requested)
        # Фиксация ноды (контекстное меню «Зафиксировать/Открепить»).
        self._scene.node_lock_toggle_requested.connect(self._on_node_lock_toggle)
        # free-layout: drag меняет ТОЛЬКО позицию ноды (не процесс) → персист в рецепт.
        self._scene.node_position_changed.connect(self._on_node_position_changed)
        # G.4.4: field_changed → presenter._on_inspector_field_changed (dispatch
        # SetPluginConfig, G.4.3) подключается в presenter.set_inspector. Дублирующий
        # tab-коннект (только лог + stale TODO) убран.

        # G.6.1: auto-reveal — раскрыть новую ноду в viewport. Подписка хранится в
        # self (EventBus держит сильную ссылку на handler). Порядок dispatch:
        # TopologyReplaced (presenter reload) ДО ProcessAdded → к этому моменту нода
        # уже на scene. undo/redo НЕ переигрывает ProcessAdded → reveal только на
        # прямое добавление (центрировать при undo было бы дезориентирующе).
        self._process_added_sub = self._services.events.subscribe(ProcessAdded, self._on_process_added)

    def _on_process_added(self, event: ProcessAdded) -> None:
        """G.6.1: центрировать вид на только что добавленной ноде."""
        item = self._scene.get_node(event.process_name)
        if item is not None:
            self._view.reveal_node(item)

    def _show_diff(self) -> None:
        """G.6.4: показать дифф текущей топологии vs активный рецепт."""
        from PySide6.QtWidgets import QMessageBox

        diff = self._presenter.compute_active_recipe_diff()
        if diff is None:
            QMessageBox.information(self, "Изменения", "Нет активного рецепта для сравнения")
            return
        if diff.is_empty:
            QMessageBox.information(self, "Изменения", "Нет несохранённых изменений")
            return
        QMessageBox.information(self, "Изменения", "\n".join(diff.summary()))

    def _show_status(self, message: str) -> None:
        """G.6.2: показать сообщение в statusBar главного окна.

        Передаётся в PipelinePresenter как notify-callback. Резолвит окно лениво
        (в момент вызова окно уже существует). Guard на отсутствие QMainWindow/
        statusBar (headless-тесты) — тогда no-op (presenter всё равно логирует).
        """
        window = self.window()
        status_bar = getattr(window, "statusBar", None)
        if callable(status_bar):
            status_bar().showMessage(message, 5000)

    def _load_topology(self) -> None:
        """Загрузить topology из AppContext и отобразить.

        G.4.2: presenter.load_topology_from_config() + load_scene_with_ports()
        для корректной установки port_schemas на нодах.
        """
        nodes, edges = self._presenter.load_topology_from_config()
        # G.4.2: рендер через presenter (port_schemas из PluginCatalog), не голый load_from_data
        self._presenter.load_scene_with_ports(nodes, edges)
        if nodes:
            # НЕ авто-раскладываем при загрузке: ноды встают по сохранённым позициям
            # (gui_positions) или дефолтному кластеру. Авто-раскладка — только по
            # кнопке «Раскладка» (пользователь сам решает, когда перестроить граф).
            self._view.fit_to_view()

    def _load_palette(self) -> None:
        """Загрузить плагины и дисплеи в палитру (services.plugins / services.displays).

        Плагины — основной список (drag → создаёт процесс). Дисплеи — отдельная
        секция «Displays — дисплеи» (drag → создаёт display-бокс на холсте, в который
        пользователь заводит провод от источника). Дисплеи берём из того же каталога,
        что и подменю «Add Display →» сцены (services.displays.list_displays()).
        """
        plugin_specs = self._services.plugins.list_plugins()
        plugins = [
            {"name": spec.name, "category": spec.category, "description": spec.description} for spec in plugin_specs
        ]
        if plugins:
            self._palette.load_plugins(plugins)

        displays = [
            {"display_id": s.display_id, "display_name": s.display_name}
            for s in self._services.displays.list_displays()
        ]
        if displays:
            self._palette.load_displays(displays)

    # ------------------------------------------------------------------ #
    #  Permissions                                                         #
    # ------------------------------------------------------------------ #

    def _can_edit(self) -> bool:
        """Имеет ли текущий пользователь право на mutation в pipeline."""
        return self._services.auth.has_permission("tabs.pipeline.edit")

    # ------------------------------------------------------------------ #
    #  Action handlers                                                     #
    # ------------------------------------------------------------------ #

    def _selected_process_name(self) -> str:
        """Имя процесса выбранной ноды (Task 1.2). Пусто если нет выбора.

        Плагин-нода знает свой процесс через ``process_name`` (D.1). Для управления
        процессом (start/stop/restart) берём процесс выбранной ноды.
        """
        for item in self._scene.selectedItems():
            pname = getattr(item, "process_name", "") or getattr(item, "node_id", "")
            if pname:
                return pname
        return ""

    def _on_toolbar_action(self, action_id: str) -> None:
        if action_id in self._MUTATING_ACTIONS and not self._can_edit():
            return
        if action_id in self._CONTROL_ACTIONS and not self._can_edit():
            return
        if action_id == "restart_topology":
            self._presenter.restart_topology(parent=self)
            return
        if action_id in ("proc_start", "proc_stop", "proc_restart"):
            verb = {"proc_start": "start", "proc_stop": "stop", "proc_restart": "restart"}[action_id]
            self._presenter.control_process(verb, self._selected_process_name(), parent=self)
            return
        if action_id == "zoom_in":
            self._view.zoom_in()
        elif action_id == "zoom_out":
            self._view.zoom_out()
        elif action_id == "fit":
            self._view.fit_to_view()
        elif action_id == "validate":
            errors = self._presenter.validate()
            from PySide6.QtWidgets import QMessageBox

            if errors:
                QMessageBox.warning(self, "Валидация", "\n".join(errors))
            else:
                QMessageBox.information(self, "Валидация", "Topology валидна")
        elif action_id == "diff":
            self._show_diff()
        elif action_id == "save_recipe":
            self._presenter.save_to_active_recipe(parent=self)
        elif action_id == "launch_recipe":
            self._presenter.launch_active_recipe(parent=self)
        elif action_id == "auto_layout":
            self._presenter.auto_layout_scene()
        elif action_id == "delete":
            selected = [item.node_id for item in self._scene.selectedItems() if hasattr(item, "node_id")]
            if selected:
                self._presenter.remove_selected(selected)
                self._inspector.clear()
        # G.4.4: undo/redo больше не toolbar-action — кнопки layout'а зовут
        # services.commands напрямую (enable_undo_redo), а Ctrl+Z/Y — глобально
        # через MainWindow.set_undo_controller. Единая шина undo (баг dual-undo закрыт).

    def _on_plugin_dropped(self, plugin_name: str, scene_pos: "QPointF") -> None:
        """D&D из палитры → создать процесс на canvas."""
        if not self._can_edit():
            return
        self._presenter.add_process_from_plugin(plugin_name, scene_pos.x(), scene_pos.y())

    def _on_display_dropped(self, display_id: str, scene_pos: "QPointF") -> None:
        """D&D дисплея из палитры → разместить display-бокс в точке drop.

        Тот же путь, что подменю «Add Display →» (place_display): бокс ещё без
        привязки; пользователь заведёт в него провод от источника → BindDisplay.
        """
        if not self._can_edit():
            return
        self._presenter.place_display(display_id, scene_pos.x(), scene_pos.y())

    def _on_add_display_requested(self, display_id: str, x: float, y: float) -> None:
        """Task 1.1: разместить пустой display-бокс в точке клика.

        Permission gating: размещение — мутация, доступна только при праве
        tabs.pipeline.edit (как и D&D плагина / wire). Без права — тихий выход.
        """
        if not self._can_edit():
            return
        self._presenter.place_display(display_id, x, y)

    def _on_wire_created(self, source_endpoint: str, target_endpoint: str) -> None:
        """Wire creation через GraphView.

        Передаёт self как parent для QMessageBox при несовместимых портах.
        """
        if not self._can_edit():
            return
        self._presenter.add_wire(source_endpoint, target_endpoint, parent=self)

    def _on_node_delete_requested(self, node_id: str) -> None:
        """Контекстное меню «Delete» для узла (NodeItem или DisplayNodeItem).

        Мутирует topology → guard по праву edit.
        """
        if not self._can_edit():
            return
        self._presenter.remove_selected([node_id])
        self._inspector.clear()

    def _on_node_position_changed(self, node_id: str, x: float, y: float) -> None:
        """free-layout: нода свободно перемещена → запомнить позицию + персист в рецепт.

        Позиция — GUI-метаданные (не топология), поэтому permission-gating не нужен:
        перекомпоновка холста косметична и не меняет членство ноды в процессе.
        Смена процесса/воркера — только через combo инспектора.
        """
        self._presenter.on_node_moved(node_id, x, y)

    def _on_node_inspect_requested(self, node_id: str) -> None:
        """Контекстное меню «Inspect» для узла (NodeItem или DisplayNodeItem).

        Read-only операция: выделяет узел на scene → срабатывает _on_selection_changed
        → inspector заполняется. Permission gating НЕ нужен.
        """
        # Снимаем текущее выделение, затем выделяем запрошенный узел.
        # Это тот же путь, что и клик мышью — через _on_selection_changed.
        self._scene.clearSelection()
        item = self._scene.get_node(node_id)
        if item is not None:
            item.setSelected(True)

    def _on_node_lock_toggle(self, node_id: str) -> None:
        """Контекстное меню «Зафиксировать/Открепить» — фиксация ноды (session-only).

        Не мутирует topology (GUI-состояние), permission gating не требуется.
        """
        self._presenter.toggle_node_lock(node_id)

    def _on_selection_changed(self) -> None:
        """Обработчик изменения выбора в scene.

        Определяет тип узла (plugin vs display) и вызывает соответствующий
        метод inspector'а: show_plugin_node или show_display_node.
        """
        from .graph.display_node_item import DisplayNodeItem

        selected = self._scene.selectedItems()
        node_items = [item for item in selected if hasattr(item, "node_id")]

        if len(node_items) == 1:
            node = node_items[0]
            topo = self._presenter.model.to_topology_dict()

            if isinstance(node, DisplayNodeItem):
                # G.4.2b: id бокса = display_id канала; topo["displays"] keyed по
                # source endpoint (binding), поэтому данные берём прямо из node.data.
                display_id = getattr(node.data, "display_id", node.node_id)
                display_name = getattr(node.data, "display_name", "")
                self._inspector.show_display_node(node.node_id, display_id, display_name)
            else:
                # Plugin-узел (D.1: node_id = `{process}.{plugin}`). Извлекаем процесс
                # и индекс плагина из самой ноды — инспектор показывает config именно
                # этого плагина, а не plugins[0].
                process_name = getattr(node, "process_name", "") or node.node_id
                plugin_index = getattr(node, "plugin_index", 0)

                process_data = None
                for proc in topo.get("processes", []):
                    if isinstance(proc, dict) and proc.get("process_name") == process_name:
                        process_data = proc
                        break

                plugins = process_data.get("plugins", []) if process_data else []
                category = node.data.category if hasattr(node, "data") else "utility"
                target_process = process_data.get("target_process", "") if process_data else ""

                # Поля параметров строятся по plugin_name (имя регистра) ВЫБРАННОГО
                # плагина (D.2), значения — из его config (PluginInstance.config).
                plugin_name = ""
                params: dict = {}
                if plugins and 0 <= plugin_index < len(plugins):
                    sel = plugins[plugin_index]
                    if isinstance(sel, dict):
                        plugin_name = sel.get("plugin_name", "")
                        params = sel.get("config", {}) or {}
                    else:
                        plugin_name = getattr(sel, "plugin_name", "")
                        params = getattr(sel, "config", {}) or {}

                # Другие процессы для combo «Перенести в процесс»
                # (исключаем сам процесс и protected-процессы вроде gui).
                available_processes = []
                for proc in topo.get("processes", []):
                    if isinstance(proc, dict):
                        pname = proc.get("process_name", "")
                        protected = bool(proc.get("protected", False))
                    else:
                        pname = getattr(proc, "process_name", "")
                        protected = bool(getattr(proc, "protected", False))
                    if pname and pname != process_name and not protected:
                        available_processes.append(pname)

                self._inspector.show_plugin_node(
                    node.node_id,
                    category,
                    target_process=target_process,
                    plugin_name=plugin_name,
                    plugins=plugins,
                    params=params,
                    available_processes=available_processes,
                    process_name=process_name,
                    plugin_index=plugin_index,
                )
        else:
            self._inspector.clear()

    # ------------------------------------------------------------------ #
    #  Keyboard shortcuts                                                  #
    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event) -> None:
        key = event.key()

        # G.4.4: Ctrl+Z/Y обрабатываются глобально в MainWindow (domain undo/redo) —
        # убран дублирующий per-tab путь, который конфликтовал с глобальным shortcut.
        if key == Qt.Key.Key_Delete:
            self._on_toolbar_action("delete")
        elif key == Qt.Key.Key_F:
            self._on_toolbar_action("fit")
        elif key == Qt.Key.Key_L:
            self._on_toolbar_action("auto_layout")
        else:
            super().keyPressEvent(event)
