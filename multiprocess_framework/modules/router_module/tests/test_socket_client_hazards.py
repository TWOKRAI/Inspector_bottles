# -*- coding: utf-8 -*-
"""Авторские hazard-тесты ``SocketClient`` (Task 1.2 GREEN, gui-service).

Что может сломаться именно в этом механизме, как он устроен:

* async-слоты живут в том же реестре ``_pending``, что и синхронные; их вынимают
  ТРИ стороны (ответ в ``_dispatch``, таймаут в ``_expire_slots``, ``close``/разрыв).
  Колбэк обязан позваться РОВНО один раз — даже если две стороны сходятся;
* ``send_nowait`` после разрыва должен поднять исключение, а не «молча записать» в
  мёртвый сокет (иначе GUI шлёт команды в пустоту без сигнала владельцу соединения);
* push-слушатель исполняется на reader-потоке — его исключение не должно убить поток
  (иначе после первого кривого слушателя клиент глохнет навсегда, без ошибки).

Хост — минимальный TCP-сервер на 127.0.0.1:0 (не RouterManager): тестам нужна
точная власть над тем, отвечать ли, когда рвать и что пушить.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import pytest

from ..channels.socket_client import SocketClient, SocketConnectionLost


class _FakeHost:
    """TCP-сервер: пишет входящие в ``received``, отвечает ``responder(msg)`` (None — молчит)."""

    def __init__(self, responder: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> None:
        self._srv = socket.create_server(("127.0.0.1", 0))
        self.port = self._srv.getsockname()[1]
        self.responder = responder
        self.received: List[Dict[str, Any]] = []
        self.conns: List[socket.socket] = []
        self.accepted = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            self.conns.append(conn)
            self.accepted.set()
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                msg = json.loads(raw)
                self.received.append(msg)
                try:
                    reply = self.responder(msg) if self.responder else None
                    if reply is not None:
                        self.send(conn, reply)
                except OSError:
                    return  # клиент уже закрыл сокет (BrokenPipe) — фейку не падать

    @staticmethod
    def send(conn: socket.socket, msg: Dict[str, Any]) -> None:
        conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))

    def push(self, msg: Dict[str, Any]) -> None:
        self.send(self.conns[-1], msg)

    def drop(self) -> None:
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    def close(self) -> None:
        self.drop()
        self._srv.close()


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _connected(host: _FakeHost) -> SocketClient:
    client = SocketClient("127.0.0.1", host.port, sender="gui")
    client.connect()
    assert host.accepted.wait(2.0), "сервер не принял соединение"
    return client


def test_close_fires_each_async_callback_exactly_once() -> None:
    """close(): каждый ожидающий request_async получает ОДИН колбэк с ошибкой."""
    host = _FakeHost()  # молчит — ответы не придут
    try:
        client = _connected(host)
        calls: Dict[str, List[Dict[str, Any]]] = {"a": [], "b": []}
        client.request_async({"command": "x"}, calls["a"].append, timeout=30.0)
        client.request_async({"command": "y"}, calls["b"].append, timeout=30.0)
        client.close()
        client.close()  # идемпотентность: второй close не зовёт колбэки повторно
        time.sleep(0.7)  # > периода опроса reader'а: таймаут-ветка не должна добавить вызов
        for key in ("a", "b"):
            assert len(calls[key]) == 1, f"{key}: колбэк позван {len(calls[key])} раз"
            assert calls[key][0]["success"] is False
            assert calls[key][0]["error"] == "connection closed"
        assert client.connection_lost is False, "намеренный close — не разрыв (I4)"
    finally:
        host.close()


def test_conn_lost_fires_async_callback_once_with_connection_lost() -> None:
    """Разрыв со стороны хоста: async-колбэк — ровно один, error == 'connection lost'."""
    host = _FakeHost()
    try:
        client = _connected(host)
        got: List[Dict[str, Any]] = []
        client.request_async({"command": "x"}, got.append, timeout=30.0)
        host.drop()
        assert _wait(lambda: client.connection_lost), "разрыв не зафиксирован"
        client.close()  # close после разрыва не должен позвать колбэк ещё раз
        assert [m["error"] for m in got] == ["connection lost"]
    finally:
        host.close()


def test_async_timeout_once_and_late_reply_quarantined() -> None:
    """Таймаут async → один колбэк 'timeout'; поздний ответ — в карантин, не в push."""
    host = _FakeHost()
    try:
        client = _connected(host)
        got: List[Dict[str, Any]] = []
        pushes: List[Dict[str, Any]] = []
        client.add_push_listener(pushes.append)
        cid = client.request_async({"command": "x"}, got.append, timeout=0.2)
        assert _wait(lambda: got, timeout=1.5), "таймаут async не сработал за timeout + опрос"
        host.push({"request_id": cid, "result": {"success": True}})
        time.sleep(0.3)
        assert [m["error"] for m in got] == ["timeout"]
        assert pushes == [], "поздний ответ всплыл push-событием (нарушение I3)"
        assert client.late_replies == 1
    finally:
        host.close()


def test_send_nowait_on_lost_connection_raises() -> None:
    """send_nowait после разрыва — SocketConnectionLost, а не тихая запись в пустоту."""
    host = _FakeHost()
    try:
        client = _connected(host)
        host.drop()
        assert _wait(lambda: client.connection_lost), "разрыв не зафиксирован"
        with pytest.raises(SocketConnectionLost):
            client.send_nowait({"command": "noop"})
    finally:
        host.close()


def test_send_nowait_reply_is_quarantined_not_push() -> None:
    """Ответ хоста на send_nowait не всплывает push'ем и не считается поздним (I3)."""
    host = _FakeHost(responder=lambda m: {"request_id": m["request_id"], "result": {"success": True}})
    try:
        client = _connected(host)
        pushes: List[Dict[str, Any]] = []
        client.add_push_listener(pushes.append)
        client.send_nowait({"command": "noop"})
        assert _wait(lambda: len(host.received) == 1)
        time.sleep(0.2)
        assert pushes == []
        assert client.late_replies == 0
    finally:
        host.close()


