# -*- coding: utf-8 -*-
"""
Конфиги составных контролов — CompoundNumericConfig, CompoundControlConfig.
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional, Tuple, Union

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.checkbox.config import CheckboxViewConfig
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig

ChildConfig = Union[NumericViewConfig, CheckboxViewConfig]
CompoundItem = Tuple[BindingConfig, ChildConfig]


class CompoundNumericConfig(SchemaBase):
    """Конфиг составного контрола: привязка + метки для 3 индексов."""

    binding: BindingConfig
    labels: List[str]
    view_config: Optional[NumericViewConfig] = None


class CompoundControlConfig(SchemaBase):
    """
    Конфиг составного контрола.

    Array mode: binding + array_children — создаёт контролы для индексов 0,1,2,...
    Mixed mode: items — каждый элемент (binding, config) создаётся отдельно.
    """

    orientation: Annotated[
        Literal["horizontal", "vertical"],
        FieldMeta("Ориентация layout"),
    ] = "horizontal"
    spacing: Annotated[int, FieldMeta("Отступ между элементами", min=0)] = 10

    # Array mode
    binding: Optional[BindingConfig] = None
    array_children: Optional[List[NumericViewConfig]] = None

    # Mixed mode
    items: Optional[List[CompoundItem]] = None
