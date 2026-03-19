# multiprocess_prototype/frontend/windows/main_window.py
"""
MainWindow — главное окно приложения.

Layout: Header + ImagePanel + TabWidget.
Config-driven: window, header, image_panel, tabs из конфига.
HeaderConfig из framework — валидация и нормализация через model_dump().
"""

from typing import Any, Callable, Dict, Optional, Union

from frontend_module.components import HeaderWidget, TabWidget
from frontend_module.components.header import HeaderConfig
from frontend_module.core.qt_imports import QMainWindow, QVBoxLayout, QWidget
from frontend_module.widgets.image_panel import ImagePanelWidget


TabWidgetFactory = Callable[[str, dict], Any]


class MainWindow(QMainWindow):
    """
    Главное окно: Header + ImagePanel + TabWidget.

    Параметры:
        config: dict с секциями window, header, image_panel, tabs, settings_tab
        show_window_callback: fn(name) для переключения окон
        registers_manager: для виджетов вкладок (опционально)
        tab_widget_factory: (widget_key, tab_config) -> QWidget — создание вкладок из конфига
    """

    def __init__(
        self,
        *,
        config: Optional[Dict[str, Any]] = None,
        show_window_callback: Optional[Callable[[str], None]] = None,
        registers_manager: Optional[Any] = None,
        camera_callbacks: Optional[Dict[str, Callable]] = None,
        processing_callbacks: Optional[Dict[str, Callable]] = None,
        camera_type: str = "simulator",
        tab_widget_factory: Optional[TabWidgetFactory] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config or {}
        self._show_window = show_window_callback
        self._registers_manager = registers_manager
        self._camera_callbacks = camera_callbacks or {}
        self._processing_callbacks = processing_callbacks or {}
        self._camera_type = camera_type
        self._tab_widget_factory = tab_widget_factory or self._default_tab_factory
        self._init_ui()

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

    def _default_tab_factory(self, widget_key: str, tab_config: dict) -> Any:
        """Фабрика по умолчанию — fallback если не передана."""
        from multiprocess_prototype.frontend.widgets import (
            CameraTabWidget,
            ProcessingTabWidget,
            RecipesTabWidget,
            SettingsTabWidget,
        )

        if widget_key == "recipes":
            return RecipesTabWidget(registers_manager=self._registers_manager)
        if widget_key == "settings":
            controls = self._config.get("settings_tab", {}).get("controls", [])
            return SettingsTabWidget(
                registers_manager=self._registers_manager,
                controls_config=controls,
            )
        if widget_key == "processing":
            return ProcessingTabWidget(callbacks=self._processing_callbacks)
        if widget_key == "camera":
            return CameraTabWidget(
                camera_type=self._camera_type,
                callbacks=self._camera_callbacks,
            )
        return None

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

        # Header — HeaderConfig из framework, dict для HeaderWidget
        header_dict = self._build_header_config(header_cfg)
        self._header = HeaderWidget(config=header_dict)
        if self._show_window:
            self._header.buttons_widget.button_clicked.connect(self._show_window)
        layout.addWidget(self._header)

        # ImagePanel
        slots = image_panel_cfg.get("slots", [
            {"id": "original", "label": "Original", "visible_default": True},
            {"id": "mask", "label": "Mask", "visible_default": True},
        ])
        self._image_panel = ImagePanelWidget(image_slots=slots)
        layout.addWidget(self._image_panel, 1)

        # TabWidget — config-driven
        self._tab_widget = TabWidget()
        for tab in tabs_cfg:
            widget_key = tab.get("widget", tab.get("id", "recipes"))
            title = tab.get("title", widget_key)
            w = self._tab_widget_factory(widget_key, tab)
            if w is not None:
                self._tab_widget.add_tab(w, title)
        layout.addWidget(self._tab_widget)

        # Сохранить ссылки на вкладки для update_*
        self._camera_tab = None
        qt_tabs = self._tab_widget.tab_widget  # QTabWidget внутри TabWidget
        for i in range(qt_tabs.count()):
            w = qt_tabs.widget(i)
            # add_tab оборачивает в QScrollArea — берём внутренний виджет
            if hasattr(w, "widget") and callable(w.widget):
                w = w.widget()
            if w and hasattr(w, "update_camera_devices"):
                self._camera_tab = w
                break

    @property
    def image_panel(self) -> ImagePanelWidget:
        """ImagePanelWidget для отображения кадров."""
        return self._image_panel

    @property
    def tab_widget(self) -> TabWidget:
        """TabWidget для вкладок."""
        return self._tab_widget

    def display_frames(self, frames: Dict[str, Any]) -> None:
        """Обновить кадры в ImagePanel. frames: {slot_id: numpy_array}."""
        self._image_panel.display_frames(frames)

    def update_camera_status(self, text: str) -> None:
        """Переслать статус камеры (для совместимости с InspectorWindow)."""
        pass

    def update_camera_error(self, text: str) -> None:
        """Переслать ошибку камеры."""
        pass

    def update_camera_fps(self, fps: float) -> None:
        """Переслать FPS камеры."""
        pass

    def update_camera_devices(self, devices: list) -> None:
        """Переслать список устройств Hikvision в CameraTabWidget."""
        if self._camera_tab:
            self._camera_tab.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        """Переслать параметры камеры в CameraTabWidget."""
        if self._camera_tab:
            self._camera_tab.update_camera_parameters(params)

    def sync_camera_type(self, camera_type: str) -> None:
        """Синхронизировать тип камеры в CameraTabWidget."""
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
        """Совместимость с InspectorWindow: обновить кадры из rendered_frame_ready."""
        frames = {}
        if show_original and original_frame is not None:
            frames["original"] = original_frame
        if show_mask and mask_frame is not None:
            frames["mask"] = mask_frame
        self.display_frames(frames)
