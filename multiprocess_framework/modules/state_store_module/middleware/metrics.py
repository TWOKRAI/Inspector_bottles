"""metrics.py — Middleware сбора метрик StateStore.

Считает количество операций, разбивку по источникам и время последней операции.
Предоставляет метод get_stats() для мониторинга и reset() для сброса счётчиков.
Не модифицирует и не отклоняет данные — только наблюдает.
"""

from __future__ import annotations

import time
from typing import Any

from ..core.delta import Delta
from .base import StateMiddleware


class MetricsMiddleware(StateMiddleware):
    """Сбор метрик для мониторинга StateStore.

    Считает:
    - operations_total: {"set": N, "merge": N, "delete": N}
    - operations_rejected: N — операции, отклонённые другими middleware
    - operations_by_source: {"gui": N, "camera_0": N, ...}
    - last_operation_time: timestamp последней успешной операции (time.monotonic)

    Примечание: operations_rejected увеличивается вручную вызывающим кодом
    через increment_rejected(), так как after_* вызываются только при успехе.
    """

    @property
    def name(self) -> str:
        return "metrics"

    def __init__(self) -> None:
        self._ops_total: dict[str, int] = {"set": 0, "merge": 0, "delete": 0}
        self._ops_rejected: int = 0
        self._ops_by_source: dict[str, int] = {}
        self._last_operation_time: float = 0.0

    # --- before_* — пропускаем без изменений ---

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        """Пропустить без изменений. Счётчики обновляются в after_set."""
        return True, value

    # --- after_set ---

    def after_set(self, delta: Delta, context: dict) -> None:
        """Увеличить счётчик set и обновить метрики источника."""
        self._ops_total["set"] += 1
        self._ops_by_source[delta.source] = self._ops_by_source.get(delta.source, 0) + 1
        self._last_operation_time = time.monotonic()

    # --- after_merge ---

    def after_merge(self, deltas: list[Delta], context: dict) -> None:
        """Увеличить счётчик merge. Источник берётся из первой дельты."""
        self._ops_total["merge"] += 1
        if deltas:
            source = deltas[0].source
            self._ops_by_source[source] = self._ops_by_source.get(source, 0) + 1
        self._last_operation_time = time.monotonic()

    # --- after_delete ---

    def after_delete(self, delta: Delta, context: dict) -> None:
        """Увеличить счётчик delete и обновить метрики источника."""
        self._ops_total["delete"] += 1
        self._ops_by_source[delta.source] = self._ops_by_source.get(delta.source, 0) + 1
        self._last_operation_time = time.monotonic()

    # --- Публичный API ---

    def increment_rejected(self) -> None:
        """Увеличить счётчик отклонённых операций.

        Вызывается вручную при обнаружении rejected операции,
        так как after_* хуки срабатывают только при успехе.
        """
        self._ops_rejected += 1

    def get_stats(self) -> dict:
        """Вернуть текущие метрики в виде snapshot-dict.

        Returns:
            dict с ключами:
                operations_total: {"set": N, "merge": N, "delete": N}
                operations_rejected: N
                operations_by_source: {"source_name": N, ...}
                last_operation_time: float (time.monotonic, 0.0 если не было операций)
        """
        return {
            "operations_total": dict(self._ops_total),
            "operations_rejected": self._ops_rejected,
            "operations_by_source": dict(self._ops_by_source),
            "last_operation_time": self._last_operation_time,
        }

    def reset(self) -> None:
        """Сбросить все счётчики в начальное состояние."""
        self._ops_total = {"set": 0, "merge": 0, "delete": 0}
        self._ops_rejected = 0
        self._ops_by_source.clear()
        self._last_operation_time = 0.0
