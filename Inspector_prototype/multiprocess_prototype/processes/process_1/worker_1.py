"""
Worker 1 — воркер для process_1. Ping-pong: явное чтение из worker_in, отправка через роутер.
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


@register_schema("Worker1Config")
class Worker1Config(RegisterBase):
    """Регистр конфигурации worker_1."""

    name: str = "worker_1"
    interval: Annotated[float, FieldMeta("Интервал опроса, сек", min=0.001, max=10.0)] = 1

    def build(self) -> tuple[str, dict]:
        """Вернуть (имя_воркера, worker_dict) для build_process_with_workers."""
        class_path = f"{Worker1.__module__}.{Worker1.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
        })


class Worker1:
    """Воркер 1. Явное чтение из worker_in, отправка в process_2_worker_in."""

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.01)
        self._initial_sent = False

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
                    if isinstance(msg, dict) and msg.get("command") == "pong":
                        n = msg.get("data", {}).get("n", 0)
                        new_n = n + 1
                        print(f"[worker_1] ПРИНЯЛ {n}, +1={new_n}, отправляю")
                        self.process.router_manager.send({
                            "channel": "process_2_worker_in",
                            "sender": "worker_1",
                            "command": "ping",
                            "data": {"n": new_n},
                        })
                except Empty:
                    pass

            # Первая отправка
            if not self._initial_sent:
                self._initial_sent = True
                result = self.process.router_manager.send({
                    "channel": "process_2_worker_in",
                    "sender": "worker_1",
                    "command": "ping",
                    "data": {"n": 0},
                })
                if result.get("status") == "success":
                    print(f"[worker_1] ОТПРАВИЛ старт: n=0")

            time.sleep(self.interval)
