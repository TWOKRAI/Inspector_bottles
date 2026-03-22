# -*- coding: utf-8 -*-
"""
Конфиги составных контролов — CompoundNumericConfig, CompoundControlConfig.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple, Union

from frontend_module.components.controls.v2.base.config import BindingConfig
from frontend_module.components.controls.v2.checkbox.config import CheckboxViewConfig
from frontend_module.components.controls.v2.numeric.config import NumericViewConfig

ChildConfig = Union[NumericViewConfig, CheckboxViewConfig]
CompoundItem = Tuple[BindingConfig, ChildConfig]


@dataclass
class CompoundNumericConfig:
    """Конфиг составного контрола: привязка + метки для 3 индексов."""

    binding: BindingConfig
    labels: List[str]
    view_config: Optional[NumericViewConfig] = None


@dataclass
class CompoundControlConfig:
    """
    Конфиг составного контрола.

    Array mode: binding + array_children — создаёт контролы для индексов 0,1,2,...
    Mixed mode: items — каждый элемент (binding, config) создаётся отдельно.
    """

    orientation: Literal["horizontal", "vertical"] = "horizontal"
    spacing: int = 10

    # Array mode: binding + список конфигов (индексы 0,1,2,...)
    binding: Optional[BindingConfig] = None
    array_children: Optional[List[NumericViewConfig]] = None

    # Mixed mode: список (binding, config) для разных полей
    items: Optional[List[CompoundItem]] = None