def test_push_listener_exception_does_not_kill_reader() -> None:
    """Исключение слушателя: следующий слушатель получает push, reader жив для следующего."""
    host = _FakeHost()
    try:
        client = _connected(host)

        def _boom(msg: Dict[str, Any]) -> None:
            raise RuntimeError("кривой слушатель")

        got: List[Dict[str, Any]] = []
        client.add_push_listener(_boom)
        client.add_push_listener(got.append)
        host.push({"command": "one"})
        host.push({"command": "two"})
        assert _wait(lambda: len(got) == 2), f"дошло {got}"
        assert [m["command"] for m in got] == ["one", "two"]
        assert client._reader is not None and client._reader.is_alive()
    finally:
        host.close()


def test_out_of_order_replies_reach_their_own_requests() -> None:
    """I2: два request в ожидании одновременно, хост отвечает НЕ по порядку — каждый
    получает свой ответ (матчинг по request_id, а не «первый ожидающий»)."""
    held: Dict[str, Any] = {}
    host: _FakeHost

    def _reply(msg: Dict[str, Any]) -> Dict[str, Any]:
        return {"request_id": msg["request_id"], "result": {"success": True, "result": {"tag": msg["tag"]}}}

    def _responder(msg: Dict[str, Any]) -> None:
        if "first" not in held:
            held["first"] = msg  # держим первый ответ, пока не придёт второй запрос
            return None
        host.push(_reply(msg))  # сначала — второму
        host.push(_reply(held["first"]))  # потом — первому
        return None

    host = _FakeHost(responder=_responder)
    try:
        client = _connected(host)
        results: Dict[str, Any] = {}

        def _call(tag: str) -> None:
            results[tag] = client.request({"command": "echo", "tag": tag}, timeout=3.0)

        ta = threading.Thread(target=_call, args=("A",), daemon=True)
        ta.start()
        assert _wait(lambda: len(host.received) == 1), "первый запрос не дошёл"
        tb = threading.Thread(target=_call, args=("B",), daemon=True)
        tb.start()
        ta.join(5.0)
        tb.join(5.0)
        assert not ta.is_alive() and not tb.is_alive(), "зависание вместо ответа"
        assert results["A"] == {"success": True, "result": {"tag": "A"}}
        assert results["B"] == {"success": True, "result": {"tag": "B"}}
    finally:
        host.close()


class _DropInsideLockWindow:
    """Подмена ``_pending_lock``: при ПЕРВОМ входе из потока-вызывающего рвёт соединение
    со стороны хоста и ждёт, пока reader отметит обрыв и завершится — детерминированно
    попадает в окно «проверка _conn_lost → вставка слота» (ревью 1.2, кейс [a])."""

    def __init__(self, client: SocketClient, host: _FakeHost) -> None:
        self._real = client._pending_lock
        self._client = client
        self._host = host
        self.caller: Optional[threading.Thread] = None
        self.fired = False

    def __enter__(self) -> Any:
        if threading.current_thread() is self.caller and not self.fired:
            self.fired = True
            reader = self._client._reader
            self._host.drop()
            assert reader is not None
            reader.join(3.0)
        return self._real.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._real.__exit__(*exc)


def _run_in_window(client: SocketClient, host: _FakeHost, fn: Callable[[], Any]) -> Dict[str, Any]:
    gate = _DropInsideLockWindow(client, host)
    client._pending_lock = gate  # type: ignore[assignment]
    box: Dict[str, Any] = {}

    def _run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — в вызывающий поток ниже
            box["exc"] = exc
        box["elapsed"] = time.monotonic() - t0

    t = threading.Thread(target=_run, daemon=True)
    gate.caller = t
    t.start()
    t.join(5.0)
    assert not t.is_alive(), "вызов завис"
    assert gate.fired, "окно не сработало — тест ничего не проверил"
    assert not client._reader or not client._reader.is_alive(), "reader ещё жив — окно не то"
    return box


def test_request_async_in_conn_lost_window_gets_callback() -> None:
    """Обрыв между проверкой _conn_lost и вставкой слота: колбэк 'connection lost'
    приходит сразу, слот-сирота не остаётся (reader уже вышел — будить его некому)."""
    host = _FakeHost()
    try:
        client = _connected(host)
        got: List[Dict[str, Any]] = []
        _run_in_window(client, host, lambda: client.request_async({"command": "x"}, got.append, timeout=1.0))
        assert _wait(lambda: got, timeout=0.5), "колбэк не пришёл — слот осиротел"
        assert [m["error"] for m in got] == ["connection lost"]
        assert client._pending == {}
    finally:
        host.close()


def test_request_in_conn_lost_window_raises_immediately() -> None:
    """То же окно для блокирующего request: исключение разрыва сразу, а не таймаут."""
    host = _FakeHost()
    try:
        client = _connected(host)
        box = _run_in_window(client, host, lambda: client.request({"command": "x"}, timeout=3.0))
        assert isinstance(box.get("exc"), SocketConnectionLost), f"получено {box}"
        assert box["elapsed"] < 1.0
        assert client._pending == {}
    finally:
        host.close()
