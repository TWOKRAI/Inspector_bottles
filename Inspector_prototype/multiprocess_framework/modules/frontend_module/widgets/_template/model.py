# -*- coding: utf-8 -*-
"""
Модель данных виджета — слой доступа к данным (регистры, менеджеры).

TODO: заменить TemplateModel на имя своего виджета.
TODO: добавить поля и методы для работы с данными.

Model не содержит Qt-код. Инкапсулирует обращения к RegistersManager
и другим внешним источникам данных.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TemplateModel:
    """
    Модель данных виджета.

    TODO: добавить поля (registers_manager, внешние менеджеры, кэши).

    Attributes:
        registers_manager: Менеджер регистров (IRegistersManagerGui) или None.
    """

    registers_manager: Optional[Any] = None
