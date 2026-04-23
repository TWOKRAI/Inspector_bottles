# multiprocess_prototype_v3/frontend/windows/main_window/window.py
"""
MainWindow — главное окно приложения.

Layout: Header + ImagePanel + TabWidget.
Конфиг: window, header, image_panel, tabs. Сигналы шапки: action_triggered + connect_action_handlers.
Undo/Redo: Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z + кнопки в header (подключаются через ActionBus).
"""

from collections.abc import Callable
from typing import Any

from frontend_module.core.action_binding import connect_action_handlers
from frontend_module.core.qt_imports import QHBoxLayout, QMainWindow, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from frontend_module.widgets import HeaderWidget, TabWidget
from frontend_module.widgets.header import HeaderConfig
from frontend_module.widgets.header.button_style import create_header_button
from frontend_module.widgets.image_panel import ImagePanelWidget
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QLabel, QShortcut

from multiprocess_prototype_v3.frontend.app_context import FrontendAppContext

from .config import ImagePanelConfig
from .tab_factory import TabWidgetFactory, create_tab_widget_factory


class MainWindow(QMainWindow):
    """
    Главное окно: Header + ImagePanel + TabWidget.

    Параметры:
        config: dict с секциями window, header, image_panel, tabs, settings_tab
        tab_widget_factory: (widget_key, tab_config) -> QWidget; если None — собирается из config и callbacks
        header_action_handlers: {action_id: callable} для HeaderWidget.action_triggered
        header_on_unmatched: fallback (например show_window только для имён из window_registry)
        show_window_callback: устар.; эквивалент header_on_unmatched для обратной совместимости
        app_ctx: FrontendAppContext — контекст с ActionBus для undo/redo (опционально)
    """

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        show_window_callback: Callable[[str], None] | None = None,
        registers_manager: Any | None = None,
        camera_callbacks_map: dict[str, Any] | None = None,
        camera_type: str = "simulator",
        tab_widget_factory: TabWidgetFactory | None = None,
        header_action_handlers: dict[str, Callable[[], None]] | None = None,
        header_on_unmatched: Callable[[str], None] | None = None,
        app_ctx: FrontendAppContext | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config or {}
        self._registers_manager = registers_manager
        self._camera_callbacks_map = camera_callbacks_map or {}
        self._camera_type = camera_type
        self._tab_widget_factory = tab_widget_factory
        self._header_action_handlers = header_action_handlers or {}
        self._header_on_unmatched = header_on_unmatched or show_window_callback
        self._app_ctx = app_ctx
        # Кнопки undo/redo/history — заполняются в _setup_undo_redo_ui
        self._btn_undo: QPushButton | None = None
        self._btn_redo: QPushButton | None = None
        self._btn_history: QPushButton | None = None
        self._latency_label: QLabel | None = None
        self._init_ui()
        self._setup_undo_redo_ui()
        self._setup_latency_label()

    def _resolve_tab_factory(self) -> TabWidgetFactory:
        if self._tab_widget_factory is not None:
            return self._tab_widget_factory
        return create_tab_widget_factory(
            FrontendAppContext(
                config=self._config,
                registers_manager=self._registers_manager,
                camera_callbacks_map=self._camera_callbacks_map,
                camera_type=self._camera_type,
                recipe_manager=None,
            )
        )

    def _build_header_config(
        self, header_cfg: HeaderConfig | dict[str, Any] | None
    ) -> dict[str, Any]:
        """HeaderConfig | dict → dict для HeaderWidget. Legacy: logo_path → logo.path."""
        if header_cfg is None:
            return HeaderConfig().model_dump()
        if isinstance(header_cfg, HeaderConfig):
            return header_cfg.model_dump()
        cfg = dict(header_cfg)
        if "logo_path" in cfg and "logo" not in cfg:
            cfg["logo"] = {"path": cfg.pop("logo_path", None)}
        return cfg

    def _init_ui(self) -> None:
        window_cfg = self._config.get("window", {})
        header_cfg = self._config.get("header", {})
        image_panel_cfg = self._config.get("image_panel", {})
        tabs_cfg = self._config.get("tabs", [])

        self.setWindowTitle(window_cfg.get("title", "Inspector"))
        min_w = window_cfg.get("min_width", 1280)
        min_h = window_cfg.get("min_height", 720)
        self.setMinimumSize(min_w, min_h)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        header_dict = self._build_header_config(header_cfg)
        self._header = HeaderWidget(config=header_dict)
        if self._header_action_handlers or self._header_on_unmatched is not None:
            connect_action_handlers(
                self._header.action_triggered,
                handlers=self._header_action_handlers,
                on_unmatched=self._header_on_unmatched,
            )
        layout.addWidget(self._header)

        slots = image_panel_cfg.get("slots")
        if not slots:
            slots = ImagePanelConfig().model_dump()["slots"]
        self._image_panel = ImagePanelWidget(image_slots=slots)
        layout.addWidget(self._image_panel, 1)

        tab_factory = self._resolve_tab_factory()
        self._tab_widget = TabWidget()
        for tab in tabs_cfg:
            widget_key = tab.get("widget", tab.get("id", "recipes"))
            title = tab.get("title", widget_key)
            w = tab_factory(widget_key, tab)
            if w is not None:
                self._tab_widget.add_tab(w, title)
        layout.addWidget(self._tab_widget)

        self._camera_tab = None
        qt_tabs = self._tab_widget.tab_widget
        for i in range(qt_tabs.count()):
            w = qt_tabs.widget(i)
            if hasattr(w, "widget") and callable(w.widget):
                w = w.widget()
            if w and hasattr(w, "update_camera_devices"):
                self._camera_tab = w
                break

    def _setup_undo_redo_ui(self) -> None:
        """Подключить Ctrl+Z / Ctrl+Y и кнопки undo/redo в header."""
        bus = self._app_ctx.get_action_bus() if self._app_ctx else None

        # Shortcuts работают всегда (no-op при отсутствии bus)
        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._shortcut_undo.activated.connect(self._on_undo)
        self._shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._shortcut_redo.activated.connect(self._on_redo)
        self._shortcut_redo_alt = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._shortcut_redo_alt.activated.connect(self._on_redo)

        # Компактный toolbar: [↩ ↪ История ▼] в одну строку
        toolbar = QWidget()
        toolbar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(2)

        self._btn_undo = create_header_button("↩", tooltip="Отменить (Ctrl+Z)")
        self._btn_redo = create_header_button("↪", tooltip="Повторить (Ctrl+Y)")
        self._btn_history = create_header_button("История ▼", tooltip="Последние действия")

        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_redo.clicked.connect(self._on_redo)
        self._btn_history.clicked.connect(self._show_history_menu)

        self._btn_undo.setEnabled(False)
        self._btn_redo.setEnabled(False)
        self._btn_history.setEnabled(False)

        toolbar_layout.addWidget(self._btn_undo)
        toolbar_layout.addWidget(self._btn_redo)
        toolbar_layout.addWidget(self._btn_history)

        # Вставить toolbar в header layout
        header_layout = self._header.layout()
        if header_layout is not None:
            header_layout.addWidget(toolbar)

        # Подписаться на обновления bus
        if bus is not None:
            bus.add_change_callback(self._update_undo_redo_state)

    def _on_undo(self) -> None:
        """Обработчик Ctrl+Z / кнопки Undo."""
        bus = self._app_ctx.get_action_bus() if self._app_ctx else None
        if bus is not None:
            bus.undo()

    def _on_redo(self) -> None:
        """Обработчик Ctrl+Y / кнопки Redo."""
        bus = self._app_ctx.get_action_bus() if self._app_ctx else None
        if bus is not None:
            bus.redo()

    def _update_undo_redo_state(self) -> None:
        """Обновить enabled-состояние кнопок undo/redo и текст статус-бара."""
        bus = self._app_ctx.get_action_bus() if self._app_ctx else None
        if bus is None:
            return
        if self._btn_undo is not None:
            self._btn_undo.setEnabled(bus.can_undo())
        if self._btn_redo is not None:
            self._btn_redo.setEnabled(bus.can_redo())
        if self._btn_history is not None:
            self._btn_history.setEnabled(bus.can_undo())
        # Статус-бар
        self._update_status_bar(bus)

    def _update_status_bar(self, bus) -> None:
        """Обновить текст статус-бара по последнему событию bus."""
        event = bus.last_event
        if event is None:
            self.statusBar().showMessage("Готово")
            return
        event_type, action = event
        desc = action.description or action.action_type.value
        if event_type == "undo":
            self.statusBar().showMessage(f"Отменено: {desc}")
        elif event_type == "redo":
            self.statusBar().showMessage(f"Повторено: {desc}")
        else:
            self.statusBar().showMessage(f"Последнее действие: {desc}")

    def _setup_latency_label(self) -> None:
        """Добавить QLabel с latency в StatusBar как permanent widget."""
        self._latency_label = QLabel("Latency: —")
        self.statusBar().addPermanentWidget(self._latency_label)

    def _show_history_menu(self) -> None:
        """Показать dropdown с последними 20 Actions."""
        from PyQt5.QtWidgets import QMenu

        bus = self._app_ctx.get_action_bus() if self._app_ctx else None
        if bus is None:
            return

        actions = bus.history(20)
        if not actions:
            return

        menu = QMenu(self)
        # Показываем от новых к старым
        for i, action in enumerate(reversed(actions)):
            desc = action.description or action.action_type.value
            label = f"{i + 1}. {desc}"
            # Маркер текущей позиции (top of stack)
            if i == 0:
                label = f"● {label}"
            menu_action = menu.addAction(label)
            aid = action.action_id
            menu_action.triggered.connect(lambda checked, _aid=aid: self._undo_to(_aid))

        menu.exec_(self._btn_history.mapToGlobal(self._btn_history.rect().bottomLeft()))

    def _undo_to(self, action_id: str) -> None:
        """Откатить до указанного action."""
        bus = self._app_ctx.get_action_bus() if self._app_ctx else None
        if bus is not None:
            bus.undo_to(action_id)

    def closeEvent(self, event) -> None:
        """Отписаться от bus при закрытии окна."""
        bus = self._app_ctx.get_action_bus() if self._app_ctx else None
        if bus is not None:
            bus.remove_change_callback(self._update_undo_redo_state)
        super().closeEvent(event)

    @property
    def image_panel(self) -> ImagePanelWidget:
        return self._image_panel

    @property
    def tab_widget(self) -> TabWidget:
        return self._tab_widget

    def display_frames(self, frames: dict[str, Any]) -> None:
        self._image_panel.display_frames(frames)

    # --- Per-camera resolution tracking (Task 2.2) ---

    def update_camera_resolution(self, camera_id: int, width: int, height: int) -> None:
        """Обновить отображение разрешения для указанной камеры в StatusBar."""
        if not hasattr(self, "_camera_resolutions"):
            self._camera_resolutions: dict[int, tuple[int, int]] = {}
        self._camera_resolutions[camera_id] = (width, height)
        self._refresh_resolution_status()

    def _refresh_resolution_status(self) -> None:
        """Обновить StatusBar: показать разрешение каждой камеры."""
        if not hasattr(self, "_camera_resolutions") or not self._camera_resolutions:
            return
        parts = []
        for cam_id in sorted(self._camera_resolutions):
            w, h = self._camera_resolutions[cam_id]
            parts.append(f"Cam{cam_id}: {w}x{h}")
        resolution_text = " | ".join(parts)
        self.statusBar().showMessage(resolution_text)

    def update_camera_status(self, text: str) -> None:
        pass

    def update_camera_error(self, text: str) -> None:
        pass

    def update_camera_fps(self, fps: float) -> None:
        pass

    def update_camera_devices(self, devices: list) -> None:
        if self._camera_tab:
            self._camera_tab.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        if self._camera_tab:
            self._camera_tab.update_camera_parameters(params)

    def sync_camera_type(self, camera_type: str) -> None:
        if self._camera_tab:
            self._camera_tab.sync_camera_type(camera_type)

    def update_latency(self, latency_ms: float) -> None:
        """Обновить отображение e2e latency в StatusBar."""
        if self._latency_label is not None:
            self._latency_label.setText(f"Latency: {latency_ms:.0f}ms")

    def update_frame(
        self,
        original_frame: Any,
        mask_frame: Any,
        frame_id: int,
        show_original: bool = True,
        show_mask: bool = True,
    ) -> None:
        frames = {}
        if show_original and original_frame is not None:
            frames["original"] = original_frame
        if show_mask and mask_frame is not None:
            frames["mask"] = mask_frame
        self.display_frames(frames)
