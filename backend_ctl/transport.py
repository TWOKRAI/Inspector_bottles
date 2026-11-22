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
* текст разрыва и guard'а дедлока — actionable для агента;
* токен рукопожатия (Task 0.12a): по умолчанию читается из файла порта
  (``socket_auth.file_token_provider``) на каждом ``connect``; нет файла — ``hello`` не
  шлётся. Отказ хоста — :class:`BackendUnavailable` с путём файла в тексте (без токена).

Поля транспорта хост (`BackendDriver`) по-прежнему заводит сам в ``__init__``:
``_sock``/``_reader``/``_running``/``_pending``/``_pending_lock``/``_write_lock``/
``_timed_out``/``_late_replies`` + endpoint (``_host``/``_port``/``_reply_to``/
``_default_timeout``/``_sender``/``_session``/``_subscriber``/``_conn_lost*``).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Dict, Optional

from backend_ctl.mcp_errors import BackendUnavailable
from multiprocess_framework.modules.router_module.channels.socket_auth import (
    file_token_provider,
    resolve_token_path,
)
from multiprocess_framework.modules.router_module.channels.socket_client import (
    _SERVER_MARGIN_SEC,
    _TIMED_OUT_TTL_SEC,
    SocketAuthError,
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


class TokenRejected(BackendUnavailable, SocketAuthError):
    """Хост отказал в ``hello``: токен из файла не подошёл (Task 0.12a).

    Наследник обоих: для MCP — :class:`BackendUnavailable` (текст для агента), для
    ретрая ``except OSError`` (``harness``) — :class:`SocketAuthError` (``OSError``).
    Текст — ``token rejected: <путь файла>``; токен в текст не попадает.
    """


class TokenFileMissing(BackendUnavailable):
    """Хост требует токен, а файла токена нет: команда до хоста не дошла (Task 0.12a, ревью).

    Отдельный подтип: ``driver.system_shutdown`` ловит :class:`BackendUnavailable` как «PM
    закрыл сокет» (``pm_gone``) и этот подтип пробрасывает. Текст — ``token file not found:
    <путь файла>``.
    """


class _TransportMixin(SocketClient):
    """TCP-клиент driver'а: ``SocketClient`` + хуки событийного канала и watch."""

    _lost_exc = BackendUnavailable
    _reader_thread_name = "backend-ctl-reader"
    _reader_guard_error = _READER_THREAD_GUARD_ERROR
    # Явный провайдер (параметр ``SocketClient.__init__``) — главнее файлового. Шим
    # драйвера ``__init__`` базы не зовёт: остаётся ``None`` → файловый провайдер.
    _explicit_token_provider: Callable[[], str | None] | None = None
    # Метка «хост ответил auth_required на этом соединении» (классовый дефолт: шим без
    # __init__ базы). После отказа хост закрывает соединение: все следующие подъёмы разрыва
    # называют файл токена, а не «соединение оборвано». Снимается успешным connect.
    _token_missing: bool = False

    @property
    def _token_provider(self) -> Callable[[], str | None]:
        """Провайдер токена для ``connect``: явный либо файл порта этого экземпляра.

        Файловый провайдер создаётся заново при каждом обращении (``connect`` читает
        свойство один раз на соединение) и сам файл не кэширует: реконнект после
        рестарта сервера читает новый токен. Нет файла — провайдер вернёт ``None``,
        ``hello`` не шлётся (открытый сервер работает как раньше).
        """
        explicit = self._explicit_token_provider
        if explicit is not None:
            return explicit
        return file_token_provider(self._port, os.environ)

    @_token_provider.setter
    def _token_provider(self, provider: Callable[[], str | None] | None) -> None:
        self._explicit_token_provider = provider

    def _token_path_text(self) -> str:
        return str(resolve_token_path(self._port, os.environ))

    def connect(self, timeout: float = 5.0) -> None:
        """``SocketClient.connect``; отказ в ``hello`` → :class:`TokenRejected` с путём файла."""
        try:
            super().connect(timeout)
        except SocketAuthError as exc:
            raise TokenRejected(f"token rejected: {self._token_path_text()}") from exc
        self._token_missing = False

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """``SocketClient.request``; ответ ``auth_required`` → :class:`TokenFileMissing`.

        ``auth_required`` приходит только до рукопожатия: ``hello`` не слали (слали бы —
        ``connect`` поднял бы :class:`TokenRejected`), значит файла токена нет. После
        отказа хост закрывает соединение: разрыв на помеченном соединении — тоже
        :class:`TokenFileMissing` с тем же текстом (пробы ``_await_ready`` его не съедают).
        """
        try:
            reply = super().request(message, timeout=timeout)
        except BackendUnavailable as exc:
            if self._token_missing and not isinstance(exc, TokenFileMissing):
                raise TokenFileMissing(self._token_missing_text()) from exc
            raise
        if isinstance(reply, dict) and reply.get("success") is False and reply.get("error") == "auth_required":
            self._token_missing = True
            raise TokenFileMissing(self._token_missing_text())
        return reply

    def _token_missing_text(self) -> str:
        return f"token file not found: {self._token_path_text()}"

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
        if self._token_missing:  # хост закрыл соединение после auth_required
            return self._token_missing_text()
        reason = getattr(self, "_conn_lost_reason", "") or "соединение оборвано"
        tail = f" (request_id={request_id})" if request_id else ""
        return (
            f"соединение с бэкендом на {self._host}:{self._port} оборвано: {reason}{tail}. "
            "Драйвер будет пересоздан на следующем вызове (durable-подписки и watch-профиль "
            "восстанавливаются автоматически); если бэкенд упал — подними его с BACKEND_CTL=1."
        )


__all__ = [
    "TokenFileMissing",
    "TokenRejected",
    "_TransportMixin",
    "_Pending",
    "_READER_THREAD_GUARD_ERROR",
    "_SERVER_MARGIN_SEC",
    "_TIMED_OUT_TTL_SEC",
]
