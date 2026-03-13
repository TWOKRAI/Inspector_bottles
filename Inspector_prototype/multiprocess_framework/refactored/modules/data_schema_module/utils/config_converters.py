# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

config_converters перемещены в container/config_converters.py.

Используйте новый путь:
    from data_schema_module.container import config_to_dict, process, ...
    from data_schema_module import config_to_dict, process, ...
"""
from ..container.config_converters import (
    config_to_dict,
    configs_to_dicts,
    build_process_with_workers,
    process,
)

__all__ = [
    "config_to_dict",
    "configs_to_dicts",
    "build_process_with_workers",
    "process",
]
