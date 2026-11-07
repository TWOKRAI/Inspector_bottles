"""ЗАГЛУШКА CloseCoordinator (Task 1.1, plans/2026-10-20_gui-graceful-close/tasks/1.1.md).

Только интерфейс: сигнатуры и состояния. Поведения нет, методы ничего не делают. Заглушка нужна слепому
tester, чтобы его тесты упали по поведению, а не по ImportError. Teamlead заменяет файл реализацией
(шаги 1-5 и 10 DESIGN), сигнатуры не меняя.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol

from PySide6.QtCore import QObject

__all__ = ["CloseCoordinator", "CloseState", "Closable"]


class Closable(Protocol):
    """Ручка открытого вопроса: ``close()`` закрывает его без ответа оператора."""

    def close(self) -> None: ...


class CloseState(str, Enum):
    RUNNING = "running"
    CONFIRMING = "confirming"
    STOPPING = "stopping"
    CLOSING = "closing"


class CloseCoordinator(QObject):
    """Заглушка: ничего не делает, состояние всегда ``RUNNING``."""

    def __init__(
        self,
        window: Any,
        *,
        confirm_discard: Callable[[], bool],
        send_shutdown: Callable[[], dict],
        poll_status: Callable[[float], dict],
        ignore_names: frozenset[str],
        ask_force_stop: Callable[[Callable[[bool], None]], Closable],
        force_stop: Callable[[], None],
        quit_app: Callable[[], None],
        on_shutdown_sent: Callable[[], None],
        unattended: bool = False,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_ms: int = 250,
        no_answer_s: float = 2.0,
        request_runner: Any | None = None,
    ) -> None:
        super().__init__(window)
        self._state = CloseState.RUNNING

    @property
    def state(self) -> CloseState:
        return self._state

    def request_close(self) -> None:
        """Крестик."""

    def request_restart(self) -> None:
        """Рестарт UI (без ``system.shutdown``)."""

    def backend_gone(self) -> None:
        """``should_stop`` при ``RUNNING``/``CONFIRMING``."""

    def commit_close(self) -> None:
        """``→ CLOSING``, затем ``quit_app()``."""

    def on_safety_tick(self, should_stop: bool) -> None:
        """Тик safety-таймера (интервал 1000 мс остаётся в app.py)."""
