# -*- coding: utf-8 -*-
"""Task 0.12a: транспорт драйвера читает токен из файла порта и шлёт ``hello``.

Сервер — настоящий ``SocketChannel`` с ``authenticator`` (``token_authenticator``);
``on_inbound`` отвечает ``{"success": True, "request_id": ...}``: успех = ответ без
``auth_required``. ``HOME`` и ``USERPROFILE`` — во временный каталог (настоящий
``~/.multiprocess_framework`` не трогается), ``BACKEND_CTL_*`` из окружения убраны.
Всё, что может зависнуть, — в daemon-потоке с дедлайном. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_errors import BackendUnavailable
from multiprocess_framework.modules.router_module.channels.socket_auth import token_authenticator
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel

TOKEN_A = "ab" * 32
TOKEN_B = "cd" * 32
WORKTREE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for key in list(os.environ):
        if key.startswith("BACKEND_CTL_"):
            monkeypatch.delenv(key)
    return home


def _token_path(home: Path, port: int) -> Path:
    return home / ".multiprocess_framework" / f"ctl_{port}.token"


def _put_token(home: Path, port: int, token: str) -> Path:
    path = _token_path(home, port)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="ascii")
    return path


def _run(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Вызвать ``fn`` в daemon-потоке; исключение ``fn`` пробросить, зависание — провал."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасывается в тест ниже
            box["exc"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail(f"вызов не завершился за {timeout} с")
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


class _Server:
    """``SocketChannel`` с токеном; отвечает успехом на каждый запрос с ``request_id``."""

    def __init__(self, token: str, port: int = 0) -> None:
        self.received: list[dict[str, Any]] = []
        self.channel = SocketChannel(
            "backend_ctl",
            port=port,
            on_inbound=self._on_inbound,
            authenticator=token_authenticator(token),
        )
        assert self.channel.start() is True
        self.port = self.channel.port

    def _on_inbound(self, msg: dict[str, Any]) -> None:
        self.received.append(msg)
        if "request_id" in msg:
            self.channel.send({"success": True, "request_id": msg["request_id"]})

    def close(self) -> None:
        self.channel.close()


def _connect_and_ping(driver: BackendDriver) -> dict[str, Any]:
    driver.connect(timeout=2.0)
    return driver.request({"command": "ping-12a"}, timeout=2.0)


def test_driver_sends_hello_with_token_from_file(tmp_home: Path) -> None:
    server = _Server(TOKEN_A)
    driver = BackendDriver(port=server.port)
    try:
        _put_token(tmp_home, server.port, TOKEN_A)
        reply = _run(lambda: _connect_and_ping(driver))
        assert reply.get("success") is True, reply
        assert [m.get("command") for m in server.received] == ["ping-12a"]
    finally:
        driver.close()
        server.close()


def test_driver_connects_without_token_file_to_open_server(tmp_home: Path) -> None:
    """СТРАЖ: файла нет → первая строка клиента — запрос, а не ``hello``."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3.0)
    port = listener.getsockname()[1]
    first_lines: list[bytes] = []

    def serve() -> None:
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        conn.settimeout(3.0)
        with conn, conn.makefile("rb") as reader:
            try:
                line = reader.readline()
            except OSError:
                return
            first_lines.append(line)
            try:
                msg = json.loads(line)
            except ValueError:
                return
            if isinstance(msg, dict) and "request_id" in msg:
                conn.sendall((json.dumps({"success": True, "request_id": msg["request_id"]}) + "\n").encode("utf-8"))

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()
    driver = BackendDriver(port=port)
    try:
        reply = _run(lambda: _connect_and_ping(driver))
        server_thread.join(3.0)
        assert len(first_lines) == 1, first_lines
        first = json.loads(first_lines[0])
        assert first.get("type") != "hello", first
        assert first.get("command") == "ping-12a", first
        assert reply.get("success") is True, reply
    finally:
        driver.close()
        listener.close()


def test_wrong_token_driver_error_names_path(tmp_home: Path) -> None:
    server = _Server(TOKEN_A)
    driver = BackendDriver(port=server.port)
    try:
        path = _put_token(tmp_home, server.port, TOKEN_B)
        with pytest.raises(BackendUnavailable) as info:
            _run(lambda: _connect_and_ping(driver))
        text = str(info.value)
        assert text == f"token rejected: {path}"
        assert TOKEN_A not in text and TOKEN_B not in text
        # Ретрай `except OSError` (harness) сохраняется: отказ — и OSError.
        assert isinstance(info.value, OSError)
        assert server.received == []
    finally:
        driver.close()
        server.close()


def test_missing_token_file_error_names_path(tmp_home: Path) -> None:
    server = _Server(TOKEN_A)
    driver = BackendDriver(port=server.port)
    try:
        path = _token_path(tmp_home, server.port)
        with pytest.raises(BackendUnavailable) as info:
            _run(lambda: _connect_and_ping(driver))
        assert str(info.value) == f"token file not found: {path}"
        assert server.received == []
    finally:
        driver.close()
        server.close()


