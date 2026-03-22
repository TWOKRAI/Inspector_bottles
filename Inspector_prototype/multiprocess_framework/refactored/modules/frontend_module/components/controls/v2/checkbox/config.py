# -*- coding: utf-8 -*-
"""
CheckboxViewConfig — настройки отображения чекбокса.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from frontend_module.components.controls.v2.base.config import (
    BaseControlConfig,
    LabelOverride,
)


@dataclass
class CheckboxViewConfig(BaseControlConfig):
    """Настройки UI для чекбокса."""

    position: Literal["left", "right", "top", "bottom"] = "left"

    def to_label_override(self) -> LabelOverride:
        """Типизированное переопределение для SchemaTrait."""
        return LabelOverride(label=self.label)
