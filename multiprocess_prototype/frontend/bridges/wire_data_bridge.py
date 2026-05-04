"""WireDataBridge — мониторинг runtime-статусов wire-соединений.

Периодически (каждые 2 секунды) запрашивает статусы wire-каналов через
command_handler и предоставляет их в GUI через Qt-сигнал statuses_changed.

MVP-поведение:
  - polling отправляет wire.status команду, но не ждёт async ответа
  - статусы обновляются через on_apply_started / on_apply_completed
  - при отсутствии command_handler все wires = NOT_APPLIED, polling молчит
"""

from __future__ import annotations

import logging
import time
from copy import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor

logger = logging.getLogger(__name__)

# Порог (в секундах), после которого PENDING считается BROKEN
_PENDING_TIMEOUT_SEC = 10.0


class WireStatus(str, Enum):
    """Возможные runtime-статусы wire-соединения."""

    NOT_APPLIED = "not_applied"
    """Только в конфигурации, wire.setup ещё не отправлен."""

    PENDING = "pending"
    """wire.setup отправлен, ответ ожидается."""

    IDLE = "idle"
    """SHM создан, middleware подключен, данные не передаются."""

    ACTIVE = "active"
    """Данные передаются через wire-канал."""

    BROKEN = "broken"
    """Ошибка: SHM или процесс недоступен."""


@dataclass
class WireMetrics:
    """Количественные метрики wire-канала."""

    fps: float = 0.0
    latency_ms: float = 0.0
    buffer_fill: float = 0.0  # 0.0-1.0


