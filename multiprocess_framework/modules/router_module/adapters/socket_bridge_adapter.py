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

from typing import Any, Dict, Optional


class SocketBridgeAdapter:
    """Колбэк on_inbound для SocketChannel: dict → router.request → router.send.

    Args:
        router: RouterManager хоста (нужны методы request() и send()).
        channel_name: имя SocketChannel (адрес для channel=-маршрутизации ответа).
        default_timeout: таймаут request(), если в сообщении нет поля "timeout".
    """

    def __init__(
        self,
        router: Any,
        channel_name: str,
        default_timeout: float = 5.0,
        session_isolation: bool = False,
    ) -> None:
        self._router = router
        self._channel_name = channel_name
        self._default_timeout = default_timeout
        # D.1: при True возвращаем обратный адрес session в response (SocketChannel
        # адресует его одному сокету). pop(session) из msg — ВСЕГДА, вне флага.
        self._session_isolation = session_isolation

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
        except Exception:  # noqa: BLE001 — не роняем read-loop, если ответ не ушёл (best-effort)
            pass
