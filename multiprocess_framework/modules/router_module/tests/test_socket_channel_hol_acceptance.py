# -*- coding: utf-8 -*-
"""Независимая приёмка Task 1.3a: SocketChannel без head-of-line blocking (RED).

Написано ДО реализации по дизайну лида (см. plans/2026-09-22_gui-service/
phase-1-one-machine.md, раздел "Task 1.3a"). Слепота: видел только публичный
код ``socket_channel.py``/``socket_bridge_adapter.py`` и существующие тесты
``test_socket_channel.py`` / ``test_socket_bridge_on_request_acceptance.py`` —
не видел никакой реализации фикса (её ещё нет).

Дефект сегодня: ``_handle_line`` зовёт ``on_inbound(msg)`` ИНЛАЙН в read-потоке
соединения (``_read_loop`` → ``_handle_line`` синхронно, из того же цикла, что
читает следующую строку того же сокета) — медленный ``on_inbound`` держит
обработку следующей строки ТОГО ЖЕ соединения (HOL).

Контракт (литералы зафиксированы лидом, не выводятся из кода):
  - после фикса запросы ОДНОГО соединения могут исполняться конкурентно;
    ответы сопоставляются по ``request_id``, а не по FIFO-порядку;
  - новый kwarg конструктора ``max_line_bytes: int``, дефолт ровно 1_048_576;
    строка длиннее ``max_line_bytes`` дропается, пишется warning через
    инжектированный ``log_warning``, соединение остаётся живым, следующая
    нормальная строка доставляется;
  - session-адресация (`session` → сокет) по-прежнему происходит ДО
    on_inbound — не проверяем внутренности, только что адресный ответ
    доходит нужному клиенту (один тест в стиле существующих).
"""

from __future__ import annotations

import inspect
import json
import socket
import threading
import time
from typing import Any, Dict, List, Optional

import pytest

from ..channels.socket_channel import SocketChannel


# --- helpers (независимая копия, стиль как в test_socket_channel.py) ---


def _connect(ch: SocketChannel, timeout: float = 2.0) -> socket.socket:
    c = socket.create_connection((ch.host, ch.port), timeout=timeout)
    c.settimeout(timeout)
    deadline = time.time() + timeout
    while ch.get_info()["clients"] < 1 and time.time() < deadline:
        time.sleep(0.01)
    return c


def _connect_nth(ch: SocketChannel, n: int, timeout: float = 2.0) -> socket.socket:
    c = socket.create_connection((ch.host, ch.port), timeout=timeout)
    c.settimeout(timeout)
    deadline = time.time() + timeout
    while ch.get_info()["clients"] < n and time.time() < deadline:
        time.sleep(0.01)
    return c


