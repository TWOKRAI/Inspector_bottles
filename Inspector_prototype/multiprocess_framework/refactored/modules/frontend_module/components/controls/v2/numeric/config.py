# -*- coding: utf-8 -*-
"""
NumericViewConfig — настройки отображения числового поля.

Универсальный конфиг для SliderView, SpinBoxView и других числовых контролов.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from frontend_module.components.controls.v2.base.config import (
    BaseControlConfig,
    LabelOverride,
)


@dataclass
class NumericViewConfig(BaseControlConfig):
    """Настройки UI для числового поля."""

    view_type: Literal["slider", "spinbox"] = "slider"
    show_ticks: bool = False
    tick_interval: Optional[int] = None
    touch_keyboard_factory: Optional[object] = None  # Callable[[], keyboard_widget]
    min_val: Optional[float] = None  # для элементов массива (например, BGR 0–255)
    max_val: Optional[float] = None
    label_position: Literal["left", "right", "top", "bottom"] = "left"

    def to_label_override(self) -> LabelOverride:
        """Типизированное переопределение для SchemaTrait."""
        return LabelOverride(
            label=self.label,
            min_val=self.min_val,
            max_val=self.max_val,
        )
