# multiprocess_prototype\configs\base_config.py
"""
Базовый конфиг процессов Inspector Prototype.

ProcessConfigBase — декларативные поля class_path, priority, queues, memory.
build() реализован в базе; подклассы задают поля и опционально переопределяют memory.

Контракт proc_dict: process_manager_module/docs/CONFIG_CONTRACT.md
"""

from typing import Dict, Any, Optional, Type, Union

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel


def class_path_from_type(cls: Type) -> str:
    """
    Получить class_path из типа (type safety, IDE отследит рефакторинг).

    Пример:
        class_path: str = class_path_from_type(UnifiedCameraProcess)
    """
    return f"{cls.__module__}.{cls.__qualname__}"


class ProcessConfigBase(SchemaBase):
    """
    Базовый конфиг процесса с общей структурой proc_dict.

    Подклассы задают `class_path`, `priority`, при необходимости переопределяют `memory`.
    """

    process_name: str = "base"
    class_path: str = ""  # подкласс переопределяет; или class_path_from_type(ProcessClass)
    priority: Union[str, ProcessPriorityLevel] = ProcessPriorityLevel.NORMAL
    queues: Optional[Dict[str, Any]] = None

    @property
    def memory(self) -> Optional[Dict[str, Any]]:
        """Memory для SharedMemory. Переопределить в CameraConfig, ProcessorConfig, RendererConfig."""
        return None

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(config))."""
        priority_val = self.priority.value if hasattr(self.priority, "value") else self.priority
        return (
            self.process_name,
            self._build_proc_dict(
                self.class_path,
                queues=self.queues,
                priority=priority_val,
                memory=self.memory,
            ),
        )

    def _build_proc_dict(
        self,
        class_path: str,
        *,
        queues: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        memory: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Собрать общую структуру proc_dict для add_process().

        Args:
            class_path: Полный путь к классу процесса
            queues: Очереди (по умолчанию system:100, data:50)
            priority: Приоритет процесса (high/normal/low)
            memory: Опциональная секция memory для SharedMemory

        Returns:
            proc_dict для launcher.add_process(name, proc_dict)
        """
        from multiprocess_prototype.configs.app_config import get_default_managers_config

        default_queues = {"system": {"maxsize": 100}, "data": {"maxsize": 50}}
        proc_dict = {
            "class": class_path,
            "queues": queues if queues is not None else default_queues,
            "priority": priority,
            "workers": {},
            "config": self.model_dump(),
            "managers": get_default_managers_config(),
        }
        if memory is not None:
            proc_dict["memory"] = memory
        return proc_dict
