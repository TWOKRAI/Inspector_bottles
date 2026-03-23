# -*- coding: utf-8 -*-
"""
SliderConfig — настройки слайдера (value-часть).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from frontend_module.components.control_v2.base.config import (
    BaseControlConfig,
    LabelOverride,
)


@dataclass
class SliderConfig(BaseControlConfig):
    """Настройки слайдера: QLineEdit + QSlider."""

    show_ticks: bool = False
    tick_interval: Optional[int] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    label_position: Literal["left", "right", "top", "bottom"] = "left"

    def to_label_override(self) -> LabelOverride:
        return LabelOverride(
            label=self.label,
            min_val=self.min_val,
            max_val=self.max_val,
        )
