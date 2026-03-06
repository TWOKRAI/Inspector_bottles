"""
Конфиг process_2 — RegisterBase + FieldMeta, data_schema_module.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    RegisterBase,
    FieldMeta,
    register_schema,
)
from .process_2_module import Process2Module


@register_schema("Process2Config")
class Process2Config(RegisterBase):
    """Регистр конфигурации process_2."""

    process_name: str = "process_2"
    priority: str = "normal"
    queue_maxsize: Annotated[int, FieldMeta("Размер очереди", min=1, max=10000)] = 100

    def build(self) -> tuple[str, dict]:
        """Вернуть (имя_процесса, config_dict) для ProcessManager."""
        class_path = f"{Process2Module.__module__}.{Process2Module.__name__}"
        return (self.process_name, {
            "class": class_path,
            "queue_maxsize": self.queue_maxsize,
            "queues": {
                "system": {"maxsize": self.queue_maxsize},
                "data": {"maxsize": self.queue_maxsize},
            },
            "priority": self.priority,
        })