class WireDataBridge(QObject):
    """Мониторинг runtime-статусов wire-каналов.

    Паттерн аналогичен TopologyBridge, но ориентирован на чтение статусов,
    а не на применение конфигурации.

    Graceful degradation:
      - command_handler is None → polling молчит, все wires NOT_APPLIED
      - topology_editor is None → работа только через on_apply_* методы
    """

    # Сигнал: статусы изменились. Payload — копия всего словаря статусов.
    statuses_changed = Signal(dict)

    # Сигнал: метрики изменились. Payload — {wire_key: WireMetrics}.
    metrics_changed = Signal(dict)

    def __init__(
        self,
        command_handler: Any = None,
        topology_editor: Optional["SystemTopologyEditor"] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        """Инициализация bridge.

        Args:
            command_handler: GuiCommandHandler для отправки wire.status (может быть None).
            topology_editor: SystemTopologyEditor для сверки конфигурации (может быть None).
            parent: Родительский QObject.
        """
        super().__init__(parent)

        self._cmd = command_handler
        self._editor = topology_editor

        # Текущие статусы: wire_key → WireStatus
        self._wire_statuses: dict[str, WireStatus] = {}

        # Текущие метрики: wire_key → WireMetrics
        self._wire_metrics: dict[str, WireMetrics] = {}

        # Время перехода в PENDING: wire_key → timestamp (monotonic)
        self._pending_since: dict[str, float] = {}

        # Таймер polling
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_statuses)

    # ------------------------------------------------------------------
    # Публичный API — управление мониторингом
    # ------------------------------------------------------------------

    def start_monitoring(self) -> None:
        """Запустить периодический polling статусов."""
        if not self._poll_timer.isActive():
            self._poll_timer.start()
            logger.info("WireDataBridge: polling запущен (интервал 2000 мс)")

    def stop_monitoring(self) -> None:
        """Остановить периодический polling статусов."""
        if self._poll_timer.isActive():
            self._poll_timer.stop()
            logger.info("WireDataBridge: polling остановлен")

    # ------------------------------------------------------------------
    # Публичный API — чтение статусов
    # ------------------------------------------------------------------

    def get_status(self, wire_key: str) -> WireStatus:
        """Вернуть текущий статус wire-канала.

        Args:
            wire_key: Ключ wire в конфигурации (ключ из wires dict).

        Returns:
            WireStatus (default: NOT_APPLIED если wire неизвестен).
        """
        return self._wire_statuses.get(wire_key, WireStatus.NOT_APPLIED)

    def get_all_statuses(self) -> dict[str, WireStatus]:
        """Вернуть копию всех текущих статусов.

        Returns:
            Копия словаря wire_key → WireStatus.
        """
        return copy(self._wire_statuses)

    # ------------------------------------------------------------------
    # Публичный API — чтение метрик
    # ------------------------------------------------------------------

    def get_metrics(self, wire_key: str) -> WireMetrics:
        """Вернуть метрики wire-канала (default: нули если неизвестен).

        Args:
            wire_key: Ключ wire в конфигурации.

        Returns:
            WireMetrics с нулевыми значениями если wire неизвестен.
        """
        return self._wire_metrics.get(wire_key, WireMetrics())

    def get_all_metrics(self) -> dict[str, WireMetrics]:
        """Вернуть копию всех метрик.

        Returns:
            Копия словаря wire_key → WireMetrics.
        """
        return dict(self._wire_metrics)

    def on_metrics_received(self, data: dict) -> None:
        """Обновить метрики из полученных данных.

        Формат data: {wire_key: {"fps": float, "latency_ms": float, "buffer_fill": float}}

        Args:
            data: Словарь с метриками по каждому wire-каналу.
        """
        if not data:
            return

        changed = False
        for wire_key, raw in data.items():
            if not isinstance(raw, dict):
                continue
            new_metrics = WireMetrics(
                fps=float(raw.get("fps", 0.0)),
                latency_ms=float(raw.get("latency_ms", 0.0)),
                buffer_fill=max(0.0, min(1.0, float(raw.get("buffer_fill", 0.0)))),
            )
            if self._wire_metrics.get(wire_key) != new_metrics:
                self._wire_metrics[wire_key] = new_metrics
                changed = True

        if changed:
            self.metrics_changed.emit(dict(self._wire_metrics))

    # ------------------------------------------------------------------
    # Публичный API — обновление из apply workflow
    # ------------------------------------------------------------------

    def on_apply_started(self, wire_keys: list[str]) -> None:
        """Пометить wire-каналы как PENDING при старте apply.

        Вызывается TopologyBridge перед отправкой wire.setup команд.

        Args:
            wire_keys: Список ключей wire, для которых отправляется wire.setup.
        """
        if not wire_keys:
            return

        now = time.monotonic()
        changed = False

        for key in wire_keys:
            if self._wire_statuses.get(key) != WireStatus.PENDING:
                self._wire_statuses[key] = WireStatus.PENDING
                self._pending_since[key] = now
                changed = True

        if changed:
            logger.debug(
                "WireDataBridge: PENDING — %d wires: %s", len(wire_keys), wire_keys
            )
            self.statuses_changed.emit(copy(self._wire_statuses))

    def on_apply_completed(self, results: dict) -> None:
        """Обновить статусы из результатов apply.

        Ожидаемый формат results:
          {
            "wire_key_1": "idle",    # или "active", "broken"
            "wire_key_2": "broken",
            ...
          }

        Неизвестные статусы (вне WireStatus enum) игнорируются с предупреждением.

        Args:
            results: Словарь wire_key → строковый статус.
        """
        if not results:
            return

        changed = False
        valid_values = {s.value for s in WireStatus}

        for key, raw_status in results.items():
            if raw_status not in valid_values:
                logger.warning(
                    "WireDataBridge: неизвестный статус '%s' для wire '%s' — пропущен",
                    raw_status,
                    key,
                )
                continue

            new_status = WireStatus(raw_status)
            if self._wire_statuses.get(key) != new_status:
                self._wire_statuses[key] = new_status
                # Снять метку pending_since если wire вышел из PENDING
                if new_status != WireStatus.PENDING:
                    self._pending_since.pop(key, None)
                changed = True

        if changed:
            logger.debug("WireDataBridge: статусы обновлены из результатов apply")
            self.statuses_changed.emit(copy(self._wire_statuses))

    # ------------------------------------------------------------------
    # Внутренний polling
    # ------------------------------------------------------------------

    def _poll_statuses(self) -> None:
        """Слот QTimer — периодический опрос статусов wire-каналов.

        MVP: отправляем wire.status команду, но не ждём async ответа.
        Дополнительно: сверяем конфигурацию с текущими статусами для
        выявления NOT_APPLIED и зависших PENDING (→ BROKEN).
        """
        # Отправить запрос статусов (MVP: fire-and-forget)
        if self._cmd is not None:
            try:
                self._cmd.send("process.command", data={"cmd": "wire.status"})
            except Exception:
                logger.exception("WireDataBridge: ошибка отправки wire.status")

        # Сверить конфигурацию с текущими статусами (только если есть editor)
        if self._editor is None:
            return

        changed = False
        now = time.monotonic()

        try:
            topology_data = self._editor.to_dict()
        except Exception:
            logger.exception("WireDataBridge: ошибка чтения topology_editor.to_dict()")
            return

        configured_wires: dict = topology_data.get("wires", {})

        for wire_key in configured_wires:
            current_status = self._wire_statuses.get(wire_key)

            if current_status is None:
                # Wire есть в конфигурации, но нет в статусах → NOT_APPLIED
                self._wire_statuses[wire_key] = WireStatus.NOT_APPLIED
                changed = True
                logger.debug("WireDataBridge: wire '%s' → NOT_APPLIED", wire_key)

            elif current_status == WireStatus.PENDING:
                # PENDING слишком долго → BROKEN
                pending_since = self._pending_since.get(wire_key)
                if pending_since is not None:
                    elapsed = now - pending_since
                    if elapsed > _PENDING_TIMEOUT_SEC:
                        self._wire_statuses[wire_key] = WireStatus.BROKEN
                        self._pending_since.pop(wire_key, None)
                        changed = True
                        logger.warning(
                            "WireDataBridge: wire '%s' PENDING %.1f сек → BROKEN",
                            wire_key,
                            elapsed,
                        )
                else:
                    # pending_since не записано — защита от рассинхрона
                    self._pending_since[wire_key] = now

        if changed:
            self.statuses_changed.emit(copy(self._wire_statuses))


__all__ = ["WireStatus", "WireMetrics", "WireDataBridge"]