_CHILD = """
import sys
from backend_ctl.driver import BackendDriver

driver = BackendDriver(port=int(sys.argv[1]))
driver.connect(timeout=2.0)
reply = driver.request({"command": "ping-12a"}, timeout=2.0)
driver.close()
if reply.get("success") is not True:
    sys.stderr.write("reply: %r\\n" % (reply,))
    sys.exit(3)
print("ok-12a")
"""


def test_clean_env_client_finds_token(tmp_home: Path, tmp_path: Path) -> None:
    server = _Server(TOKEN_A)
    try:
        _put_token(tmp_home, server.port, TOKEN_A)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(WORKTREE_ROOT),
            "HOME": str(tmp_home),
            "USERPROFILE": str(tmp_home),
        }
        if "SYSTEMROOT" in os.environ:  # Windows: без него не работают сокеты
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        proc = _run(
            lambda: subprocess.run(
                [sys.executable, "-c", _CHILD, str(server.port)],
                env=env,
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=5,
            ),
            timeout=5.0,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "ok-12a", proc.stdout
    finally:
        server.close()


def test_mcp_session_shows_token_file_not_found(tmp_home: Path) -> None:
    """Ревью стадии 5, находка 1: пробы ``_await_ready`` не съедают текст — его видит вызов MCP."""
    from backend_ctl.dispatch import dispatch_tool
    from backend_ctl.mcp_driver_session import DriverSession

    server = _Server(TOKEN_A)
    session = DriverSession(port=server.port, request_timeout=2.0, log=lambda _line: None)
    try:
        with pytest.raises(BackendUnavailable) as info:
            _run(lambda: dispatch_tool(session, "run_status", {}), timeout=10.0)
        assert str(info.value) == f"token file not found: {_token_path(tmp_home, server.port)}"
        assert server.received == []
    finally:
        session.reset()
        server.close()


def test_system_shutdown_without_token_file_is_not_pm_gone(tmp_home: Path) -> None:
    """Ревью стадии 5, находка 2: команда не дошла — это не «PM ушёл» (``pm_gone``)."""
    from backend_ctl.transport import TokenFileMissing

    server = _Server(TOKEN_A)
    driver = BackendDriver(port=server.port)
    try:
        _run(lambda: driver.connect(timeout=2.0))
        with pytest.raises(TokenFileMissing) as info:
            _run(lambda: driver.system_shutdown(wait=False))
        assert str(info.value) == f"token file not found: {_token_path(tmp_home, server.port)}"
        assert server.received == []
    finally:
        driver.close()
        server.close()


def test_request_passes_non_dict_result_and_other_errors(tmp_home: Path) -> None:
    """Ревью стадии 5, находка 3: подмена — только для dict ``success False`` + ``auth_required``."""
    server = _Server(TOKEN_A)
    replies = {
        "list-12a": {"success": True, "result": [1, 2]},
        "boom-12a": {"success": False, "error": "boom"},
    }

    def on_inbound(msg: dict[str, Any]) -> None:
        server.received.append(msg)
        server.channel.send({**replies[msg["command"]], "request_id": msg["request_id"]})

    server.channel._on_inbound = on_inbound
    driver = BackendDriver(port=server.port)
    try:
        _put_token(tmp_home, server.port, TOKEN_A)
        _run(lambda: driver.connect(timeout=2.0))
        assert _run(lambda: driver.request({"command": "list-12a"}, timeout=2.0)) == [1, 2]
        boom = {"command": "boom-12a"}
        reply = _run(lambda: driver.request(boom, timeout=2.0))
        assert reply == {"success": False, "error": "boom", "request_id": boom["request_id"]}
    finally:
        driver.close()
        server.close()


def test_explicit_provider_beats_file_and_none_restores_file(tmp_home: Path) -> None:
    """Сеттер свойства: явный провайдер главнее файла; ``None`` возвращает файловый."""
    server = _Server(TOKEN_A)
    driver = BackendDriver(port=server.port)
    try:
        _put_token(tmp_home, server.port, TOKEN_B)
        driver._token_provider = lambda: TOKEN_A
        assert _run(lambda: _connect_and_ping(driver)).get("success") is True
        driver.close()

        driver._token_provider = None
        with pytest.raises(BackendUnavailable) as info:
            _run(lambda: _connect_and_ping(driver))
        assert str(info.value) == f"token rejected: {_token_path(tmp_home, server.port)}"
    finally:
        driver.close()
        server.close()


def test_provider_rereads_token_on_reconnect(tmp_home: Path) -> None:
    first = _Server(TOKEN_A)
    port = first.port
    second: _Server | None = None
    driver = BackendDriver(port=port)
    try:
        _put_token(tmp_home, port, TOKEN_A)
        assert _run(lambda: _connect_and_ping(driver)).get("success") is True
        driver.close()
        first.close()

        second = _Server(TOKEN_B, port=port)
        _put_token(tmp_home, port, TOKEN_B)
        reply = _run(lambda: _connect_and_ping(driver))
        assert reply.get("success") is True, reply
        assert [m.get("command") for m in second.received] == ["ping-12a"]
    finally:
        driver.close()
        first.close()
        if second is not None:
            second.close()
