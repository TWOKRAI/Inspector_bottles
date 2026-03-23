# multiprocess_prototype/frontend/windows/main_window/window.py
"""
MainWindow — главное окно приложения.

Layout: Header + ImagePanel + TabWidget.
Конфиг: window, header, image_panel, tabs. Сигналы шапки: action_triggered + connect_action_handlers.
"""

from typing import Any, Callable, Dict, Optional, Union

from frontend_module.components import HeaderWidget, TabWidget
from frontend_module.components.header import HeaderConfig
from frontend_module.core.action_binding import connect_action_handlers
from frontend_module.core.qt_imports import QMainWindow, QVBoxLayout, QWidget
from frontend_module.widgets.image_panel import ImagePanelWidget

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
    """

    def __init__(
        self,
        *,
        config: Optional[Dict[str, Any]] = None,
        show_window_callback: Optional[Callable[[str], None]] = None,
        registers_manager: Optional[Any] = None,
        camera_callbacks_map: Optional[Dict[str, Any]] = None,
        camera_type: str = "simulator",
        tab_widget_factory: Optional[TabWidgetFactory] = None,
        header_action_handlers: Optional[Dict[str, Callable[[], None]]] = None,
        header_on_unmatched: Optional[Callable[[str], None]] = None,
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
        self._init_ui()

    def _resolve_tab_factory(self) -> TabWidgetFactory:
        if self._tab_widget_factory is not None:
            return self._tab_widget_factory
        return create_tab_widget_factory(
            config=self._config,
            registers_manager=self._registers_manager,
            camera_callbacks_map=self._camera_callbacks_map,
            camera_type=self._camera_type,
        )

    def _build_header_config(self, header_cfg: Union[HeaderConfig, Dict[str, Any], None]) -> Dict[str, Any]:
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

    @property
    def image_panel(self) -> ImagePanelWidget:
        return self._image_panel

    @property
    def tab_widget(self) -> TabWidget:
        return self._tab_widget

    def display_frames(self, frames: Dict[str, Any]) -> None:
        self._image_panel.display_frames(frames)

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
