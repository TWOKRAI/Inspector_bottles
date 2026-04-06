# framework_minimal_prototype\backend\configs\base_config.py
"""
Базовый конфиг процессов минимального прототипа.

ProcessConfigBase — поля SchemaBase; сборка proc_dict — proc_assembly.build_launch_tuple.
"""

from typing import Any, Dict, Optional, Type, Union

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessPriorityLevel


def class_path_from_type(cls: Type) -> str:
    """Полный путь к классу процесса для proc_dict['class']."""
    return f"{cls.__module__}.{cls.__qualname__}"


class ProcessConfigBase(SchemaBase):
    """Базовый конфиг: model_dump() → proc_dict['config']."""

    process_name: str = "base"
    class_path: str = ""
    priority: Union[str, ProcessPriorityLevel] = ProcessPriorityLevel.NORMAL
    queues: Optional[Dict[str, Any]] = None

    @property
    def memory(self) -> Optional[Dict[str, Any]]:
        return None

    def managers_overlay(self) -> Optional[Dict[str, Any]]:
        return None

    def build(self) -> tuple[str, dict]:
        from .proc_assembly import build_launch_tuple

        return build_launch_tuple(self)
