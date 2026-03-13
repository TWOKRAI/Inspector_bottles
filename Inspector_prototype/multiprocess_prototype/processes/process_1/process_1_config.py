"""
Конфиг process_1 — SchemaBase + FieldMeta, data_schema_module.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaBase,
    FieldMeta,
    register_schema,
)
from .process_1_module import Process1Module


@register_schema("Process1Config")
class Process1Config(SchemaBase):
    """Регистр конфигурации process_1."""

    process_name: str = "process_1"
    priority: str = "normal"
    queue_maxsize: Annotated[int, FieldMeta("Размер очереди", min=1, max=10000)] = 100

    def build(self) -> tuple[str, dict]:
        """Вернуть (имя_процесса, config_dict) для ProcessManager."""
        class_path = f"{Process1Module.__module__}.{Process1Module.__name__}"
        return (self.process_name, {
            "class": class_path,
            "channels": {"worker_in": {"maxsize": 50, "type": "queue"}},

            "queue_maxsize": self.queue_maxsize,
            "queues": {
                "system": {"maxsize": self.queue_maxsize},
                "data": {"maxsize": self.queue_maxsize},
                "worker_in": {"maxsize": 50},
            },
            "priority": self.priority,
        })
