"""inspector.py — DevTools для инспекции StateStore в runtime.

StateInspector предоставляет методы для отладки через IPC-команды или напрямую:
- inspect(path?) → полное дерево или поддерево
- subscriptions() → список активных подписок
- stats() → метрики из MetricsMiddleware (если подключён)
- history() → последние N дельт (ring buffer)
- summary() → краткая сводка состояния
"""
from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Any

from ..core.delta import Delta, MISSING
from ..core.tree_store import TreeStore
from ..core.subscription_manager import SubscriptionManager

if TYPE_CHECKING:
    from ..middleware.metrics import MetricsMiddleware


# Маркер для сериализации MISSING в dict
_MISSING_STR = "<MISSING>"


def _serialize_value(value: Any) -> Any:
    """Сериализует значение для хранения в истории.

    MISSING → строка '<MISSING>', остальные — как есть.
    """
    if value is MISSING:
        return _MISSING_STR
    return value


class StateInspector:
    """DevTools для StateStore.

    Предоставляет методы для инспекции состояния в runtime.
    Может использоваться через IPC-команды или напрямую.

    Функции:
    - inspect(path?) → полное дерево или поддерево
    - subscriptions() → список активных подписок
    - stats() → метрики из MetricsMiddleware (если подключён)
    - history() → последние N дельт (ring buffer)
    - summary() → краткая сводка
    """

    def __init__(
        self,
        store: TreeStore,
        subscription_manager: SubscriptionManager,
        metrics: "MetricsMiddleware | None" = None,
        history_size: int = 100,
    ) -> None:
        """Инициализация StateInspector.

        Args:
            store: хранилище состояния (TreeStore).
            subscription_manager: менеджер подписок.
            metrics: MetricsMiddleware (опционально).
            history_size: максимальный размер ring buffer истории.
        """
        self._store = store
        self._sub_manager = subscription_manager
        self._metrics = metrics
        self._history: deque[dict] = deque(maxlen=history_size)

    def record_delta(self, delta: Delta) -> None:
        """Записать дельту в историю.

        Вызывается как after_set callback или вручную.
        Сохраняет дельту в ring buffer (автоматически вытесняет старые записи).

        Args:
            delta: дельта изменения из TreeStore.
        """
        record = {
            "path": delta.path,
            "old": _serialize_value(delta.old_value),
            "new": _serialize_value(delta.new_value),
            "source": delta.source,
            "timestamp": time.monotonic(),
            "transaction_id": delta.transaction_id,
        }
        self._history.append(record)

    def inspect(self, path: str | None = None) -> dict:
        """Вернуть дерево состояния (или поддерево по path).

        Args:
            path: None → полное дерево.
                  "cameras.0" → поддерево камеры 0.
                  "cameras.0.config.fps" → конкретное значение (обёрнуто в dict).

        Returns:
            dict — снимок дерева или поддерева.

        Raises:
            KeyError: если путь не существует (пробрасывается из TreeStore).
        """
        if path is None:
            # Полное дерево
            return self._store.get("")

        # Пробуем получить как поддерево (dict-узел)
        value = self._store.get(path)

        if isinstance(value, dict):
            return value

        # Скалярное значение — оборачиваем с ключом = последний сегмент пути
        last_segment = path.split(".")[-1]
        return {last_segment: value}

    def subscriptions(self) -> list[dict]:
        """Вернуть список активных подписок.

        Читает внутренний _subscriptions dict из SubscriptionManager.

        Returns:
            Список dict: [{"pattern": str, "subscriber": str, "sub_id": str,
                           "exclude_sources": list}, ...]
        """
        with self._sub_manager._lock:
            subs_snapshot = list(self._sub_manager._subscriptions.values())

        result: list[dict] = []
        for sub in subs_snapshot:
            result.append({
                "pattern": sub.pattern,
                "subscriber": sub.subscriber,
                "sub_id": sub.sub_id,
                "exclude_sources": list(sub.exclude_sources),
            })

        return result

    def history(
        self,
        limit: int | None = None,
        path_filter: str | None = None,
    ) -> list[dict]:
        """Вернуть последние N дельт из ring buffer.

        Args:
            limit: ограничить количество возвращаемых записей.
                   None → все записи из буфера.
            path_filter: если указан, вернуть только дельты для путей,
                         содержащих эту подстроку.

        Returns:
            Список dict: [{"path": str, "old": Any, "new": Any,
                           "source": str, "timestamp": float,
                           "transaction_id": str}, ...]
            Отсортирован от старых к новым (как в буфере).
        """
        # Снимок буфера
        records = list(self._history)

        # Фильтрация по пути
        if path_filter is not None:
            records = [r for r in records if path_filter in r["path"]]

        # Ограничение количества — берём последние N
        if limit is not None:
            records = records[-limit:]

        return records

    def stats(self) -> dict | None:
        """Вернуть метрики из MetricsMiddleware.

        Returns:
            dict с метриками или None если MetricsMiddleware не установлен.
        """
        if self._metrics is None:
            return None
        return self._metrics.get_stats()

    def summary(self) -> dict:
        """Краткая сводка: размер дерева, кол-во подписок, кол-во дельт в истории.

        Returns:
            dict: {
                "tree_root_keys": int — количество ключей в корне дерева,
                "subscriptions_total": int — количество активных подписок,
                "history_size": int — количество записей в ring buffer,
                "history_capacity": int — максимальная ёмкость ring buffer,
            }
        """
        root_keys = len(self._store.keys(""))
        subs_count = self._sub_manager.subscription_count
        history_len = len(self._history)
        history_cap = self._history.maxlen

        return {
            "tree_root_keys": root_keys,
            "subscriptions_total": subs_count,
            "history_size": history_len,
            "history_capacity": history_cap,
        }