def _wait(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _recv_line(sock: socket.socket, timeout: float = 2.0) -> Dict[str, Any]:
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    line, _, _ = buf.partition(b"\n")
    return json.loads(line.decode("utf-8"))


def _recv_matching(sock: socket.socket, want_request_id: str, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
    """Прочитать строки из ``sock`` до дедлайна ``timeout``, вернуть первую с
    ``request_id == want_request_id`` (порядок ответов НЕ гарантируется —
    контракт сопоставляет по id, не по FIFO). ``None`` — не дождались."""
    sock.settimeout(0.05)
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            obj = json.loads(line.decode("utf-8"))
            if obj.get("request_id") == want_request_id:
                return obj
    return None


def _make_slow_fast_channel(slow_event: threading.Event, wait_timeout: float = 3.0):
    """Канал, чей on_inbound блокируется на ``slow_event`` для request_id=="slow"
    и отвечает немедленно для всех прочих (эмулирует медленный обработчик за
    on_inbound — по дизайну лида допустимо вместо полного SocketBridgeAdapter)."""
    holder: Dict[str, SocketChannel] = {}

    def on_inbound(msg: Dict[str, Any]) -> None:
        rid = msg.get("request_id")
        ch = holder["ch"]
        if rid == "slow":
            released = slow_event.wait(timeout=wait_timeout)
            ch.send({"type": "response", "request_id": rid, "result": {"released": released}})
        else:
            ch.send({"type": "response", "request_id": rid, "result": {"ok": True}})

    ch = SocketChannel("backend_ctl", host="127.0.0.1", port=0, on_inbound=on_inbound)
    holder["ch"] = ch
    return ch


# --- HOL: одно соединение ---


def test_same_connection_fast_request_not_blocked_by_slow() -> None:
    """RED сегодня: on_inbound зовётся инлайн в read-потоке соединения, поэтому
    быстрый запрос той же сессии не может обогнать застрявший на Event медленный —
    read-loop не вернётся к разбору следующей строки, пока не выйдет из
    ``_handle_line`` медленного запроса."""
    slow_event = threading.Event()
    ch = _make_slow_fast_channel(slow_event, wait_timeout=3.0)
    assert ch.start() is True
    try:
        c = _connect(ch)
        c.sendall(b'{"request_id":"slow","type":"command","command":"slow"}\n')
        c.sendall(b'{"request_id":"fast","type":"command","command":"fast"}\n')

        t0 = time.monotonic()
        resp = _recv_matching(c, "fast", timeout=0.5)
        elapsed = time.monotonic() - t0

        slow_event.set()  # отпустить застрявший поток независимо от исхода (bounded by wait_timeout=3.0 anyway)

        assert resp is not None, f"быстрый ответ на ТОМ ЖЕ соединении не пришёл за 0.5s (elapsed={elapsed:.3f}s) — HOL"
        assert elapsed < 0.5, f"быстрый ответ пришёл, но за {elapsed:.3f}s (бюджет 0.5s) — HOL"
        c.close()
    finally:
        ch.close()


def test_other_connection_not_blocked_by_slow() -> None:
    """Базовая гарантия — ожидаю GREEN уже сегодня: у каждого соединения свой
    read-поток, поэтому медленный запрос на соединении A не должен блокировать
    независимое соединение B."""
    slow_event = threading.Event()
    ch = _make_slow_fast_channel(slow_event, wait_timeout=3.0)
    assert ch.start() is True
    try:
        c1 = _connect_nth(ch, 1)
        c1.sendall(b'{"request_id":"slow","type":"command","command":"slow"}\n')
        c2 = _connect_nth(ch, 2)
        c2.sendall(b'{"request_id":"fast","type":"command","command":"fast"}\n')

        t0 = time.monotonic()
        resp = _recv_matching(c2, "fast", timeout=0.5)
        elapsed = time.monotonic() - t0

        slow_event.set()

        assert resp is not None, f"быстрый ответ на ДРУГОМ соединении не пришёл за 0.5s (elapsed={elapsed:.3f}s)"
        assert elapsed < 0.5, f"быстрый ответ на другом соединении занял {elapsed:.3f}s (бюджет 0.5s)"
        c1.close()
        c2.close()
    finally:
        ch.close()


# --- медленный читатель не должен стопорить остальных ---


def test_slow_reader_does_not_stall_other_clients() -> None:
    """Клиент A подключается и никогда не читает; сервер broadcast'ит push'и,
    пока буфер A не заполнится. Ожидание: клиент B получает каждый push с
    задержкой < 1.0s, A отключается в течение 5.0s, пишется warning.

    Сегодняшнее поведение НЕИЗВЕСТНО заранее (ловушка (1) из брифа: сокеты
    клиентов имеют settimeout(0.5) на send/recv — sendall в A может упереться
    в 0.5s ТОТАЛ таймаут раньше, чем ожидалось) — фиксирую то, что реально
    замерено, а не подгоняю под гипотезу."""
    warnings: List[str] = []
    ch = SocketChannel("backend_ctl", host="127.0.0.1", port=0, log_warning=warnings.append)
    assert ch.start() is True
    try:
        a = _connect_nth(ch, 1)
        try:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        except OSError:
            pass
        b = _connect_nth(ch, 2)

        received_at: List[float] = []
        stop_reader = threading.Event()

        def _read_b() -> None:
            buf = b""
            b.settimeout(0.2)
            while not stop_reader.is_set():
                try:
                    chunk = b.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    _line, buf = buf.split(b"\n", 1)
                    received_at.append(time.monotonic())

        reader = threading.Thread(target=_read_b, name="test-read-b", daemon=True)
        reader.start()

        payload = "x" * (256 * 1024)  # 256 KiB на push — несколько МиБ суммарно (ловушка (2))
        max_call_elapsed = 0.0
        sent = 0
        deadline = time.monotonic() + 4.0  # ловушка (2): держать тест под ~5s
        try:
            while time.monotonic() < deadline and sent < 80:
                t0 = time.monotonic()
                ch.send({"type": "event", "command": "push", "seq": sent, "payload": payload})
                elapsed = time.monotonic() - t0
                max_call_elapsed = max(max_call_elapsed, elapsed)
                sent += 1
                if ch.get_info()["clients"] == 1:
                    break  # A уже отброшен — дальше гонять незачем
        finally:
            stop_reader.set()
            reader.join(timeout=1.0)

        a_dropped = _wait(lambda: ch.get_info()["clients"] == 1, timeout=5.0)
        assert a_dropped, f"клиент A не отброшен за 5.0s (clients={ch.get_info()['clients']}, отправлено={sent})"
        assert warnings, "не залогирован ни один warning при обрыве медленного читателя"
        assert received_at, "клиент B не получил НИ ОДНОГО push"
        assert max_call_elapsed < 1.0, (
            f"один из send()-вызовов держал ВСЕХ клиентов {max_call_elapsed:.3f}s (бюджет 1.0s на B), "
            f"отправлено={sent}, получено B={len(received_at)}"
        )

        a.close()
        b.close()
    finally:
        ch.close()


# --- max_line_bytes ---


def test_oversize_line_dropped_connection_alive() -> None:
    """RED сегодня: конструктор не знает kwarg ``max_line_bytes`` → TypeError."""
    inbound: List[Dict[str, Any]] = []
    warnings: List[str] = []
    ch = SocketChannel(
        "backend_ctl",
        host="127.0.0.1",
        port=0,
        on_inbound=inbound.append,
        log_warning=warnings.append,
        max_line_bytes=4096,
    )
    assert ch.start() is True
    try:
        c = _connect(ch)
        oversize = json.dumps({"request_id": "big", "data": "x" * (8 * 1024)}) + "\n"
        c.sendall(oversize.encode("utf-8"))
        time.sleep(0.3)  # дать read-loop'у шанс обработать/отбросить строку

        assert inbound == [], "on_inbound НЕ должен был позваться для строки > max_line_bytes"
        assert warnings, "должен быть залогирован warning при дропе oversize-строки"

        c.sendall(b'{"ok":true}\n')
        assert _wait(lambda: len(inbound) == 1), "нормальная строка ПОСЛЕ oversize должна доставиться"
        assert inbound[0] == {"ok": True}
        c.close()
    finally:
        ch.close()


def test_max_line_bytes_default_is_1_mib() -> None:
    """RED сегодня: параметра ``max_line_bytes`` нет в сигнатуре конструктора."""
    sig = inspect.signature(SocketChannel.__init__)
    assert "max_line_bytes" in sig.parameters, "конструктору не хватает kwarg max_line_bytes"
    assert sig.parameters["max_line_bytes"].default == 1_048_576, (
        f"дефолт max_line_bytes должен быть 1_048_576, получено {sig.parameters['max_line_bytes'].default!r}"
    )


# --- session-адресация не должна пострадать от фикса ---


def test_session_reply_still_reaches_its_client() -> None:
    """Ожидаю GREEN уже сегодня — существующая гарантия (D.1), пин в стиле
    существующих тестов, чтобы фикс HOL её не задел."""
    inbound: List[Dict[str, Any]] = []
    ch = SocketChannel("backend_ctl", host="127.0.0.1", port=0, on_inbound=inbound.append, session_isolation=True)
    assert ch.start() is True
    try:
        c1 = _connect_nth(ch, 1)
        c2 = _connect_nth(ch, 2)
        c1.sendall(b'{"session":"sid-1","type":"command","command":"ping"}\n')
        assert _wait(lambda: ch.get_info()["sessions"] == 1)

        res = ch.send({"type": "response", "session": "sid-1", "request_id": "r1", "result": {"ok": 1}})
        assert res["status"] == "success"
        assert res["clients"] == 1

        got = _recv_line(c1)
        assert got["request_id"] == "r1"

        c2.settimeout(0.3)
        with pytest.raises(socket.timeout):
            c2.recv(4096)  # чужой reply НЕ протёк

        c1.close()
        c2.close()
    finally:
        ch.close()
