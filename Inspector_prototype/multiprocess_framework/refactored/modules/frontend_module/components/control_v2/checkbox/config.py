# -*- coding: utf-8 -*-
"""
CheckboxViewConfig — UI-опции чекбокса (позиция метки, общие поля из BaseControlConfig).

`to_label_override()` — типизированное слияние с метаданными регистра в `SchemaTrait`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from frontend_module.components.control_v2.base.config import (
    BaseControlConfig,
    LabelOverride,
)


@dataclass
class CheckboxViewConfig(BaseControlConfig):
    """
    Настройки отображения чекбокса (позиция метки относительно квадрата).

    Поля `label` / `tooltip` / `enabled` наследуются из `BaseControlConfig`;
    непустой `label` переопределяет подпись из метаданных регистра в `SchemaTrait`.

    Attributes:
        position: Порядок метки и `QCheckBox`: left, right, top или bottom.
    """

    position: Literal["left", "right", "top", "bottom"] = "left"

    def to_label_override(self) -> LabelOverride:
        """Собрать `LabelOverride` для слияния с `ResolvedMeta` (только заданные поля)."""
        return LabelOverride(label=self.label)
