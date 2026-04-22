# multiprocess_prototype_v2\backend\configs\base_config.py
"""
Базовый конфиг процессов v2.

ProcessConfigBase — только поля SchemaBase и опционально memory / managers_overlay.
Сборка proc_dict — в proc_assembly.build_proc_dict / build_launch_tuple.

Контракт proc_dict: process_manager_module/docs/CONFIG_CONTRACT.md
"""

from typing import Any, Dict, Optional, Type, Union

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessPriorityLevel


def class_path_from_type(cls: Type) -> str:
    """
    Получить class_path из типа (type safety, IDE отследит рефакторинг).

    Пример:
        class_path: str = class_path_from_type(UnifiedCameraProcess)
    """
    return f"{cls.__module__}.{cls.__qualname__}"


class ProcessConfigBase(SchemaBase):
    """
    Базовый конфиг процесса: поля для model_dump() → proc_dict['config'].

    Подклассы задают process_name, class_path, priority; при необходимости
    переопределяют memory и managers_overlay.
    """

    process_name: str = "base"
    class_path: str = ""  # подкласс переопределяет; или class_path_from_type(ProcessClass)
    priority: Union[str, ProcessPriorityLevel] = ProcessPriorityLevel.NORMAL
    queues: Optional[Dict[str, Any]] = None

    @property
    def memory(self) -> Optional[Dict[str, Any]]:
        """Memory для SharedMemory. Переопределить в CameraConfig, ProcessorConfig, RendererConfig."""
        return None

    def managers_overlay(self) -> Optional[Dict[str, Any]]:
        """
        Фрагмент managers для merge с get_default_managers_config().

        По умолчанию None — полный общий конфиг логов/ошибок.
        """
        return None

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(config))."""
        from .proc_assembly import build_launch_tuple

        return build_launch_tuple(self)
