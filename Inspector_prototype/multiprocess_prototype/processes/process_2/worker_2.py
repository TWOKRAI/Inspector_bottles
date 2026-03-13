"""
Workers для process_2.
"""

import time
from typing import Any

from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaBase,
    FieldMeta,
    register_schema,
)
from typing import Annotated


@register_schema("Worker2_1Config")
class Worker2_1Config(SchemaBase):
    """Регистр конфигурации worker_2_1."""

    name: str = "worker_2_1"
    interval: Annotated[float, FieldMeta("Интервал опроса, сек", min=0.001, max=10.0)] = 1
    priority: str = "NORMAL"
    execution_mode: str = "loop"
    restart_on_failure: bool = False
    max_restarts: int = 3

    def build(self) -> tuple[str, dict]:
        class_path = f"{Worker2_1.__module__}.{Worker2_1.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
            "thread": {
                "priority": self.priority,
                "execution_mode": self.execution_mode,
                "restart_on_failure": self.restart_on_failure,
                "max_restarts": self.max_restarts,
            },
        })


@register_schema("Worker2_2Config")
class Worker2_2Config(SchemaBase):
    """Регистр конфигурации worker_2_2."""

    name: str = "worker_2_2"
    interval: Annotated[float, FieldMeta("Интервал опроса, сек", min=0.001, max=10.0)] = 1
    priority: str = "NORMAL"
    execution_mode: str = "loop"
    restart_on_failure: bool = False
    max_restarts: int = 3

    def build(self) -> tuple[str, dict]:
        class_path = f"{Worker2_2.__module__}.{Worker2_2.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
            "thread": {
                "priority": self.priority,
                "execution_mode": self.execution_mode,
                "restart_on_failure": self.restart_on_failure,
                "max_restarts": self.max_restarts,
            },
        })


class Worker2_1:
    """Воркер 2.1 — вспомогательный, не участвует в пинг-понге."""

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.01)

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self.interval)
            print("Worker 2.1", flush=True)


class Worker2_2:
    """
    Ping-pong воркер (сторона process_2).

    Принимает ping через router_manager.receive(), отвечает pong через router_manager.send().
    Прямого доступа к очередям нет.
    """

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.02)

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue

            router = self.process.router_manager
            if not router:
                time.sleep(self.interval)
                continue

            # Читаем все входящие через роутер
            for msg in router.receive():
                msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
                if msg_dict.get("command") == "ping":
                    n = msg_dict.get("data", {}).get("n", 0)
                    new_n = n + 1
                    print(f"[worker_2_2] ПРИНЯЛ ping n={n}, отправляю pong n={new_n}", flush=True)
                    router.send({
                        "channel": "process_1_worker_in",
                        "sender": "worker_2_2",
                        "command": "pong",
                        "data": {"n": new_n},
                    })
                else:
                    print(f"[worker_2_2] неожиданное сообщение: {msg_dict}", flush=True)

            time.sleep(self.interval)
