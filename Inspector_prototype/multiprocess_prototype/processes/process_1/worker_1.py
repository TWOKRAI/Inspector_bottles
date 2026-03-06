"""
Worker 1 — воркер для process_1.
"""

import time
from typing import Any

from multiprocess_framework.refactored.modules.data_schema_module import (
    RegisterBase,
    FieldMeta,
    register_schema,
)
from typing import Annotated


@register_schema("Worker1Config")
class Worker1Config(RegisterBase):
    """Регистр конфигурации worker_1."""

    name: str = "worker_1"
    interval: Annotated[float, FieldMeta("Интервал опроса, сек", min=0.001, max=10.0)] = 1

    def build(self) -> tuple[str, dict]:
        """Вернуть (имя_воркера, worker_dict) для ProcessBuilder."""
        class_path = f"{Worker1.__module__}.{Worker1.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
        })


class Worker1:
    """Воркер 1. Цикл с интервалом."""

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.01)

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self.interval)
            print("Worker 1")
