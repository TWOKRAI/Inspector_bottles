# -*- coding: utf-8 -*-
"""
NumericViewConfig — настройки отображения числового поля.

Универсальный конфиг для SliderView, SpinBoxView и других числовых контролов.
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, Literal, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
)
from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import TouchKeyboardConfig


class NumericViewConfig(BaseControlConfig):
    """Настройки UI для числового поля."""

    view_type: Annotated[
        Literal["slider", "spinbox"],
        FieldMeta("Тип виджета"),
    ] = "slider"
    show_ticks: Annotated[bool, FieldMeta("Показывать деления")] = False
    tick_interval: Annotated[Optional[int], FieldMeta("Интервал делений")] = None
    touch_keyboard: Optional[TouchKeyboardConfig] = None
    touch_keyboard_factory: Optional[Callable[[], Any]] = None
    """Если задано, вызывается вместо встроенной mini/full (совместимость со старым API).
    Runtime-only поле, не подлежит JSON-сериализации."""
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
