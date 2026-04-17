# multiprocess_prototype_v3/backend/configs/base_config.py
"""
Базовый конфиг процессов v3.

ProcessConfigBase — поля для model_dump() → proc_dict['config'];
сборка proc_dict — proc_assembly.build_proc_dict / build_launch_tuple.
"""

from typing import Any, Dict, Optional, Type, Union

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessPriorityLevel


def class_path_from_type(cls: Type) -> str:
    """Получить class_path из типа (type safety при рефакторинге)."""
    return f"{cls.__module__}.{cls.__qualname__}"


class ProcessConfigBase(SchemaBase):
    """
    Базовый конфиг процесса: process_name, class_path, priority, queues;
    managers_preset — пресет секции managers; managers_overlay — deep-merge поверх пресета.
    """

    process_name: str = "base"
    class_path: str = ""
    priority: Union[str, ProcessPriorityLevel] = ProcessPriorityLevel.NORMAL
    queues: Optional[Dict[str, Any]] = None
    managers_preset: str = "standard"

    @property
    def memory(self) -> Optional[Dict[str, Any]]:
        """SharedMemory layout для proc_dict['memory']."""
        return None

    def managers_overlay(self) -> Optional[Dict[str, Any]]:
        """Фрагмент managers для merge с пресетом."""
        return None

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(config))."""
        from .proc_assembly import build_launch_tuple

        return build_launch_tuple(self)
