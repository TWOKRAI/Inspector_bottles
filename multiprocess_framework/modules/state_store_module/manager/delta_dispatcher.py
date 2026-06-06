"""delta_dispatcher.py — Рассылка дельт подписчикам через IPC.

DeltaDispatcher получает список дельт, матчит их по подпискам,
группирует по subscriber (с дедупликацией!) и отправляет
каждому подписчику одно IPC-сообщение state.changed.
"""

from __future__ import annotations

from typing import Any

from ..core.delta import Delta
from ..core.subscription_manager import SubscriptionManager
from ..interfaces import IRouter


class DeltaDispatcher:
    """Рассылка дельт подписчикам через IPC.

    Batch-режим: собирает дельты из Transaction, отправляет одним сообщением.
    Дедупликация по subscriber: если процесс подписан на cameras.0.* и cameras.**,
    он получает каждую дельту ОДИН раз.
    """

    def __init__(
        self,
        subscription_mgr: SubscriptionManager,
        router: IRouter | None = None,
        sender_name: str = "StateStore",
        logger: Any = None,
    ) -> None:
        """
        Args:
            subscription_mgr: менеджер подписок для матчинга дельт.
            router: реализация IRouter для отправки IPC-сообщений (None для тестов).
            sender_name: имя отправителя в IPC-сообщениях.
            logger: ObservableMixin-совместимый объект с методами _log_*.
        """
        self._subs = subscription_mgr
        self._router = router
        self._sender = sender_name
        self._log = logger

    def dispatch(self, deltas: list[Delta]) -> dict[str, int]:
        """Сгруппировать дельты по подписчику, отправить state.changed.

        Логика:
        1. Для каждой delta -> subs.match(delta) -> list[Subscription]
        2. Группировка: {subscriber: list[Delta]} с дедупликацией
           (каждая delta у subscriber встречается не более одного раза)
        3. Для каждого subscriber -> отправить одно IPC-сообщение state.changed

        Args:
            deltas: список дельт для рассылки.

        Returns:
            {subscriber: количество_дельт} — статистика рассылки.
        """
        if not deltas:
            return {}

        # Группировка: subscriber -> список уникальных дельт
        # Для дедупликации используем set индексов дельт по subscriber
        subscriber_delta_indices: dict[str, set] = {}
        subscriber_deltas: dict[str, list[Delta]] = {}

        for idx, delta in enumerate(deltas):
            matched_subs = self._subs.match(delta)
            for sub in matched_subs:
                name = sub.subscriber
                # Дедупликация: если эта delta (по индексу) уже добавлена — пропускаем
                if name not in subscriber_delta_indices:
                    subscriber_delta_indices[name] = set()
                    subscriber_deltas[name] = []
                if idx not in subscriber_delta_indices[name]:
                    subscriber_delta_indices[name].add(idx)
                    subscriber_deltas[name].append(delta)

        # Отправка IPC-сообщений
        stats: dict[str, int] = {}
        for subscriber, sub_deltas in subscriber_deltas.items():
            stats[subscriber] = len(sub_deltas)
            self._send_state_changed(subscriber, sub_deltas)

        return stats

    def dispatch_single(self, delta: Delta) -> dict[str, int]:
        """Обёртка для одной дельты.

        Args:
            delta: единственная дельта для рассылки.

        Returns:
            {subscriber: количество_дельт} — статистика рассылки.
        """
        return self.dispatch([delta])

    def _send_state_changed(self, subscriber: str, deltas: list[Delta]) -> None:
        """Отправить state.changed сообщение подписчику.

        При router=None — только логирование (для тестов).

        Args:
            subscriber: имя процесса-подписчика.
            deltas: список дельт для отправки.
        """
        message = {
            "type": "event",
            "sender": self._sender,
            "targets": [subscriber],
            # queue_type="system": доставка в {subscriber}_system, который опрашивает
            # штатный message_processor подписчика — event_dispatcher синхронно
            # вызовет handler state.changed при опросе. См. U1-fallback в
            # RouterManager._deliver_by_targets (доставка по targets через queue_registry).
            "queue_type": "system",
            "command": "state.changed",
            "data": {
                "deltas": [d.to_dict() for d in deltas],
            },
        }

        if self._router is not None:
            try:
                self._router.send_async(message, priority="normal")
            except Exception as exc:
                if self._log is not None:
                    self._log._log_error(f"Ошибка отправки state.changed подписчику '{subscriber}': {exc}")
        else:
            if self._log is not None:
                self._log._log_debug(
                    f"Рассылка state.changed для '{subscriber}': {len(deltas)} дельт (router=None, пропуск)"
                )
