# multiprocess_prototype/frontend/widgets/camera_tab/fps_section.py
"""
Секция FPS для режима Simulator / Webcam.

С `RegistersManager`: один виджет `NumericControl` на поле `fps`.
Без менеджера: QLabel + QSlider и колбэк `on_slider_changed` (демо / тесты без регистров).

Диапазон слайдера и подпись control_v2 — из ``CameraTabUiConfig``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from frontend_module.components.control_v2 import (
    BindingConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.components.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QLabel, QSlider, Qt

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

from .schemas import CameraTabUiConfig


@dataclass
class FpsFallbackWidgets:
    """Виджеты ручного FPS; при привязке к регистру оба None."""

    label: Optional[QLabel]
    slider: Optional[QSlider]


def add_fps_section_to_layout(
    layout: Any,
    *,
    binding: RegisterBindingContext,
    u: CameraTabUiConfig,
    on_slider_changed: Callable[[int], None],
) -> FpsFallbackWidgets:
    """
    Добавляет в переданный QVBoxLayout контент группы FPS.

    Returns:
        Ссылки на fallback-виджеты (для обновления подписи и чтения не нужны при bind).
    """
    # С RegistersManager — NumericControl; без — QLabel + QSlider
    if binding.can_bind and binding.rm is not None:
        result = NumericControl.create(
            binding.rm,
            BindingConfig(CAMERA_REGISTER, "fps"),
            NumericViewConfig(view_type="slider", label=u.fps_numeric_control_label),
        )
        layout.addWidget(result.widget)
        return FpsFallbackWidgets(None, None)

    label = QLabel(f"{u.initial_fps}{u.fps_suffix}")
    slider = QSlider(Qt.Horizontal)
    slider.setRange(u.fps_slider_min, u.fps_slider_max)
    slider.setValue(u.initial_fps)
    slider.valueChanged.connect(on_slider_changed)
    layout.addWidget(label)
    layout.addWidget(slider)
    return FpsFallbackWidgets(label, slider)
