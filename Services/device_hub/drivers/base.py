"""BaseDeviceDriver — базовый класс драйверов устройств (Р5/У7).

Наследует BaseManager + ObservableMixin (правило владельца: все компоненты
через BaseManager). Инъекции clock/sleep — как у RobotClient — для
детерминированных тестов.

Quality codes (ревью Р8): каждый snapshot несёт quality + ts:
    good  — последний tick успешен
    stale — драйвер сам пометил (напр. carrier busy)
    bad   — последний tick упал / нет соединения

Stats: tx_ok, tx_err, reconnects, last_latency_ms — диагностические счётчики.
"""

from __future__ import annotations

import time
from typing import Any

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin


class BaseDeviceDriver(BaseManager, ObservableMixin):
    """Базовый драйвер устройства.

    Подклассы обязаны реализовать:
        kind       — строка ("robot", "vfd", ...)
        connect()  — установить соединение
        disconnect() — закрыть соединение
        is_connected — property
        tick(stop_event) -> dict | None — один шаг поллинга
        call(op, args) -> dict — диспетчер операций

    Args:
        entry:    DeviceEntry описывающий устройство.
        protocol: DeviceProtocol или None (hikvision).
        clock:    Источник монотонного времени (для тестов).
        sleep:    Функция паузы (для тестов).
    """

    kind: str = ""

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        *,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        BaseManager.__init__(self, manager_name=f"driver_{entry.id}")
        ObservableMixin.__init__(self)
        self.entry = entry
        self.protocol = protocol
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep

        # Диагностические счётчики (Р8)
        self._stats: dict[str, Any] = {
            "tx_ok": 0,
            "tx_err": 0,
            "reconnects": 0,
            "last_latency_ms": 0.0,
        }
        # Последнее качество (для snapshot)
        self._last_quality: str = "bad"

        # НР-1/НР-2: desired-state — проставляется плагином-supervisor'ом.
        # Драйвер НЕ должен реконнектиться при desired_connected=False.
        # Runtime-атрибут, НЕ persist.
        self.desired_connected: bool = False

    # ------------------------------------------------------------------ #
    # Контракт BaseManager
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """Инициализация менеджера."""
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Остановка менеджера."""
        self.disconnect()
        self.is_initialized = False
        return True

    # ------------------------------------------------------------------ #
    # Контракт драйвера (переопределить в подклассах)
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        """Установлено ли соединение."""
        return False

    def connect(self) -> bool:
        """Установить соединение. Возвращает True при успехе."""
        raise NotImplementedError

    def disconnect(self) -> None:
        """Закрыть соединение."""
        raise NotImplementedError

    def tick(self, stop_event: Any = None) -> dict | None:
        """Один шаг поллинга -> snapshot или None."""
        raise NotImplementedError

    def call(self, op: str, args: dict) -> dict:
        """Диспетчер операций."""
        return {"status": "error", "message": f"Неизвестная операция: {op!r}"}

    # ------------------------------------------------------------------ #
    # Stats и snapshot
    # ------------------------------------------------------------------ #

    @property
    def stats(self) -> dict[str, Any]:
        """Снимок диагностических счётчиков."""
        return dict(self._stats)

    def snapshot(self, data: dict | None = None, quality: str | None = None) -> dict:
        """Обёртка snapshot: добавляет quality + ts + stats.

        Args:
            data:    Kind-специфичные данные (None -> пустой dict).
            quality: ``good`` | ``stale`` | ``bad``. Если None — берётся
                     последнее сохранённое значение.

        Returns:
            Полный snapshot: {quality, ts, stats, ...data}.
        """
        if quality is not None:
            self._last_quality = quality
        result: dict[str, Any] = {
            "quality": self._last_quality,
            "ts": time.time(),
            "stats": dict(self._stats),
        }
        if data:
            result.update(data)
        return result

    def _record_ok(self, latency_ms: float = 0.0) -> None:
        """Зафиксировать успешную операцию."""
        self._stats["tx_ok"] += 1
        self._stats["last_latency_ms"] = latency_ms

    def _record_err(self) -> None:
        """Зафиксировать ошибку операции."""
        self._stats["tx_err"] += 1

    def _record_reconnect(self) -> None:
        """Зафиксировать переподключение."""
        self._stats["reconnects"] += 1
