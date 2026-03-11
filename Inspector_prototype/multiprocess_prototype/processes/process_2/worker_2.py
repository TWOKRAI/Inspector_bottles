"""
Workers для process_2.
"""

import time
from typing import Any

try:
    from queue import Empty
except ImportError:
    from multiprocessing.queues import Empty

from multiprocess_framework.refactored.modules.data_schema_module import (
    RegisterBase,
    FieldMeta,
    register_schema,
)
from typing import Annotated


@register_schema("Worker2_1Config")
class Worker2_1Config(RegisterBase):
    """Регистр конфигурации worker_2_1."""

    name: str = "worker_2_1"
    interval: Annotated[float, FieldMeta("Интервал опроса, сек", min=0.001, max=10.0)] = 1

    def build(self) -> tuple[str, dict]:
        """Вернуть (имя_воркера, worker_dict) для build_process_with_workers."""
        class_path = f"{Worker2_1.__module__}.{Worker2_1.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
        })


@register_schema("Worker2_2Config")
class Worker2_2Config(RegisterBase):
    """Регистр конфигурации worker_2_2."""

    name: str = "worker_2_2"
    interval: Annotated[float, FieldMeta("Интервал опроса, сек", min=0.001, max=10.0)] = 1

    def build(self) -> tuple[str, dict]:
        """Вернуть (имя_воркера, worker_dict) для build_process_with_workers."""
        class_path = f"{Worker2_2.__module__}.{Worker2_2.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
        })


class Worker2_1:
    """Воркер 2.1."""

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.01)

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self.interval)
            print("Worker 2.1")


class Worker2_2:
    """Воркер 2.2. Явное чтение из worker_in, отправка в process_1_worker_in."""

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.02)

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            if not self.process.router_manager:
                time.sleep(self.interval)
                continue

            # Явное чтение из worker_in
            if self.process.queues and "worker_in" in self.process.queues:
                try:
                    msg = self.process.queues["worker_in"].get_nowait()
                    if isinstance(msg, dict) and msg.get("command") == "ping":
                        n = msg.get("data", {}).get("n", 0)
                        new_n = n + 1
                        print(f"[worker_2_2] ПРИНЯЛ {n}, +1={new_n}, отправляю")
                        self.process.router_manager.send({
                            "channel": "process_1_worker_in",
                            "sender": "worker_2_2",
                            "command": "pong",
                            "data": {"n": new_n},
                        })
                except Empty:
                    pass

            time.sleep(self.interval)
