"""
Базовый конфиг процессов Inspector Prototype.

ProcessConfigBase — общая логика build() для всех процессов:
class, queues, priority, workers, config, managers.
Подклассы переопределяют process_name, class_path и опционально memory.
"""

from typing import Dict, Any, Optional

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase


class ProcessConfigBase(SchemaBase):
    """
    Базовый конфиг процесса с общей структурой proc_dict.

    Подклассы переопределяют process_name и вызывают _build_proc_dict()
    с class_path и опционально queues, priority, memory.
    """

    process_name: str = "base"

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
