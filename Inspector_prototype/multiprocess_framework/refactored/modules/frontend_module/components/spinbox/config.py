# -*- coding: utf-8 -*-
"""
SpinBoxConfig — настройки спинбокса (value-часть).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from frontend_module.components.base.config import (
    BaseControlConfig,
    LabelOverride,
)


@dataclass
class SpinBoxConfig(BaseControlConfig):
    """Настройки спинбокса: QDoubleSpinBox."""

    min_val: Optional[float] = None
    max_val: Optional[float] = None
    label_position: Literal["left", "right", "top", "bottom"] = "left"

    def to_label_override(self) -> LabelOverride:
        return LabelOverride(
            label=self.label,
            min_val=self.min_val,
            max_val=self.max_val,
        )
