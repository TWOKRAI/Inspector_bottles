# -*- coding: utf-8 -*-
"""RouterPushChannel — sink, который пушит LogRecord через RouterManager (Ф1 Task 1.5).

Реализация якоря ADR-CRM-006 п.2 (SocketChannel-push): ``IChannel.write(record)``
не пишет в файл, а отправляет запись адресным router-пушем целевому подписчику
(например внешнему ``backend_ctl``). Dict at Boundary — наружу едет чистый dict,
БЕЗ прямого доступа к SHM (feedback_no_shm_hacks).

Маршрут доставки — тот же, что у ``state.changed`` (DeltaDispatcher) и мост 1.1b
(``RouterManager._deliver_by_targets``): ``targets=[subscriber]`` + ``queue_type="system"``.
Если у подписчика нет очереди (он не процесс, а внешний сокет-клиент), но
зарегистрирован канал того же имени (SocketChannel ``backend_ctl``) — доставка идёт
через канал во внешний driver. Живой router обязателен → канал создаётся в рантайме
командой ``log.tail.subscribe`` (не через config-фабрику: ссылку на router в конфиг
не положить).

Фильтрация по уровню НЕ здесь: канал пушит всё, что ему дали. Порог ``level ≥ X``
держит tap на стороне LoggerManager (``add_log_tap(min_level=...)``) — так канал
остаётся тонким и переиспользуемым.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...channel_routing_module.interfaces import IChannel


class RouterPushChannel(IChannel):
    """Sink, пушащий записи через RouterManager адресно подписчику.

    Args:
        name: уникальное имя канала (для реестра tap'ов / диагностики).
        router: RouterManager с ``send_async(dict, priority)`` — живой роутер процесса.
        subscriber: имя-адрес получателя (``targets=[subscriber]``), напр. "backend_ctl".
        sender: имя отправителя в сообщении (обычно имя процесса-источника).
        command: значение поля ``command`` пуша (по умолчанию "log.record").
    """

    def __init__(
        self,
        name: str,
        *,
        router: Any,
        subscriber: str,
        sender: str = "",
        command: str = "log.record",
    ) -> None:
        self._name = name
        self._router = router
        self._subscriber = subscriber
        self._sender = sender or subscriber
        self._command = command

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "router_push"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить запись адресным router-пушем подписчику (fire-and-forget).

        Форма сообщения зеркалит ``state.changed`` (DeltaDispatcher._send_state_changed):
        ``type=event`` + ``targets=[subscriber]`` + ``queue_type=system`` → мост 1.1b.
        Ошибки глотаются (лог не должен падать/тормозить из-за проблем доставки).
        """
        if self._router is None:
            return {"status": "error", "channel": self._name, "reason": "router=None"}
        message = {
            "type": "event",
            "sender": self._sender,
            "targets": [self._subscriber],
            "queue_type": "system",
            "command": self._command,
            "data": {"process": self._sender, "record": data},
        }
        try:
            self._router.send_async(message, priority="normal")
            return {"status": "success", "channel": self._name}
        except Exception as exc:  # noqa: BLE001 — доставка лога best-effort
            return {"status": "error", "channel": self._name, "reason": str(exc)}

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "type": self.channel_type,
            "active": self._router is not None,
            "subscriber": self._subscriber,
            "command": self._command,
        }
