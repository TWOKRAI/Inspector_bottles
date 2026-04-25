# -*- coding: utf-8 -*-
"""
NumericViewConfig — настройки отображения числового поля.

Универсальный конфиг для SliderView, SpinBoxView и других числовых контролов.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
    LabelOverride,
)
from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import TouchKeyboardConfig


@dataclass
class NumericViewConfig(BaseControlConfig):
    """Настройки UI для числового поля."""

    view_type: Literal["slider", "spinbox"] = "slider"
    show_ticks: bool = False
    tick_interval: Optional[int] = None
    touch_keyboard: Optional[TouchKeyboardConfig] = None
    touch_keyboard_factory: Optional[Callable[[], Any]] = None
    """Если задано, вызывается вместо встроенной mini/full (совместимость со старым API)."""
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
