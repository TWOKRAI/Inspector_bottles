# -*- coding: utf-8 -*-
"""
Shared Registers — общие схемы регистров для backend и frontend.

Единый источник истины: backend-процессы и frontend_module импортируют
регистры отсюда. Метаданные (FieldMeta, routing) используются роутером
для маршрутизации сообщений.
"""

from .draw import DrawRegisters
from .processor import ProcessorRegisters
from .renderer import RendererRegisters

__all__ = [
    "DrawRegisters",
    "ProcessorRegisters",
    "RendererRegisters",
]
