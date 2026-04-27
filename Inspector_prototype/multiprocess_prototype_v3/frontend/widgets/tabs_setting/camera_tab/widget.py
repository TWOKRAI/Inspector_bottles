# multiprocess_prototype_v3/frontend/widgets/camera_tab/widget.py
"""
CameraTabWidget — контейнер: ComboBox типа камеры + StackedWidget с тремя виджетами.

Task 3.10: расширен на N камер из CameraRegistry — camera selector вверху,
per-camera status/FPS/drops, start/stop кнопки (placeholder).

Дочерние виджеты: SimWebcamWidget (simulator / webcam) и HikvisionCameraMvpWidget.
Нужны ``command_handler`` (для Hikvision MVP) и ``callbacks_map`` для Sim/Webcam и on_camera_type_changed.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)
from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config
from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseTab

from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ...sources.camera_common import SimWebcamWidget
from ...sources.hikvision_camera_mvp import HikvisionCameraMvpWidget
from .presenter import CameraTabPresenter
from .schemas import CameraTabUiConfig


class CameraTabWidget(BaseTab):
    """Вкладка камеры: переключатель Simulator/Webcam/Hikvision и три виджета.

    При наличии camera_registry — multi-camera UI с selector, status, FPS, drops.
    При camera_registry=None — fallback на текущее поведение (1 камера).
    """

    def __init__(
        self,
        *,
        camera_type: str = "simulator",
        registers_manager: Any | None = None,
        callbacks_map: dict[str, Any] | None = None,
        command_handler: Any | None = None,
        ui: CameraTabUiConfig | dict | None = None,
        touch_keyboard: Any | None = None,
        camera_registry: Any | None = None,
        parent: Any | None = None,
    ):
        """ComboBox типа камеры + стек из SimWebcam×2 и Hikvision MVP.

        Args:
            camera_registry: CameraRegistry (Task 3.9) или None для fallback.
        """
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._callbacks_map = callbacks_map or {}
        self._command_handler = command_handler
        self._ui = coerce_schema_config(ui, CameraTabUiConfig)
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(self._ui, "touch_keyboard", None)
        )
        self._camera_type_map = self._ui.camera_type_index_map()
        self._camera_registry = camera_registry

        self._presenter = CameraTabPresenter(
            view=self,
            rm=registers_manager,
            ui=self._ui,
            callbacks_map=self._callbacks_map,
            camera_registry=camera_registry,
        )

        self._init_ui()

        idx = self._camera_type_map.get(camera_type, 0)
        self._presenter.apply_initial_camera_type(camera_type, stack_index=idx)

        # Инициализировать multi-camera UI после создания всех Qt-виджетов
        self._presenter.init_multi_camera_ui()

    def _init_ui(self) -> None:
        """Верх: camera selector (multi-cam) → тип камеры; низ: QStackedWidget с тремя страницами."""
        u = self._ui
        root = QVBoxLayout(self)

        # --- Блок: выбор камеры из реестра (Task 3.10) ---
        # Показываем только если camera_registry передан
        if self._camera_registry is not None:
            self._init_multi_camera_section(root)
        else:
            # Fallback: заглушки для multi-camera виджетов
            self._combo_camera_selector = None
            self._label_status = None
            self._label_fps = None
            self._label_drops = None
            self._btn_start = None
            self._btn_stop = None

        # --- Блок: тип камеры (ComboBox) ---
        type_group = QGroupBox(u.group_camera_type)
        type_layout = QVBoxLayout(type_group)
        self._combo_camera_type = QComboBox()
        self._combo_camera_type.addItems(list(u.camera_type_options))
        self._combo_camera_type.setMinimumWidth(u.camera_type_combo_min_width)
        self._combo_camera_type.currentIndexChanged.connect(self._presenter.on_camera_type_changed)
        type_layout.addWidget(self._combo_camera_type)
        root.addWidget(type_group)

        # --- Блок: три виджета (simulator, webcam, hikvision) в стеке ---
        self._stack = QStackedWidget()
        tk_fps = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_fps", None)
        )
        tk_hik = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_hikvision", None)
        )
        sim = SimWebcamWidget(
            camera_type_id="simulator",
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("simulator"),
            touch_keyboard=tk_fps,
        )
        web = SimWebcamWidget(
            camera_type_id="webcam",
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("webcam"),
            touch_keyboard=tk_fps,
        )
        if self._command_handler is None:
            raise TypeError("CameraTabWidget requires command_handler for HikvisionCameraMvpWidget")
        hik = HikvisionCameraMvpWidget(
            registers_manager=self._registers_manager,
            command_handler=self._command_handler,
            ui=self._ui.hikvision,
            touch_keyboard=tk_hik,
            webcam_enum_max_index=self._ui.webcam_enum_max_index,
        )
        self._stack.addWidget(sim)
        self._stack.addWidget(web)
        self._stack.addWidget(hik)
        self._hik_widget = hik

        root.addWidget(self._stack)

    def _init_multi_camera_section(self, root: QVBoxLayout) -> None:
        """Создать секцию multi-camera: selector, status, FPS, drops, start/stop."""
        cam_group = QGroupBox("Камеры")
        cam_layout = QVBoxLayout(cam_group)

        # Строка 1: selector камеры
        selector_layout = QHBoxLayout()
        selector_label = QLabel("Камера:")
        self._combo_camera_selector = QComboBox()
        self._combo_camera_selector.setMinimumWidth(200)
        self._combo_camera_selector.currentIndexChanged.connect(
            self._presenter.on_camera_selector_changed
        )
        selector_layout.addWidget(selector_label)
        selector_layout.addWidget(self._combo_camera_selector)
        selector_layout.addStretch()
        cam_layout.addLayout(selector_layout)

        # Строка 2: статус + FPS + drops
        info_layout = QHBoxLayout()

        self._label_status = QLabel("Stopped")
        self._label_status.setStyleSheet("color: gray; font-weight: bold;")
        self._label_status.setMinimumWidth(80)
        info_layout.addWidget(self._label_status)

        self._label_fps = QLabel("FPS: 0.0")
        self._label_fps.setMinimumWidth(80)
        info_layout.addWidget(self._label_fps)

        self._label_drops = QLabel("Drops: 0")
        self._label_drops.setMinimumWidth(80)
        info_layout.addWidget(self._label_drops)

        info_layout.addStretch()
        cam_layout.addLayout(info_layout)

        # Строка 3: кнопки Start / Stop (placeholder — IPC в Task 3.13)
        btn_layout = QHBoxLayout()
        self._btn_start = QPushButton("Start")
        self._btn_stop = QPushButton("Stop")
        self._btn_start.clicked.connect(self._presenter.on_start_camera)
        self._btn_stop.clicked.connect(self._presenter.on_stop_camera)
        btn_layout.addWidget(self._btn_start)
        btn_layout.addWidget(self._btn_stop)
        btn_layout.addStretch()
        cam_layout.addLayout(btn_layout)

        root.addWidget(cam_group)

    # ------------------------------------------------------------------
    # Реализация CameraTabView (вызывается из presenter)
    # ------------------------------------------------------------------

    def set_stack_index(self, index: int) -> None:
        """Показать страницу стека по индексу."""
        self._stack.setCurrentIndex(index)

    def set_combo_index(self, index: int, *, block_signals: bool = False) -> None:
        """Синхронизировать ComboBox с регистром/стеком (опционально без currentIndexChanged)."""
        if block_signals:
            self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(index)
        if block_signals:
            self._combo_camera_type.blockSignals(False)

    def set_camera_status_text(self, text: str, color: str) -> None:
        """Обновить текст и цвет статуса выбранной камеры."""
        if self._label_status is not None:
            self._label_status.setText(text)
            self._label_status.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_camera_fps_text(self, text: str) -> None:
        """Обновить текст FPS выбранной камеры."""
        if self._label_fps is not None:
            self._label_fps.setText(text)

    def set_camera_drops_text(self, text: str) -> None:
        """Обновить текст счётчика дропов выбранной камеры."""
        if self._label_drops is not None:
            self._label_drops.setText(text)

    def populate_camera_selector(self, items: list[str], *, block_signals: bool = False) -> None:
        """Заполнить camera selector списком камер из реестра."""
        if self._combo_camera_selector is None:
            return
        if block_signals:
            self._combo_camera_selector.blockSignals(True)
        self._combo_camera_selector.clear()
        self._combo_camera_selector.addItems(items)
        if block_signals:
            self._combo_camera_selector.blockSignals(False)

    def set_camera_selector_index(self, index: int, *, block_signals: bool = False) -> None:
        """Установить выбранную камеру в camera selector."""
        if self._combo_camera_selector is None:
            return
        if block_signals:
            self._combo_camera_selector.blockSignals(True)
        self._combo_camera_selector.setCurrentIndex(index)
        if block_signals:
            self._combo_camera_selector.blockSignals(False)

    # ------------------------------------------------------------------
    # Существующий публичный API (без изменений)
    # ------------------------------------------------------------------

    def sync_camera_type(self, camera_type: str) -> None:
        """Выставить combo и стек по строковому id типа камеры."""
        idx = self._camera_type_map.get(camera_type, 0)
        self.set_combo_index(idx, block_signals=True)
        self.set_stack_index(idx)

    def update_camera_devices(self, devices: list) -> None:
        """Проброс списка устройств в HikvisionWidget (IPC / enum)."""
        self._hik_widget.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        """Проброс параметров камеры в HikvisionWidget."""
        self._hik_widget.update_camera_parameters(params)

    @property
    def registers_manager(self):
        """Rm вкладки (для внешнего кода)."""
        return self._registers_manager
