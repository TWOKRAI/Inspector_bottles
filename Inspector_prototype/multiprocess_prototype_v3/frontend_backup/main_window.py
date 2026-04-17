"""MainWindow — primary application window with Header + ImagePanel + TabWidget."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from frontend_module.core.qt_imports import QMainWindow, QVBoxLayout, QWidget
from frontend_module.widgets import HeaderWidget, TabWidget
from frontend_module.widgets.image_panel import ImagePanelWidget

TabWidgetFactory = Callable[[str, dict], Any]

DEFAULT_IMAGE_SLOTS = [
    {"id": "original", "label": "Original", "stretch": 2},
    {"id": "mask", "label": "Mask", "stretch": 1},
]


class MainWindow(QMainWindow):
    """Main window: Header + ImagePanel + TabWidget.

    Args:
        config: dict with sections window, header, image_panel, tabs
        tab_widget_factory: (widget_key, tab_config) -> QWidget | None
    """

    def __init__(
        self,
        *,
        config: Optional[Dict[str, Any]] = None,
        registers_manager: Optional[Any] = None,
        camera_callbacks_map: Optional[Dict[str, Any]] = None,
        camera_type: str = "simulator",
        tab_widget_factory: Optional[TabWidgetFactory] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config or {}
        self._registers_manager = registers_manager
        self._camera_callbacks_map = camera_callbacks_map or {}
        self._camera_type = camera_type
        self._tab_widget_factory = tab_widget_factory
        self._camera_tab = None
        self._init_ui()

    def _init_ui(self) -> None:
        window_cfg = self._config.get("window", {})
        header_cfg = self._config.get("header", {})
        image_panel_cfg = self._config.get("image_panel", {})
        tabs_cfg = self._config.get("tabs", [])

        self.setWindowTitle(window_cfg.get("title", "Inspector Prototype v3"))
        min_w = window_cfg.get("min_width", 1280)
        min_h = window_cfg.get("min_height", 720)
        self.setMinimumSize(min_w, min_h)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        self._header = HeaderWidget(config=header_cfg if isinstance(header_cfg, dict) else {})
        layout.addWidget(self._header)

        # Image panel
        slots = image_panel_cfg.get("slots", DEFAULT_IMAGE_SLOTS)
        self._image_panel = ImagePanelWidget(image_slots=slots)
        layout.addWidget(self._image_panel, 1)

        # Tab widget
        self._tab_widget = TabWidget()
        if self._tab_widget_factory and tabs_cfg:
            for tab in tabs_cfg:
                widget_key = tab.get("widget", tab.get("id", ""))
                title = tab.get("title", widget_key)
                w = self._tab_widget_factory(widget_key, tab)
                if w is not None:
                    self._tab_widget.add_tab(w, title)
        layout.addWidget(self._tab_widget)

        # Find camera tab for delegation
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
