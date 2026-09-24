# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 1.3a (ADR-RTR-012): SocketChannel без head-of-line.

Что может сломаться в ЭТОМ механизме (read-поток разбирает строку и привязывает
сессию синхронно, on_inbound уходит в daemon-поток под семафором на соединение):

  * обработчик доживает дольше своего соединения — его ответ не должен уйти в
    закрытый сокет, а сам поток обязан закончиться;
  * read-поток висит на ПОЛНОМ семафоре — close() не должен ждать освобождения
    слотов, а поток — остаться жить навсегда;
  * потолок in-flight — это backpressure одного соединения, а не общего канала:
    девятый запрос на A ждёт, B отвечает сразу;
  * oversize-строка, пришедшая многими recv-чанками, не копится в буфере;
  * снятие с учёта (``_unregister_clients``) гоняется из нескольких потоков —
    каждая сессия достаётся ровно одному вызову (отсюда ровно одно оповещение);
  * сбой записи (медленный читатель) закрывает сессию тем же порядком, что выход
    read-loop, а второй отправитель к зависшему сокету не ждёт ещё раз.

Каждый блокирующий вызов — в daemon-потоке с join-дедлайном: зависший тест хуже
упавшего.
"""

from __future__ import annotations

import socket
import threading
import time
import tracemalloc
from typing import Any, Callable, Dict, List

from ..channels.socket_channel import _MAX_INFLIGHT_PER_CONNECTION, SocketChannel


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _connect(ch: SocketChannel, n_expected: int) -> socket.socket:
    c = socket.create_connection((ch.host, ch.port), timeout=2.0)
    assert _wait(lambda: ch.get_info()["clients"] >= n_expected), "сервер не принял соединение"
    return c


def _run_with_deadline(fn: Callable[[], Any], deadline: float) -> float:
    """fn() в daemon-потоке; вернуть длительность, упасть, если не уложилась."""
    box: Dict[str, Any] = {}

    def _run() -> None:
        t0 = time.monotonic()
        fn()
        box["elapsed"] = time.monotonic() - t0

    t = threading.Thread(target=_run, daemon=True, name="test-deadline")
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов не завершился за {deadline}с — зависание"
    return box["elapsed"]


def _recv_line(sock: socket.socket, timeout: float = 1.0) -> bytes:
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return buf.split(b"\n", 1)[0]


def _read_threads_alive(name: str) -> int:
    return sum(1 for t in threading.enumerate() if t.name == f"socket-ch-read-{name}" and t.is_alive())


def test_cap_constant_is_eight() -> None:
    """Литерал потолка из дизайна — отдельно от механики (тест ниже от него зависит)."""
    assert _MAX_INFLIGHT_PER_CONNECTION == 8


def test_worker_outliving_its_connection_does_not_write_and_ends() -> None:
    """Соединение закрыто, пока обработчик работает: ответ не уходит, поток кончается."""
    release = threading.Event()
    results: List[Dict[str, Any]] = []
    finished = threading.Event()
    closed_sessions: List[str] = []

    def on_inbound(msg: Dict[str, Any]) -> None:
        release.wait(3.0)
        results.append(ch.send({"type": "response", "session": msg["session"], "request_id": msg["request_id"]}))
        finished.set()

    ch = SocketChannel(
        "hz1", port=0, on_inbound=on_inbound, session_isolation=True, on_session_closed=closed_sessions.append
    )
    assert ch.start() is True
    try:
        c = _connect(ch, 1)
        c.sendall(b'{"session":"s1","request_id":"r1"}\n')
        assert _wait(lambda: ch.get_info()["sessions"] == 1), "сессия не привязана до передачи обработчику"
        c.close()
        assert _wait(lambda: ch.get_info()["clients"] == 0), "read-поток не заметил разрыв, пока обработчик занят"
        tx_before = ch.get_info()["tx"]
        release.set()
        assert finished.wait(2.0), "обработчик не закончился после разрыва своего соединения"
        assert results[0]["status"] == "error", f"ответ ушёл в закрытое соединение: {results[0]!r}"
        assert results[0]["reason"] == "session not connected"
        assert ch.get_info()["tx"] == tx_before
        # Оповещение — после возврата обработчика (порядок закрытия), не мгновенно.
        assert _wait(lambda: closed_sessions == ["s1"]), f"on_session_closed: {closed_sessions!r}"
    finally:
        release.set()
        ch.close()


def test_close_with_full_semaphore_returns_and_read_thread_exits() -> None:
    """Все 8 слотов заняты, девятая строка ждёт слот: close() не висит, read-поток выходит."""
    release = threading.Event()
    started: List[int] = []

    def on_inbound(msg: Dict[str, Any]) -> None:
        started.append(msg["i"])
        release.wait(5.0)

    name = "hz2"
    ch = SocketChannel(name, port=0, on_inbound=on_inbound)
    assert ch.start() is True
    try:
        c = _connect(ch, 1)
        cap = _MAX_INFLIGHT_PER_CONNECTION
        c.sendall(b"".join(b'{"i":%d}\n' % i for i in range(cap + 3)))
        assert _wait(lambda: len(started) == cap), f"в работе {len(started)}, ожидалось {cap}"
        time.sleep(0.2)
        assert len(started) == cap, "потолок in-flight пробит"
        assert _read_threads_alive(name) == 1

        elapsed = _run_with_deadline(ch.close, deadline=1.5)
        assert elapsed < 1.0, f"close() занял {elapsed:.3f}с при полном семафоре"
        assert _wait(lambda: _read_threads_alive(name) == 0, timeout=1.0), "read-поток висит на семафоре после close()"
        assert len(started) == cap, "после close() строки из очереди ушли в обработчик"
    finally:
        release.set()
        ch.close()


def test_ninth_request_waits_while_other_connection_is_served() -> None:
    """Backpressure — на соединение: 9-й на A ждёт слот, B отвечает сразу."""
    release = threading.Event()
    started: List[str] = []

    def on_inbound(msg: Dict[str, Any]) -> None:
        started.append(msg["id"])
        if msg["id"].startswith("a"):
            release.wait(5.0)
        ch.send({"type": "response", "request_id": msg["id"]})

    ch = SocketChannel("hz3", port=0, on_inbound=on_inbound)
    assert ch.start() is True
    try:
        a = _connect(ch, 1)
        b = _connect(ch, 2)
        cap = _MAX_INFLIGHT_PER_CONNECTION
        a.sendall(b"".join(b'{"id":"a%d"}\n' % i for i in range(cap + 1)))
        assert _wait(lambda: len(started) == cap)
        time.sleep(0.2)
        assert f"a{cap}" not in started, "девятый запрос A стартовал при занятых 8 слотах"

        t0 = time.monotonic()
        b.sendall(b'{"id":"b0"}\n')
        line = _recv_line(b, timeout=1.0)
        elapsed = time.monotonic() - t0
        assert b'"b0"' in line, f"B не получил ответ: {line!r}"
        assert elapsed < 0.5, f"B ждал {elapsed:.3f}с — потолок A задел соседнее соединение"

        release.set()
        assert _wait(lambda: f"a{cap}" in started), "девятый запрос A не стартовал после освобождения слотов"
    finally:
        release.set()
        ch.close()


def test_oversize_line_in_many_chunks_is_not_buffered() -> None:
    """2 МиБ без перевода строки при потолке 4 КиБ: память не растёт с длиной строки.

    Наблюдаемый эффект — пик аллокаций (tracemalloc видит все потоки), не имя
    внутреннего буфера. Бюджет: потолок + recv-чанк + запас на интерпретатор.
    """
    inbound: List[Dict[str, Any]] = []
    warnings: List[str] = []
    limit = 4096
    ch = SocketChannel("hz4", port=0, on_inbound=inbound.append, log_warning=warnings.append, max_line_bytes=limit)
    assert ch.start() is True
    try:
        c = _connect(ch, 1)
        piece = b"x" * 65536
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            base = tracemalloc.get_traced_memory()[0]

            def _send() -> None:
                for _ in range(32):  # 2 МиБ
                    c.sendall(piece)
                c.sendall(b'\n{"ok":true}\n')

            _run_with_deadline(_send, deadline=10.0)
            assert _wait(lambda: len(inbound) == 1, timeout=5.0), "строка после oversize не доставлена"
            peak = tracemalloc.get_traced_memory()[1] - base
        finally:
            tracemalloc.stop()
        assert inbound == [{"ok": True}]
        assert len(warnings) == 1, f"ожидался один WARNING на oversize-строку, получено {warnings!r}"
        assert peak < 256 * 1024, f"пик аллокаций {peak} байт при потолке {limit} — oversize-строка копится"
    finally:
        ch.close()


def test_concurrent_unregister_hands_session_to_exactly_one_call() -> None:
    """Снятие с учёта из 8 потоков сразу: сессия достаётся ровно одному вызову."""
    ch = SocketChannel("hz5", port=0)
    assert ch.start() is True
    try:
        c = _connect(ch, 1)
        c.sendall(b'{"session":"s9"}\n')
        assert _wait(lambda: ch.get_info()["sessions"] == 1)
        with ch._clients_lock:
            server_sock = ch._clients[0]
        barrier = threading.Barrier(8)
        got: List[str] = []
        got_lock = threading.Lock()

        def _unregister() -> None:
            barrier.wait(2.0)
            sids = ch._unregister_clients([server_sock])
            with got_lock:
                got.extend(sids)

        threads = [threading.Thread(target=_unregister, daemon=True) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3.0)
            assert not t.is_alive()
        assert got == ["s9"], f"сессия досталась {len(got)} вызовам: {got!r}"
        assert ch.get_info()["clients"] == 0
        c.close()
    finally:
        ch.close()


def test_session_bound_before_handler_on_first_line() -> None:
    """Самая первая строка соединения несёт session: обработчик сразу отвечает адресно.

    Привязка обязана случиться в read-потоке ДО передачи сообщения обработчику —
    иначе ответ первой же команды уходит в «session not connected».
    """
    results: List[Dict[str, Any]] = []

    def on_inbound(msg: Dict[str, Any]) -> None:
        results.append(ch.send({"type": "response", "session": msg["session"], "request_id": "r1"}))

    ch = SocketChannel("hz6", port=0, on_inbound=on_inbound, session_isolation=True)
    assert ch.start() is True
    try:
        c = _connect(ch, 1)
        c.sendall(b'{"session":"first","request_id":"r1"}\n')
        line = _recv_line(c, timeout=1.0)
        assert b'"r1"' in line, f"ответ на первую строку не дошёл: {line!r}, send → {results!r}"
        c.close()
    finally:
        ch.close()


def test_session_closed_fires_after_last_handler_of_the_session() -> None:
    """Порядок: on_session_closed — только ПОСЛЕ возврата последнего обработчика сессии.

    Иначе наблюдатель обработчика (note_point) отработает после forget_session и
    оставит намерение подписки мёртвой сессии (класс Н3-1).
    """
    release = threading.Event()
    order: List[str] = []

    def on_inbound(msg: Dict[str, Any]) -> None:
        release.wait(3.0)
        order.append("handler_done")

    ch = SocketChannel(
        "hz7", port=0, on_inbound=on_inbound, on_session_closed=lambda sid: order.append(f"closed:{sid}")
    )
    assert ch.start() is True
    try:
        c = _connect(ch, 1)
        c.sendall(b'{"session":"s7"}\n')
        assert _wait(lambda: ch.get_info()["sessions"] == 1)
        c.close()
        time.sleep(0.3)  # read-поток давно увидел EOF
        assert order == [], f"сессия закрыта при живом обработчике: {order!r}"
        release.set()
        assert _wait(lambda: len(order) == 2), f"порядок не завершился: {order!r}"
        time.sleep(0.1)
        assert order == ["handler_done", "closed:s7"], f"неверный порядок: {order!r}"
    finally:
        release.set()
        ch.close()


def _stuck_client(ch: SocketChannel, n_expected: int) -> socket.socket:
    """Клиент, который не читает: маленький приёмный буфер, recv не зовётся никогда."""
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    c.connect((ch.host, ch.port))
    assert _wait(lambda: ch.get_info()["clients"] >= n_expected), "сервер не принял соединение"
    return c


def test_session_closed_after_handler_on_write_failure_path() -> None:
    """Сбой записи (медленный читатель) не закрывает сессию раньше её обработчика.

    Путь, которым отбрасывается медленный клиент: sendall упирается в таймаут. Снятие
    сессии обязано идти тем же порядком, что на выходе read-loop, — после handler_done.
    """
    release = threading.Event()
    order: List[str] = []
    ch = SocketChannel(
        "hz8",
        port=0,
        on_inbound=lambda msg: (release.wait(3.0), order.append("handler_done")),
        on_session_closed=lambda sid: order.append(f"closed:{sid}"),
        session_isolation=True,
        log_warning=lambda _m: None,
    )
    assert ch.start() is True
    try:
        c = _stuck_client(ch, 1)
        c.sendall(b'{"session":"s8"}\n')
        assert _wait(lambda: ch.get_info()["sessions"] == 1)
        payload = "x" * 262144

        def _push_until_error() -> None:
            for _ in range(200):
                if ch.send({"session": "s8", "payload": payload})["status"] == "error":
                    return

        _run_with_deadline(_push_until_error, deadline=5.0)
        time.sleep(0.3)
        assert order == [], f"сессия закрыта сбоем записи при живом обработчике: {order!r}"
        release.set()
        assert _wait(lambda: len(order) == 2, timeout=3.0), f"порядок не завершился: {order!r}"
        assert order == ["handler_done", "closed:s8"], f"неверный порядок: {order!r}"
        c.close()
    finally:
        release.set()
        ch.close()


def test_second_sender_to_stuck_socket_does_not_wait_again() -> None:
    """Два отправителя к одному зависшему сокету: второй не сидит свои 0.5 с, EBADF нет."""
    warnings: List[str] = []
    ch = SocketChannel("hz9", port=0, log_warning=warnings.append)
    assert ch.start() is True
    try:
        c = _stuck_client(ch, 1)
        payload = "x" * (4 * 1024 * 1024)
        ends: Dict[str, float] = {}
        barrier = threading.Barrier(2)

        def _sender(tag: str) -> None:
            barrier.wait(2.0)
            if tag == "second":
                time.sleep(0.05)  # первый гарантированно внутри sendall
            ch.send({"type": "event", "payload": payload})
            ends[tag] = time.monotonic()

        threads = [threading.Thread(target=_sender, args=(t,), daemon=True) for t in ("first", "second")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3.0)
            assert not t.is_alive(), "отправитель завис"
        gap = ends["second"] - ends["first"]
        assert gap < 0.2, f"второй отправитель ждал ещё {gap:.3f}с после таймаута первого"
        time.sleep(0.2)
        ebadf = [w for w in warnings if "Bad file descriptor" in w]
        assert ebadf == [], f"запись в закрытый сокет: {ebadf!r}"
        assert len(warnings) == 1, f"ожидался один WARNING на отброс клиента: {warnings!r}"
        c.close()
    finally:
        ch.close()
