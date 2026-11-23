# -*- coding: utf-8 -*-
"""Task 1.7c (system-run-state) — heartbeat ребёнка несёт его ``pid``.

Контракт (из брифа): в сообщении heartbeat есть поле ``pid`` = ``os.getpid()`` процесса-ребёнка (целое; аддитивно).
ProcessManager по нему отличает воплощение, которое пришлось убить рестартом, от нового. Красный до реализации:
``KeyError``/``AssertionError`` — поля в сообщении нет.
"""

from __future__ import annotations

import os

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)


class _Services:
    """Носитель heartbeat: имя и журнал отправленных сообщений (как в соседних тестах heartbeat)."""

    def __init__(self) -> None:
        self.name = "proc"
        self.worker_manager = None
        self.heartbeats: list[dict] = []

    def send_message(self, target: str, message: dict) -> bool:
        self.heartbeats.append(message)
        return True


def test_heartbeat_message_carries_own_pid() -> None:
    """Отправленный heartbeat содержит ``pid`` == ``os.getpid()`` (целое, не bool)."""
    svc = _Services()

    ProcessHeartbeat(svc)._send_heartbeat({})

    assert len(svc.heartbeats) == 1
    msg = svc.heartbeats[0]
    assert "pid" in msg, f"в heartbeat нет поля pid: {sorted(msg)}"
    assert type(msg["pid"]) is int, msg["pid"]
    assert msg["pid"] == os.getpid()
