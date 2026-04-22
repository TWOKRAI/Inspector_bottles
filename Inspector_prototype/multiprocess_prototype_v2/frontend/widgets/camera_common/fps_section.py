# multiprocess_prototype/frontend/widgets/camera_common/fps_section.py
"""
Секция FPS для Simulator/Webcam: NumericControl или fallback QLabel+QSlider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from frontend_module.components import (
    BindingConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.widgets.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QLabel, QSlider, Qt

from multiprocess_prototype_v2.registers.names import CAMERA_REGISTER

from .schemas import SimWebcamUiConfig


@dataclass
class FpsFallbackWidgets:
    """Виджеты fallback FPS; при привязке к регистру оба None."""

    label: Optional[QLabel]
    slider: Optional[QSlider]


def add_fps_section_to_layout(
    layout: Any,
    *,
    binding: RegisterBindingContext,
    u: SimWebcamUiConfig,
    on_slider_changed: Callable[[int], None],
    touch_keyboard: Any | None = None,
) -> FpsFallbackWidgets:
    """Добавляет секцию FPS в layout (NumericControl или QLabel+QSlider)."""
    from frontend_module.components.base.touch_keyboard_config import coerce_touch_keyboard

    tk_cfg = coerce_touch_keyboard(touch_keyboard)
    # Ветка с живым rm: один NumericControl на поле fps регистра камеры
    if binding.can_bind and binding.rm is not None:
        result = NumericControl.create(
            binding.rm,
            BindingConfig(CAMERA_REGISTER, "fps"),
            NumericViewConfig(
                view_type="slider",
                label=u.fps_numeric_control_label,
                touch_keyboard=tk_cfg,
            ),
        )
        layout.addWidget(result.widget)
        return FpsFallbackWidgets(None, None)

    # Без rm: подпись + горизонтальный QSlider, сигнал → on_slider_changed
    label = QLabel(f"{u.initial_fps}{u.fps_suffix}")
    slider = QSlider(Qt.Horizontal)
    slider.setRange(u.fps_slider_min, u.fps_slider_max)
    slider.setValue(u.initial_fps)
    slider.valueChanged.connect(on_slider_changed)
    layout.addWidget(label)
    layout.addWidget(slider)
    return FpsFallbackWidgets(label, slider)
