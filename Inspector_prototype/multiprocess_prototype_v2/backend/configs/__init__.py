# multiprocess_prototype_v2\backend\configs\__init__.py
"""
Общие конфиги backend: base_config, managers_schema_lite, proc_assembly.

Схемы отдельных процессов (CameraConfig, ProcessorConfig, …) импортируйте из своих
модулей — здесь только базовые типы и сборка proc_dict, без тяжёлых зависимостей.

Дефолтные managers — managers_schema_lite (SchemaBase + наполнение dict).
Декларативные схемы процессов — data_schema_module.SchemaBase.
"""

from .base_config import ProcessConfigBase, class_path_from_type
from .managers_schema_lite import (
    DefaultManagersConfig,
    build_default_managers_model,
    get_default_managers_config,
    get_log_dir,
    merge_managers,
)
from .proc_assembly import build_launch_tuple, build_proc_dict

__all__ = [
    "DefaultManagersConfig",
    "build_default_managers_model",
    "get_log_dir",
    "get_default_managers_config",
    "merge_managers",
    "build_proc_dict",
    "build_launch_tuple",
    "ProcessConfigBase",
    "class_path_from_type",
]
