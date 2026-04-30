# -*- coding: utf-8 -*-
"""
GroupConfig — конфиг группы компонентов.

Объединяет схемы дочерних компонентов + поля настройки группы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Union

from multiprocess_framework.modules.frontend_module.components.label.config import LabelConfig
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.slider.config import SliderConfig
from multiprocess_framework.modules.frontend_module.components.spinbox.config import SpinBoxConfig

# Типы дочерних конфигов (примитивы + view-конфиги)
ChildConfig = Union[LabelConfig, SliderConfig, SpinBoxConfig, NumericViewConfig]
# Элемент группы: либо один конфиг, либо пара (тип, конфиг) для явного указания
GroupChild = Union[ChildConfig, tuple[str, Any]]


@dataclass
class GroupConfig:
    """
    Конфиг группы компонентов.

    children — список конфигов дочерних компонентов (Label, Slider, SpinBox и т.д.).
    Поля группы — для настройки layout и поведения.
    """

    children: List[ChildConfig] = field(default_factory=list)
    orientation: Literal["horizontal", "vertical"] = "horizontal"
    spacing: int = 5

    # Дополнительные поля для групп с подписью
    label_position: Literal["left", "right", "top", "bottom"] = "left"


@dataclass
class LabeledNumericGroupConfig(GroupConfig):
    """
    Готовый конфиг группы «Подпись + числовой контрол».

    Объединяет LabelConfig + NumericViewConfig + параметры группы.
    """

    label_config: Optional[LabelConfig] = None
    value_config: Optional[Union[SliderConfig, SpinBoxConfig, NumericViewConfig]] = None

    def __post_init__(self) -> None:
        label = self.label_config or LabelConfig(position=self.label_position)
        value = self.value_config or SliderConfig()
        if not self.children:
            self.children = [label, value]
