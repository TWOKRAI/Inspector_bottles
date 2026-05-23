"""WireStatusMonitor — мониторинг статусов и метрик wire'ов.

Lifecycle wire'а:
  NOT_CONFIGURED → PENDING → IDLE / ACTIVE → BROKEN

Pure Python логика; QTimer — опциональный (ленивая инициализация).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


__all__ = [
    "WireStatus",
    "WireMetrics",
    "WireStatusMonitor",
]


class WireStatus(Enum):
    """Жизненный цикл wire."""

    NOT_CONFIGURED = "not_configured"
    PENDING = "pending"  # wire.setup отправлен, ответа нет
    IDLE = "idle"  # SHM создан, данных пока нет
    ACTIVE = "active"  # данные передаются
    BROKEN = "broken"  # ошибка или timeout


@dataclass
class WireMetrics:
    """Метрики одного wire."""

    fps: float = 0.0
    latency_ms: float = 0.0
    buffer_fill: float = 0.0  # 0.0–1.0
    last_update: float = 0.0  # UNIX timestamp


class WireStatusMonitor:
    """Мониторинг статусов и метрик wire'ов.

    Pure Python логика + опциональный QTimer для периодического polling.
    Все публичные методы потокобезопасны при GIL (только dict-операции).
    """

    def __init__(
        self,
        *,
        pending_timeout_sec: float = 10.0,
        poll_interval_ms: int = 2000,
    ) -> None:
        self._pending_timeout = pending_timeout_sec
        self._poll_interval = poll_interval_ms

        # Основные хранилища
        self._statuses: dict[str, WireStatus] = {}
        self._metrics: dict[str, WireMetrics] = {}
        self._pending_since: dict[str, float] = {}  # wire_key → timestamp

        # QTimer создаётся лениво в start_polling
        self._timer: Any = None

    # ------------------------------------------------------------------
    # Lifecycle callbacks
    # ------------------------------------------------------------------

    def on_wire_setup_sent(self, wire_key: str) -> None:
        """Перевести wire в PENDING и запомнить момент отправки."""
        self._statuses[wire_key] = WireStatus.PENDING
        self._pending_since[wire_key] = time.time()
        # Инициализировать метрики, если ещё нет записи
        if wire_key not in self._metrics:
            self._metrics[wire_key] = WireMetrics()

    def on_wire_teardown_sent(self, wire_key: str) -> None:
        """Удалить wire из мониторинга."""
        self._statuses.pop(wire_key, None)
        self._metrics.pop(wire_key, None)
        self._pending_since.pop(wire_key, None)

    # ------------------------------------------------------------------
    # Runtime ответы
    # ------------------------------------------------------------------

    def on_status_received(self, wire_key: str, status: str) -> None:
        """Обновить статус wire.

        Если wire ещё не известен — создать запись (например, wire
        зарегистрировался сам без предварительного setup).
        """
        try:
            new_status = WireStatus(status)
        except ValueError:
            # Неизвестное значение статуса — фиксируем как BROKEN
            new_status = WireStatus.BROKEN

        self._statuses[wire_key] = new_status

        # Если wire вышел из PENDING — убрать таймер ожидания
        if new_status != WireStatus.PENDING:
            self._pending_since.pop(wire_key, None)

        # Гарантируем наличие записи метрик
        if wire_key not in self._metrics:
            self._metrics[wire_key] = WireMetrics()

    def on_metrics_received(self, wire_key: str, metrics: dict) -> None:
        """Обновить WireMetrics из словаря.

        Неизвестные ключи игнорируются.
        """
        entry = self._metrics.get(wire_key)
        if entry is None:
            entry = WireMetrics()
            self._metrics[wire_key] = entry

        if "fps" in metrics:
            entry.fps = float(metrics["fps"])
        if "latency_ms" in metrics:
            entry.latency_ms = float(metrics["latency_ms"])
        if "buffer_fill" in metrics:
            entry.buffer_fill = float(metrics["buffer_fill"])
        entry.last_update = time.time()

    # ------------------------------------------------------------------
    # Инспекция
    # ------------------------------------------------------------------

    def get_status(self, wire_key: str) -> WireStatus:
        """Вернуть статус wire. NOT_CONFIGURED если wire не известен."""
        return self._statuses.get(wire_key, WireStatus.NOT_CONFIGURED)

    def get_all_statuses(self) -> dict[str, WireStatus]:
        """Копия словаря всех статусов (не ссылка)."""
        return dict(self._statuses)

    def get_metrics(self, wire_key: str) -> WireMetrics | None:
        """Вернуть метрики wire или None если не известен."""
        return self._metrics.get(wire_key)

    def get_broken_wires(self) -> list[str]:
        """Список ключей wire'ов в статусе BROKEN."""
        return [key for key, st in self._statuses.items() if st == WireStatus.BROKEN]

    def summary(self) -> str:
        """Краткая сводка. Формат: '3 active, 1 pending, 0 broken'."""
        active = sum(1 for st in self._statuses.values() if st == WireStatus.ACTIVE)
        pending = sum(1 for st in self._statuses.values() if st == WireStatus.PENDING)
        broken = sum(1 for st in self._statuses.values() if st == WireStatus.BROKEN)
        return f"{active} active, {pending} pending, {broken} broken"

    # ------------------------------------------------------------------
    # Timeout
    # ------------------------------------------------------------------

    def check_timeouts(self) -> list[str]:
        """Проверить PENDING wire'ы на превышение timeout.

        Переводит просроченные в BROKEN и возвращает их список.
        """
        now = time.time()
        timed_out: list[str] = []

        for wire_key, since in list(self._pending_since.items()):
            if now - since >= self._pending_timeout:
                self._statuses[wire_key] = WireStatus.BROKEN
                self._pending_since.pop(wire_key, None)
                timed_out.append(wire_key)

        return timed_out

    # ------------------------------------------------------------------
    # Polling (опциональный, только с Qt)
    # ------------------------------------------------------------------

    def start_polling(self, sender: Any = None) -> None:
        """Запустить периодический polling через QTimer (если Qt доступен).

        ``sender`` — опциональный callable, вызываемый при каждом тике
        (например, функция запроса метрик у процессов).
        """
        try:
            from PySide6.QtCore import QTimer  # type: ignore[import]
        except ImportError:
            return  # Qt не доступен — работаем без polling

        if self._timer is not None:
            return  # уже запущен

        def _tick() -> None:
            self.check_timeouts()
            if callable(sender):
                sender()

        timer = QTimer()
        timer.setInterval(self._poll_interval)
        timer.timeout.connect(_tick)
        timer.start()
        self._timer = timer

    def stop_polling(self) -> None:
        """Остановить QTimer polling."""
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:  # nosec B110 — намеренный silence при cleanup QTimer
                pass
            self._timer = None
