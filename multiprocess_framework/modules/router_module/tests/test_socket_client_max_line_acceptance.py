# -*- coding: utf-8 -*-
"""Независимая приёмка Task 1.3a (Part B1): SocketClient без неограниченного `buf` (RED).

Написано ДО реализации по дизайну лида. Слепота: читал только
``socket_client.py`` (докстринги/сигнатуры) и ``test_socket_client.py``
(харнесс) — реализации фикса нет и не смотрел.

Дефект сегодня: ``_read_loop`` (~строка 584) копит ``buf`` без ограничения —
оверсайз-строка от сервера растит буфер клиента неограниченно.

Контракт (литералы фикса лида):
  - новый kwarg ``max_line_bytes: int``, дефолт ровно 16_777_216 (16 МиБ —
    ответы вроде state-поддерева/истории бывают большими; сервер держит 1 МиБ);
  - строка от сервера длиннее ``max_line_bytes`` дропается с WARNING на
    модульном логгере, соединение остаётся живым (``connection_lost`` не
    взводится), следующая нормальная строка доставляется;
  - запрос, чей ответ был дропнут по этой причине, НЕ висит — завершается
    СВОИМ клиентским таймаутом (``{"success": False, "error": "timeout"}``).

Харнесс — переиспользован из ``test_socket_client.py`` (реальный
``RouterManager`` + реальный ``SocketChannel(port=0)`` + реальный
``SocketBridgeAdapter``, как хост), как просил координатор.
"""

from __future__ import annotations

import inspect
import time

from ..channels.socket_client import SocketClient
from .test_socket_client import _call_with_deadline, _make_command_host, _wait


def test_client_max_line_bytes_default_is_16_mib() -> None:
    """RED сегодня: параметра ``max_line_bytes`` нет в сигнатуре конструктора."""
    sig = inspect.signature(SocketClient.__init__)
    assert "max_line_bytes" in sig.parameters, "конструктору SocketClient не хватает kwarg max_line_bytes"
    assert sig.parameters["max_line_bytes"].default == 16_777_216, (
        f"дефолт max_line_bytes должен быть 16_777_216, получено {sig.parameters['max_line_bytes'].default!r}"
    )


def test_client_oversize_line_dropped_connection_alive() -> None:
    """RED сегодня: TypeError на неизвестном kwarg ``max_line_bytes``."""
    host = _make_command_host({"ping": lambda msg: {"pong": True}})
    try:
        pushes: list = []
        client = SocketClient(
            host.host,
            host.port,
            sender="drv-oversize",
            max_line_bytes=4096,
            on_push=pushes.append,
        )
        client.connect()
        try:
            # Синхронизация: round trip гарантирует, что хост уже зарегистрировал
            # соединение — иначе push уходит в пустоту и pushes == [] вакуумно
            # (гонка accept, тот же класс, что 2561bd61).
            sync = _call_with_deadline(
                lambda: client.request({"type": "command", "command": "ping", "sender": "drv-oversize"}, timeout=2.0),
                timeout=3.0,
            )
            assert sync["success"] is True, f"синхронизирующий ping не прошёл: {sync!r}"
            # Оверсайз push (> 4096 байт) — должен быть дропнут молча для listener'а.
            host.push({"type": "event", "command": "big.push", "data": {"payload": "x" * 8192}})
            time.sleep(0.3)
            assert pushes == [], "on_push НЕ должен был позваться для oversize push-строки"

            # Соединение живо: нормальный push ПОСЛЕ oversize доставляется.
            host.push({"type": "event", "command": "small.push", "data": {"ok": True}})
            assert _wait(lambda: len(pushes) == 1), "нормальный push после oversize не дошёл — reader мёртв?"
            assert pushes[0]["command"] == "small.push"

            # Соединение живо: обычный request() после oversize по-прежнему проходит.
            res = _call_with_deadline(
                lambda: client.request({"type": "command", "command": "ping", "sender": "drv-oversize"}, timeout=2.0),
                timeout=3.0,
            )
            assert res["success"] is True
            assert res["result"] == {"pong": True}
        finally:
            client.close()
    finally:
        host.close()


def test_client_request_with_dropped_oversize_reply_ends_by_timeout() -> None:
    """RED сегодня: TypeError на неизвестном kwarg ``max_line_bytes``.

    Дизайн: ответ хоста на "big" превышает max_line_bytes=4096 клиента →
    строка дропается на чтении, pending-слот запроса никогда не резолвится
    ответом → request() обязан завершиться СВОИМ таймаутом (не зависнуть)."""
    host = _make_command_host({"big": lambda msg: {"blob": "x" * 8192}})
    try:
        client = SocketClient(host.host, host.port, sender="drv-timeout", max_line_bytes=4096)
        client.connect()
        try:
            t0 = time.monotonic()
            res = _call_with_deadline(
                lambda: client.request({"type": "command", "command": "big", "sender": "drv-timeout"}, timeout=1.5),
                timeout=4.0,
            )
            elapsed = time.monotonic() - t0
            assert res.get("success") is False
            assert res.get("error") == "timeout", f"ожидал явный клиентский timeout, получено: {res!r}"
            assert elapsed < 2.5, f"ответ пришёл за {elapsed:.3f}s — не похоже на честный клиентский таймаут (~1.5s)"
        finally:
            client.close()
    finally:
        host.close()
