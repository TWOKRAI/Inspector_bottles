# -*- coding: utf-8 -*-
"""
GroupConfig — конфиг группы компонентов.

Объединяет схемы дочерних компонентов + поля настройки группы.
"""

from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import model_validator

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.frontend_module.components.label.config import LabelConfig
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.slider.config import SliderConfig
from multiprocess_framework.modules.frontend_module.components.spinbox.config import SpinBoxConfig

# Типы дочерних конфигов (примитивы + view-конфиги)
ChildConfig = Union[LabelConfig, SliderConfig, SpinBoxConfig, NumericViewConfig]
# Элемент группы: либо один конфиг, либо пара (тип, конфиг) для явного указания
GroupChild = Union[ChildConfig, tuple[str, Any]]


class GroupConfig(SchemaBase):
    """
    Конфиг группы компонентов.

    children — список конфигов дочерних компонентов (Label, Slider, SpinBox и т.д.).
    """

    children: List[ChildConfig] = []
    orientation: Annotated[
        Literal["horizontal", "vertical"],
        FieldMeta("Ориентация layout"),
    ] = "horizontal"
    spacing: Annotated[int, FieldMeta("Отступ между элементами", min=0)] = 5
    label_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"


class LabeledNumericGroupConfig(GroupConfig):
    """
    Готовый конфиг группы «Подпись + числовой контрол».

    Объединяет LabelConfig + NumericViewConfig + параметры группы.
    """

    label_config: Optional[LabelConfig] = None
    value_config: Optional[Union[SliderConfig, SpinBoxConfig, NumericViewConfig]] = None

    @model_validator(mode="after")
    def _fill_children(self) -> "LabeledNumericGroupConfig":
        """Заполнить children из label_config + value_config если пусто."""
        if not self.children:
            label = self.label_config or LabelConfig(position=self.label_position)
            value = self.value_config or SliderConfig()
            self.children = [label, value]
        return self
