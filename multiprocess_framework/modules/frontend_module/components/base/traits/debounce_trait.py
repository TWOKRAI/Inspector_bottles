# -*- coding: utf-8 -*-
"""
DebounceTrait — отложенная запись (для слайдера).

Один QTimer создаётся в __init__, schedule() только перезапускает.
"""
from __future__ import annotations

from typing import Callable, Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import QTimer


class DebounceTrait:
    """Трейт: отложенная запись через QTimer."""

    def __init__(self, ms: int = 100) -> None:
        self._ms = ms
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._pending: Optional[Callable[[], None]] = None

    def schedule(self, callback: Callable[[], None]) -> None:
        """Запланировать вызов callback через ms (перезапуск таймера)."""
        self.cancel()
        self._pending = callback
        self._timer.start(self._ms)

    def cancel(self) -> None:
        """Отменить отложенный вызов."""
        self._timer.stop()
        self._pending = None

    def flush(self) -> None:
        """Немедленно выполнить отложенный вызов."""
        if self._pending:
            cb = self._pending
            self._pending = None
            self._timer.stop()
            cb()

    def _fire(self) -> None:
        if self._pending:
            cb = self._pending
            self._pending = None
            self._timer.stop()
            cb()
