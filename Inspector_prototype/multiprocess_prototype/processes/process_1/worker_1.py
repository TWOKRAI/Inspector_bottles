"""
Worker 1 — ping-pong воркер для process_1.
Принимает сообщения через router_manager.receive(), отправляет через router_manager.send().
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
        class_path = f"{Worker1.__module__}.{Worker1.__name__}"
        return (self.name, {
            "class": class_path,
            "config": {"interval": self.interval},
        })


class Worker1:
    """
    Ping-pong воркер (сторона process_1).

    Отправляет и принимает сообщения исключительно через router_manager —
    прямого доступа к очередям нет.
    """

    def __init__(self, process: Any, config: dict):
        self.process = process
        self.interval = config.get("interval", 0.01)
        self._initial_sent = False

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue

            router = self.process.router_manager
            if not router:
                time.sleep(self.interval)
                continue

            # Первая отправка — запускаем пинг-понг
            if not self._initial_sent:
                self._initial_sent = True
                result = router.send({
                    "channel": "process_2_worker_in",
                    "sender": "worker_1",
                    "command": "ping",
                    "data": {"n": 0},
                })
                if result.get("status") == "success":
                    print("[worker_1] ОТПРАВИЛ старт ping n=0", flush=True)
                else:
                    print(f"[worker_1] ОШИБКА отправки: {result}", flush=True)

            # Читаем все входящие через роутер
            for msg in router.receive():
                msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
                if msg_dict.get("command") == "pong":
                    n = msg_dict.get("data", {}).get("n", 0)
                    new_n = n + 1
                    print(f"[worker_1] ПРИНЯЛ pong n={n}, отправляю ping n={new_n}", flush=True)
                    router.send({
                        "channel": "process_2_worker_in",
                        "sender": "worker_1",
                        "command": "ping",
                        "data": {"n": new_n},
                    })

            time.sleep(self.interval)
