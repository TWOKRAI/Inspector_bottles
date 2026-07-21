# -*- coding: utf-8 -*-
"""Бюджет ожидания должен доезжать до сервера, а не оставаться у клиента.

Регресс, измеренный живьём 2026-07-21: ``topology.apply`` с ``timeout=180``
возвращал ``{"success": False, "error": "timeout"}`` ровно через 5.00 с — при
этом переключение топологии ПРОХОДИЛО (новые процессы в state, ghost'ов нет).

Причина: ``request()`` использовал timeout только для СВОЕГО ожидания и не клал
его в сообщение, а ``socket_bridge_adapter`` читает ``msg["timeout"]`` и без
этого поля берёт свой дефолт (5 с). Сервер сдавался раньше и рапортовал таймаут
на успешной команде — из-за этого падали live-тесты switch/wire/routing.

Инвариант: сервер ждёт чуть МЕНЬШЕ клиента. Тогда клиент получает честный ответ
сервера («не успел вот на этом»), а не подменяет диагноз собственным таймаутом.

Тесты гоняют РЕАЛЬНЫЙ сокет, а не fake-транспорт — та же причина, что в
``test_conn_lost.py``: на фейках находка такого класса уцелела бы, потому что
фейк моделирует ровно то, что проверяет. Здесь сервер настоящий и просто
записывает пришедшее по проводу.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import List, Optional

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.transport import _SERVER_MARGIN_SEC

_HOST = "127.0.0.1"


class _RecordingServer:
    """TCP-listener, который записывает пришедшие сообщения и может ответить."""

    def __init__(self, *, reply: bool = False) -> None:
        self._reply = reply
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind((_HOST, 0))
        self._srv.listen(1)
        self._srv.settimeout(5.0)
        self.port: int = self._srv.getsockname()[1]
        self.received: List[dict] = []
        self._conn: Optional[socket.socket] = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        self._conn = conn
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                self.received.append(msg)
                if self._reply:
                    resp = {
                        "request_id": msg.get("request_id"),
                        "success": True,
                        "result": {"ok": 1},
                    }
                    try:
                        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                    except OSError:
                        return

    def wait_for_message(self, timeout: float = 3.0) -> dict:
        deadline = threading.Event()
        deadline.wait(0)  # no-op, читаемость
        import time

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.received:
                return self.received[0]
            time.sleep(0.02)
        raise AssertionError("сервер не получил ни одного сообщения")

    def close(self) -> None:
        for sock in (self._conn, self._srv):
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass


@pytest.fixture
def server():
    srv = _RecordingServer()
    yield srv
    srv.close()


@pytest.fixture
def answering_server():
    srv = _RecordingServer(reply=True)
    yield srv
    srv.close()


def _driver(port: int, **kw) -> BackendDriver:
    drv = BackendDriver(host=_HOST, port=port, **kw)
    drv.connect()
    return drv


class TestTimeoutPropagation:
    """Сервер отвечает сразу — иначе клиент честно ждал бы весь запрошенный
    таймаут (180 с), и тест повис бы вместо проверки."""

    def test_caller_timeout_reaches_the_wire(self, answering_server):
        drv = _driver(answering_server.port)
        try:
            drv.send_command("ProcessManager", "topology.apply", timeout=180.0)
        finally:
            drv.close()

        assert answering_server.wait_for_message()["timeout"] == pytest.approx(180.0 - _SERVER_MARGIN_SEC)

    def test_server_budget_is_smaller_than_client_wait(self, answering_server):
        """Инвариант: клиент не должен сдаваться раньше сервера."""
        drv = _driver(answering_server.port)
        try:
            drv.send_command("ProcessManager", "x", timeout=30.0)
        finally:
            drv.close()

        assert answering_server.wait_for_message()["timeout"] < 30.0

    def test_default_timeout_also_propagates(self, answering_server):
        drv = _driver(answering_server.port, default_timeout=7.0)
        try:
            drv.send_command("ProcessManager", "x")
        finally:
            drv.close()

        assert answering_server.wait_for_message()["timeout"] == pytest.approx(7.0 - _SERVER_MARGIN_SEC)

    def test_tiny_timeout_stays_positive(self, answering_server):
        """Крошечный таймаут не должен дать серверу отрицательный бюджет."""
        drv = _driver(answering_server.port)
        try:
            drv.send_command("ProcessManager", "x", timeout=0.1)
        finally:
            drv.close()

        assert answering_server.wait_for_message()["timeout"] > 0


class TestBehaviourUnchanged:
    """Само поведение request() при таймауте и при ответе не меняется."""

    def test_silent_server_still_yields_timeout_error(self, server):
        drv = _driver(server.port)
        try:
            res = drv.send_command("ProcessManager", "x", timeout=0.3)
        finally:
            drv.close()

        assert res["success"] is False
        assert res["error"] == "timeout"

    def test_answering_server_resolves_request(self, answering_server):
        """Ответ доезжает и резолвит pending. Driver отдаёт РАЗВЁРНУТЫЙ result
        (не конверт) — проверяем полезную нагрузку, а не поле success."""
        drv = _driver(answering_server.port)
        try:
            res = drv.send_command("ProcessManager", "x", timeout=5.0)
        finally:
            drv.close()

        assert res.get("ok") == 1
        assert res.get("error") is None
