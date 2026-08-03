# -*- coding: utf-8 -*-
"""Ф6.4б — heartbeat не подменяет незнание утверждением «работает».

Находка Н-5б живого прогона (2026-08-03): статус готовности врал в ТРЁХ местах,
и однажды его уже чинили — но на одном пути из трёх. Здесь третье место:
``_send_heartbeat`` брал статус через ``getattr(..., "_current_process_status",
"running")``. Отсутствие атрибута — это «не знаю», а фолбэк отвечал «работаю»;
соседний ``introspect.status`` в тех же условиях отвечает ``"unknown"``. Два
разных ответа на один вопрос хуже, чем один незнающий.

Пара обязательна: атрибут есть → в heartbeat едет его значение (иначе тест
зелен и на коде, который вообще не читает статус).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)


class _ServicesWithoutStatus:
    """Носитель БЕЗ ``_current_process_status`` — «статус неизвестен»."""

    def __init__(self, *, name: str = "proc") -> None:
        self.name = name
        self.worker_manager = None
        self.heartbeats: list[dict] = []

    def send_message(self, target: str, message: dict) -> bool:
        self.heartbeats.append(message)
        return True


class _ServicesWithStatus(_ServicesWithoutStatus):
    def __init__(self, status: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._current_process_status = status


class TestHeartbeatStatusFallback:
    def test_missing_status_is_unknown_not_running(self) -> None:
        """Нет атрибута → ``unknown``. Утверждать «работает» здесь нечем."""
        svc = _ServicesWithoutStatus()

        ProcessHeartbeat(svc)._send_heartbeat({})

        assert svc.heartbeats[0]["status"] == "unknown", (
            f"heartbeat подменил незнание утверждением «работает» — пришло {svc.heartbeats[0]['status']!r}"
        )

    def test_present_status_is_reported_as_is(self) -> None:
        """Вторая половина пары: известный статус едет как есть, включая не-running."""
        for status in ("initializing", "running", "paused"):
            svc = _ServicesWithStatus(status)

            ProcessHeartbeat(svc)._send_heartbeat({})

            assert svc.heartbeats[0]["status"] == status, (
                f"статус {status!r} не доехал до heartbeat: {svc.heartbeats[0]['status']!r}"
            )
