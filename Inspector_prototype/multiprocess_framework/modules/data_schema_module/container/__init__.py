# -*- coding: utf-8 -*-
"""
Контейнеры и конвертеры конфигов.

Содержит:
    RegistersContainer   — контейнер для набора *Registers-моделей
    config_to_dict       — Dict at Boundary конвертер
    process              — короткий алиас для build_process_with_workers
"""
from .registers_container import RegistersContainer
from .config_converters import (
    config_to_dict,
    configs_to_dicts,
    build_process_with_workers,
    process,
)

__all__ = [
    "RegistersContainer",
    "config_to_dict",
    "configs_to_dicts",
    "build_process_with_workers",
    "process",
]
