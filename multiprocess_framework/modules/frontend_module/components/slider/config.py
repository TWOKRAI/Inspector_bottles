# -*- coding: utf-8 -*-
"""
SliderConfig — настройки слайдера (value-часть).
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
)


class SliderConfig(BaseControlConfig):
    """Настройки слайдера: QLineEdit + QSlider."""

    show_ticks: Annotated[bool, FieldMeta("Показывать деления")] = False
    tick_interval: Annotated[Optional[int], FieldMeta("Интервал делений")] = None
    min_val: Annotated[Optional[float], FieldMeta("Минимум")] = None
    max_val: Annotated[Optional[float], FieldMeta("Максимум")] = None
    label_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    def to_override_dict(self) -> dict:
        """Dict для слияния с ResolvedMeta (label + min/max)."""
        d = super().to_override_dict()
        if self.min_val is not None:
            d["min"] = self.min_val
        if self.max_val is not None:
            d["max"] = self.max_val
        return d
