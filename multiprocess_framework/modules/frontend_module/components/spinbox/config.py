# -*- coding: utf-8 -*-
"""
SpinBoxConfig — настройки спинбокса (value-часть).
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, Literal, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
)
from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import TouchKeyboardConfig


class SpinBoxConfig(BaseControlConfig):
    """Настройки спинбокса: QDoubleSpinBox."""

    min_val: Annotated[Optional[float], FieldMeta("Минимум")] = None
    max_val: Annotated[Optional[float], FieldMeta("Максимум")] = None
    label_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"
    touch_keyboard: Optional[TouchKeyboardConfig] = None
    touch_keyboard_factory: Optional[Callable[[], Any]] = None

    def to_override_dict(self) -> dict:
        """Dict для слияния с ResolvedMeta (label + min/max)."""
        d = super().to_override_dict()
        if self.min_val is not None:
            d["min"] = self.min_val
        if self.max_val is not None:
            d["max"] = self.max_val
        return d
