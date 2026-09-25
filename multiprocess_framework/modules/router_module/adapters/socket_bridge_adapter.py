# -*- coding: utf-8 -*-
"""
SocketBridgeAdapter — серверная сторона request-response для SocketChannel.

Связывает прочитанное сокетом router-сообщение с RouterManager и отправляет
ответ обратно через тот же router (channel=-маршрутизация). Симметрия
`CommandSender`: driver = клиент, этот адаптер = сервер. Сам сокет не трогает —
весь I/O делает SocketChannel, вся доставка внутрь системы и обратно — router.

Поток (каждая стрелка — RouterManager, см. P2 дизайн §4–5):
    SocketChannel.read-loop → on_inbound(msg)
        result = router.request(msg, timeout)          # внутрь системы и ждём ответ
        router.send({type:response, channel:<name>, request_id, result})
                                                        # ответ резолвится в SocketChannel.send

Контракт P0.5: request() здесь крутится в read-потоке сокета, а резолвится в
system-цикле хоста (другой поток) → дедлок-контракт соблюдён даром.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from ..._fallback import FallbackLogger

# A-4 (bug-hunt 2026-07-20 §5): в модуле не было ни логов, ни счётчиков — потеря
# ответа driver'у проходила безмолвно. FallbackLogger — стандартный паттерн
# проекта для utility-классов без DI (см. multiprocess_framework/modules/_fallback.py).
_logger = FallbackLogger(__name__)


class SocketBridgeAdapter:
    """Колбэк on_inbound для SocketChannel: dict → router.request → router.send.

    Args:
        router: RouterManager хоста (нужны методы request() и send()).
        channel_name: имя SocketChannel (адрес для channel=-маршрутизации ответа).
        default_timeout: таймаут request(), если в сообщении нет поля "timeout".
        on_request: наблюдатель ``(msg, sid, result)`` — зовётся ПОСЛЕ
            router.request, до отправки ответа (4.4). Адаптер о командах не знает:
            что из запроса запомнить, решает хост. Исключение наблюдателя гасится
            и считается в ``get_stats()["observer_errors"]`` — ответ driver'у
            уходит всё равно.
    """

    def __init__(
        self,
        router: Any,
        channel_name: str,
        default_timeout: float = 5.0,
        session_isolation: bool = False,
        on_request: Optional[Callable[[Dict[str, Any], Optional[str], Any], None]] = None,
    ) -> None:
        self._router = router
        self._channel_name = channel_name
        self._default_timeout = default_timeout
        # D.1: при True возвращаем обратный адрес session в response (SocketChannel
        # адресует его одному сокету). pop(session) из msg — ВСЕГДА, вне флага.
        self._session_isolation = session_isolation
        # A-4: число ответов, потерянных при router.send(response) (см. on_inbound).
        # Раньше терялось молча — MCP-инструменты висели до таймаута, пользователь
        # повторял уже применённую команду (register_snapshot/record_start — двойное
        # применение). Публичный счётчик — get_stats().
        # Счётчики инкрементятся из нескольких потоков-обработчиков SocketChannel
        # (ADR-RTR-012) — один лок на оба счётчика, инкремент и чтение под ним.
        self._stats_lock = threading.Lock()
        self._lost_responses = 0
        self._on_request = on_request
        self._observer_errors = 0

    def on_inbound(self, msg: Dict[str, Any]) -> None:
        """Обработать входящее сообщение от driver'а и отправить ответ.

        msg уже router-формы (билдер протокола на стороне driver'а), reshaping
        не требуется. Ошибки request() превращаются в error-ответ, не роняют
        read-loop сокета.
        """
        corr: Optional[str] = msg.get("request_id")
        # session (D.1) снимаем ВСЕГДА, до router.request — поле изоляции не должно
        # течь во внутренние handler'ы (защита маршрутизации; при OFF команда
        # обрабатывается идентично прежней). Обратный адрес вернём в response только
        # при включённой изоляции — иначе wire бит-в-бит прежним.
        sid: Optional[str] = msg.pop("session", None)
        timeout = msg.get("timeout", self._default_timeout)

        # Универсальность драйвера: ответ handler'а должен вернуться ХОСТУ (где
        # живёт pending-слот request()), а не во `sender` драйвера — внешний driver
        # не процесс с очередью, поэтому reply_to_request, адресуя ответ в sender,
        # терял бы его → request() ловит timeout. Подставляем reply_to=<имя хоста>,
        # чтобы ответ доехал в system-очередь хоста и резолвил pending. setdefault —
        # не затираем явный reply_to, если driver задал свой.
        host = getattr(getattr(self._router, "process", None), "name", None) or getattr(self._router, "router_id", None)
        if host:
            msg.setdefault("reply_to", host)

        try:
            result = self._router.request(msg, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — граница: любая ошибка → error-ответ driver'у
            result = {"success": False, "error": str(exc)}

        if self._on_request is not None:
            # msg уже без "session" (снят выше) — sid идёт отдельным аргументом.
            try:
                self._on_request(msg, sid, result)
            except Exception as exc:  # noqa: BLE001 — наблюдатель не важнее ответа
                with self._stats_lock:
                    self._observer_errors += 1
                    total = self._observer_errors
                _logger.error(
                    "SocketBridgeAdapter.on_inbound: наблюдатель on_request упал "
                    "(request_id=%s, channel=%s): %s [всего: %d]",
                    corr,
                    self._channel_name,
                    exc,
                    total,
                )

        # Ответ driver'у через router (channel=-маршрутизация → SocketChannel.send).
        # Адаптер сокет напрямую НЕ трогает.
        response: Dict[str, Any] = {
            "type": "response",
            "channel": self._channel_name,
            "request_id": corr,
            "result": result,
        }
        if self._session_isolation and sid is not None:
            # Обратный адрес доставки — SocketChannel.send резолвит его в один сокет.
            response["session"] = sid
        try:
            self._router.send(response)
        except Exception as exc:  # noqa: BLE001 — не роняем read-loop, если ответ не ушёл (best-effort)
            # A-4: раньше здесь было голое `pass` — потеря ответа проходила без следа.
            # Не re-raise (симметрично прежнему best-effort), но видимо: счётчик + лог.
            with self._stats_lock:
                self._lost_responses += 1
                lost = self._lost_responses
            _logger.error(
                "SocketBridgeAdapter.on_inbound: ответ driver'у не отправлен "
                "(request_id=%s, channel=%s): %s [потеряно всего: %d]",
                corr,
                self._channel_name,
                exc,
                lost,
            )

    def get_stats(self) -> Dict[str, Any]:
        """A-4: потерянные ответы (router.send упал); 4.4: упавшие наблюдатели on_request."""
        with self._stats_lock:
            return {"lost_responses": self._lost_responses, "observer_errors": self._observer_errors}
