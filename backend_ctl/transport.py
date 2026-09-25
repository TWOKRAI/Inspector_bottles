# -*- coding: utf-8 -*-
"""transport.py — TCP-транспорт driver'а: тонкий шим над ``SocketClient`` фреймворка.

Wire-клиент (сокет, reader-поток, request-response по ``request_id``, карантин поздних
ответов, thread-safe ``close()``) переехал в
``multiprocess_framework.modules.router_module.channels.socket_client.SocketClient``
(gui-service Task 1.2): им же пользуется внешний GUI. Здесь остаются только хуки,
которые делают поведение driver'а бит-в-бит прежним:

* разрыв соединения поднимает :class:`BackendUnavailable` (по нему ``call_tool`` зовёт
  ``session.reset()`` и реконнектится с replay'ем durable-подписок);
* push-сообщения уходят в событийный канал через ``self._emit_event``
  (``_EventChannelMixin``), а не в push-слушатели клиента;
* ``close()`` гасит watch-контур (``self._watch``) и будит ожидающих событийного
  hub'а (``self._hub``); разрыв тоже будит hub;
* текст разрыва и guard'а дедлока — actionable для агента.

Поля транспорта хост (`BackendDriver`) по-прежнему заводит сам в ``__init__``:
``_sock``/``_reader``/``_running``/``_pending``/``_pending_lock``/``_write_lock``/
``_timed_out``/``_late_replies`` + endpoint (``_host``/``_port``/``_reply_to``/
``_default_timeout``/``_sender``/``_session``/``_subscriber``/``_conn_lost*``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend_ctl.mcp_errors import BackendUnavailable
from multiprocess_framework.modules.router_module.channels.socket_client import (
    _SERVER_MARGIN_SEC,
    _TIMED_OUT_TTL_SEC,
    SocketClient,
    _Pending,
)

# Task 1.3: enforcement дедлок-конвенции «не звать request() из reader-потока». Текст
# называет ПРАВИЛЬНЫЙ паттерн, а не только запрет: подписчик event-hub'а (колбэк
# subscribe()) исполняется синхронно в reader-потоке (контракт events.py).
_READER_THREAD_GUARD_ERROR: str = (
    "request() позван из reader-потока — дедлок: этот же поток должен доставить ответ, "
    "а вызов блокируется в ожидании его самого. Так нельзя звать request() (и обёртки "
    "команд поверх него) из колбэка subscribe()/слушателя событий. Правильный паттерн: "
    "слушатель кладёт намерение (например, имя процесса) в очередь (queue.Queue) и "
    "немедленно возвращается, а отдельный applier-поток разбирает очередь и уже там, "
    "на безопасном потоке, зовёт request(). Так был устроен контур автоподписки в "
    "backend_ctl/watch.py — до Task 5.11.h, где его сняли целиком: переподписку "
    "делает брокер на оркестраторе, и звать request() из reader-потока стало незачем."
)


class _TransportMixin(SocketClient):
    """TCP-клиент driver'а: ``SocketClient`` + хуки событийного канала и watch."""

    _lost_exc = BackendUnavailable
    _reader_thread_name = "backend-ctl-reader"
    _reader_guard_error = _READER_THREAD_GUARD_ERROR

    def _handle_push(self, msg: Dict[str, Any]) -> None:
        # Push (без reply / поздний ответ никто не ждёт) → событийный канал driver'а.
        self._emit_event(msg)

    def _on_closed(self) -> None:
        # Реконнект зовёт close() (DriverSession.reset): профиль watch не должен считаться
        # активным на закрытом сокете; ожидающие events(timeout) — проснуться.
        self._watch.stop()
        self._hub.wake()

    def _on_conn_lost(self) -> None:
        # Поток событий оборван — разбудить блокирующих в events(timeout).
        self._hub.wake()

    def _conn_lost_message(self, *, request_id: Optional[str] = None) -> str:
        """Actionable-текст смерти соединения (единый для всех точек подъёма)."""
        reason = getattr(self, "_conn_lost_reason", "") or "соединение оборвано"
        tail = f" (request_id={request_id})" if request_id else ""
        return (
            f"соединение с бэкендом на {self._host}:{self._port} оборвано: {reason}{tail}. "
            "Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль "
            "восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1."
        )


__all__ = [
    "_TransportMixin",
    "_Pending",
    "_READER_THREAD_GUARD_ERROR",
    "_SERVER_MARGIN_SEC",
    "_TIMED_OUT_TTL_SEC",
]
