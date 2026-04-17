# multiprocess_prototype_v3/backend/configs/__init__.py
"""Конфигурация процессов v3."""

from .base_config import ProcessConfigBase, class_path_from_type
from .proc_assembly import build_launch_tuple, build_proc_dict

__all__ = [
    "ProcessConfigBase",
    "class_path_from_type",
    "build_launch_tuple",
    "build_proc_dict",
]
