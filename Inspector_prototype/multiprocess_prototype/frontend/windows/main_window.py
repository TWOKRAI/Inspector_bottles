# multiprocess_prototype/frontend/windows/main_window.py
"""
MainWindow — главное окно приложения.

Layout: Header + ImagePanel (2 слота) + TabWidget.
Использует компоненты из frontend_module.
"""

from typing import Any, Callable, Dict, Optional

from frontend_module.components.header import HeaderWidget
from frontend_module.components.tab_widget import TabWidget
from frontend_module.core.qt_imports import QMainWindow, QVBoxLayout, QWidget
from frontend_module.widgets.image_panel import ImagePanelWidget

from multiprocess_prototype.frontend.widgets import (
    RecipesTabWidget,
    SettingsTabWidget,
    ProcessingTabWidget,
    CameraTabWidget,
)


class MainWindow(QMainWindow):
    """
    Главное окно: Header + ImagePanel + TabWidget.

    Параметры:
        config: dict с секциями window, header, tabs, image_panel
        show_window_callback: fn(name) для переключения окон
        registers_manager: для виджетов вкладок (опционально)
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
        parent=None,
    ):
        super().__init__(parent)
        self._config = config or {}
        self._show_window = show_window_callback
        self._registers_manager = registers_manager
        self._camera_callbacks = camera_callbacks or {}
        self._processing_callbacks = processing_callbacks or {}
        self._camera_type = camera_type
        self._init_ui()

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

        # Header
        callbacks = {}
        if self._show_window:
            for w in header_cfg.get("windows", []):
                ck = w.get("callback_key")
                wid = w.get("id")
                if ck and wid:
                    callbacks[ck] = lambda n=wid: self._show_window(n)
        self._header = HeaderWidget(
            windows=header_cfg.get("windows", [
                {"id": "main", "label": "Домой", "callback_key": "on_main_show"},
                {"id": "neuroun", "label": "Нейрон", "callback_key": "on_neuroun_show"},
            ]),
            callbacks=callbacks,
            logo_path=header_cfg.get("logo_path"),
            show_admin=header_cfg.get("show_admin", True),
        )
        layout.addWidget(self._header)

        # ImagePanel
        slots = image_panel_cfg.get("slots", [
            {"id": "original", "label": "Original", "visible_default": True},
            {"id": "mask", "label": "Mask", "visible_default": True},
        ])
        self._image_panel = ImagePanelWidget(image_slots=slots)
        layout.addWidget(self._image_panel, 1)

        # TabWidget с вкладками
        self._tab_widget = TabWidget()
        self._tab_widget.add_tab(
            RecipesTabWidget(registers_manager=self._registers_manager),
            "Рецепты",
        )
        self._tab_widget.add_tab(
            SettingsTabWidget(registers_manager=self._registers_manager),
            "Настройки",
        )
        self._processing_tab = ProcessingTabWidget(
            callbacks=self._processing_callbacks,
        )
        self._tab_widget.add_tab(self._processing_tab, "Обработка")
        self._camera_tab = CameraTabWidget(
            camera_type=self._camera_type,
            callbacks=self._camera_callbacks,
        )
        self._tab_widget.add_tab(self._camera_tab, "Камера")
        layout.addWidget(self._tab_widget)

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
        pass  # CameraTabWidget не имеет статусной метки, можно добавить

    def update_camera_error(self, text: str) -> None:
        """Переслать ошибку камеры."""
        pass

    def update_camera_fps(self, fps: float) -> None:
        """Переслать FPS камеры."""
        pass

    def update_camera_devices(self, devices: list) -> None:
        """Переслать список устройств Hikvision в CameraTabWidget."""
        if hasattr(self, "_camera_tab"):
            self._camera_tab.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        """Переслать параметры камеры в CameraTabWidget."""
        if hasattr(self, "_camera_tab"):
            self._camera_tab.update_camera_parameters(params)

    def sync_camera_type(self, camera_type: str) -> None:
        """Синхронизировать тип камеры в CameraTabWidget."""
        if hasattr(self, "_camera_tab"):
            self._camera_tab.sync_camera_type(camera_type)

    def update_frame(
        self,
        original_frame: Any,
        mask_frame: Any,
        frame_id: int,
        show_original: bool = True,
        show_mask: bool = True,
    ) -> None:
        """
        Совместимость с InspectorWindow: обновить кадры из rendered_frame_ready.
        """
        frames = {}
        if show_original and original_frame is not None:
            frames["original"] = original_frame
        if show_mask and mask_frame is not None:
            frames["mask"] = mask_frame
        self.display_frames(frames)
