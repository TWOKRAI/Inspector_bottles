# -*- coding: utf-8 -*-
"""
DirectBuffer — буферная стратегия без буферизации.

Вызывает send_fn(channel, data) напрямую при enqueue().
Используется:
  - В тестах (предсказуемое синхронное поведение)
  - В простых однопоточных сценариях без необходимости в буферизации

Thread safety:
    send_fn вызывается в том же потоке что и enqueue() — без блокировок.
    Если send_fn не thread-safe, вызывающий код должен обеспечить синхронизацию.
"""

from typing import Any, Callable, Dict, Optional

from ..interfaces import IBufferStrategy


class DirectBuffer(IBufferStrategy):
    """Без буферизации: enqueue() немедленно вызывает send_fn."""

    def __init__(self, send_fn: Callable[[str, Dict[str, Any]], Any]) -> None:
        """
        Args:
            send_fn: fn(channel_name: str, data: Dict) → Any
                     Функция фактической записи в канал.
        """
        self._send_fn = send_fn
        self._enqueued = 0
        self._errors = 0

    def enqueue(
        self, channel: str, data: Dict[str, Any], priority: str = "normal"
    ) -> None:
        """Немедленно вызывает send_fn. Приоритет игнорируется."""
        try:
            self._send_fn(channel, data)
            self._enqueued += 1
        except Exception:
            self._errors += 1
            raise

    def flush(self, channel: Optional[str] = None) -> None:
        """Нечего сбрасывать — данные уже записаны."""

    def start(self) -> None:
        """Нет фоновых ресурсов для запуска."""

    def stop(self) -> None:
        """Нет фоновых ресурсов для остановки."""

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "type": "direct",
            "enqueued": self._enqueued,
            "errors": self._errors,
        }
