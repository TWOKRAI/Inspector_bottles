# -*- coding: utf-8 -*-
"""Task 0.12b: порт управления ProcessManager закрыт без токена; поставка выключена.

Сервер — настоящий ``setup_backend_ctl_channel`` (``port: 0`` или заранее найденный
свободный порт) с роутером-двойником. ``HOME`` и ``USERPROFILE`` — во временный
каталог (фикстура ``tmp_home`` из ``conftest.py``): настоящий ``~/.multiprocess_framework``
не трогается; ``BACKEND_CTL_*`` из окружения убраны. Всё, что может зависнуть, — в
daemon-потоке с дедлайном.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.process.backend_ctl_endpoint import (
    is_enabled,
    setup_backend_ctl_channel,
    teardown_backend_ctl_channel,
)
from multiprocess_framework.modules.router_module.channels import socket_auth

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_YAML = WORKTREE_ROOT / "multiprocess_prototype" / "backend" / "config" / "system.yaml"
TOKEN_STALE = "5a" * 32
TOKEN_FOREIGN = "f0" * 32
ENV_ON = {"BACKEND_CTL": "1"}

pytestmark = pytest.mark.usefixtures("tmp_home")  # общая фикстура conftest.py: HOME во временный каталог


class FakeRouter:
    """Двойник RouterManager: реестр каналов + ``request``/``send``."""

    def __init__(self, handler: Callable[[dict], dict] | None = None) -> None:
        self.channels: dict[str, Any] = {}
        self._handler = handler or (lambda msg: {"success": True, "result": {"echo": msg.get("command")}})

    def register_channel(self, channel: Any) -> bool:
        self.channels[channel.name] = channel
        return True

    def unregister_channel(self, name: str) -> bool:
        return self.channels.pop(name, None) is not None

    def request(self, message: dict, timeout: float = 5.0) -> dict:
        return self._handler(message)

    def send(self, message: dict) -> dict:
        ch = self.channels.get(message.get("channel"))
        if ch is not None:
            return ch.send(message)
        return {"status": "error", "reason": "no channel"}


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


def _token_path(home: Path, port: int) -> Path:
    return home / ".multiprocess_framework" / f"ctl_{port}.token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _exchange(port: int, line: dict, timeout: float = 3.0) -> tuple[dict | None, bytes]:
    """Сырой TCP: отправить одну строку, прочитать первую строку ответа и остаток до EOF.

    Returns: (первая строка ответа как dict | None, байты после неё до EOF).
    """

    def go() -> tuple[dict | None, bytes]:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(line) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return None, buf
                buf += chunk
            first, _, rest = buf.partition(b"\n")
            reply = json.loads(first)
            if reply.get("error") == "auth_required":
                while True:  # после отказа хост закрывает соединение
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    rest += chunk
            return reply, rest

    return _run(go, timeout=timeout + 2.0)


def test_shipped_config_disabled() -> None:
    section = yaml.safe_load(SYSTEM_YAML.read_text(encoding="utf-8"))["backend_ctl"]
    assert section["enabled"] is False
    assert is_enabled({}, section) is False  # без env порт не открывается
    assert is_enabled({"BACKEND_CTL": "1"}, section) is True  # dev-старт


def test_raw_tcp_without_hello_gets_auth_required() -> None:
    router = FakeRouter()
    ch = setup_backend_ctl_channel(router, port=0, env=ENV_ON)
    assert ch is not None
    try:
        reply, rest = _exchange(ch.port, {"cmd": "ping"})
        assert reply == {"success": False, "error": "auth_required"}
        assert rest == b""  # EOF после отказа, больше ничего
    finally:
        teardown_backend_ctl_channel(ch, router)


@pytest.mark.skipif(sys.platform == "win32", reason="режим 0600 — POSIX; на Windows права задаёт ACL профиля")
def test_token_file_written_0600_after_start(tmp_home: Path) -> None:
    router = FakeRouter()
    ch = setup_backend_ctl_channel(router, port=0, env=ENV_ON)
    assert ch is not None
    try:
        assert ch.port != 0
        path = _token_path(tmp_home, ch.port)
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
        token = socket_auth.read_token(path)
        assert token is not None and len(token) == 64
        assert not _token_path(tmp_home, 0).exists()  # не ctl_0.token: имя по фактическому порту
    finally:
        teardown_backend_ctl_channel(ch, router)


def test_token_removed_on_stop(tmp_home: Path) -> None:
    router = FakeRouter()
    ch = setup_backend_ctl_channel(router, port=0, env=ENV_ON)
    assert ch is not None
    path = _token_path(tmp_home, ch.port)
    try:
        assert path.is_file()  # фаза «до»: без неё «файла нет» зелёно вакуумно
    finally:
        teardown_backend_ctl_channel(ch, router)
    assert not path.exists()  # фаза «после»


def test_failed_bind_leaves_other_token_intact(tmp_home: Path) -> None:
    router_a = FakeRouter()
    router_b = FakeRouter()  # второй ПМ — свой процесс и свой роутер
    ch_a = setup_backend_ctl_channel(router_a, port=0, env=ENV_ON)
    assert ch_a is not None
    path = _token_path(tmp_home, ch_a.port)
    try:
        token_a = socket_auth.read_token(path)
        assert token_a is not None and len(token_a) == 64
        ch_b = setup_backend_ctl_channel(router_b, port=ch_a.port, env=ENV_ON)
        assert ch_b is None
        assert router_b.channels == {}
        assert socket_auth.read_token(path) == token_a
        reply, _ = _exchange(ch_a.port, {"type": "hello", "token": token_a})
        assert reply == {"type": "hello", "success": True}
    finally:
        teardown_backend_ctl_channel(ch_a, router_a)


def test_stale_token_overwritten_on_start(tmp_home: Path) -> None:
    port = _free_port()
    path = _token_path(tmp_home, port)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TOKEN_STALE + "\n", encoding="ascii")  # залип после SIGKILL прошлого ПМ
    router = FakeRouter()
    ch = setup_backend_ctl_channel(router, port=port, env=ENV_ON)
    assert ch is not None
    try:
        fresh = socket_auth.read_token(path)
        assert fresh is not None and len(fresh) == 64
        assert fresh != TOKEN_STALE
        stale_reply, _ = _exchange(port, {"type": "hello", "token": TOKEN_STALE})
        assert stale_reply == {"success": False, "error": "auth_required"}
        fresh_reply, _ = _exchange(port, {"type": "hello", "token": fresh})
        assert fresh_reply == {"type": "hello", "success": True}
    finally:
        teardown_backend_ctl_channel(ch, router)


def test_token_removed_only_if_own(tmp_home: Path) -> None:
    router = FakeRouter()
    ch = setup_backend_ctl_channel(router, port=0, env=ENV_ON)
    assert ch is not None
    path = _token_path(tmp_home, ch.port)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TOKEN_FOREIGN + "\n", encoding="ascii")  # файл уже принадлежит другому ПМ
    finally:
        teardown_backend_ctl_channel(ch, router)
    assert socket_auth.read_token(path) == TOKEN_FOREIGN


def test_write_failure_returns_none_not_open_server(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path: Path) -> str:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(socket_auth, "write_token", boom)
    port = _free_port()
    router = FakeRouter()
    errors: list[str] = []
    ch = setup_backend_ctl_channel(router, port=port, env=ENV_ON, log_error=errors.append)
    try:
        assert ch is None
        assert router.channels == {}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            assert probe.connect_ex(("127.0.0.1", port)) != 0  # порт не слушается
        assert len(errors) == 1
        assert not _token_path(tmp_home, port).exists()
    finally:
        teardown_backend_ctl_channel(ch, router)


def test_token_not_in_logs(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[str] = []
    real_write = socket_auth.write_token

    def spy(path: Path) -> str:
        token = real_write(path)
        written.append(token)
        return token

    monkeypatch.setattr(socket_auth, "write_token", spy)
    infos: list[str] = []
    errors: list[str] = []
    router = FakeRouter()
    ch = setup_backend_ctl_channel(router, port=0, env=ENV_ON, log_info=infos.append, log_error=errors.append)
    assert ch is not None
    try:
        file_token = socket_auth.read_token(_token_path(tmp_home, ch.port))
    finally:
        teardown_backend_ctl_channel(ch, router)
    assert infos  # журнал старта перехвачен: проверка не вакуумна по каналу журнала
    tokens = set(written) | ({file_token} if file_token else set())
    for token in tokens:
        for message in infos + errors:
            assert token not in message


def test_driver_round_trip_with_token() -> None:
    from backend_ctl.driver import BackendDriver

    calls: list[dict] = []

    def handler(msg: dict) -> dict:
        calls.append(msg)
        return {"success": True, "result": {"target": (msg.get("targets") or ["?"])[0]}}

    router = FakeRouter(handler=handler)
    ch = setup_backend_ctl_channel(router, port=0, env=ENV_ON)
    assert ch is not None
    driver = BackendDriver(host="127.0.0.1", port=ch.port)
    try:
        _run(driver.connect)
        res = _run(lambda: driver.introspect_handlers("preprocessor", timeout=3.0), timeout=6.0)
        assert res["success"] is True
        assert res["result"]["target"] == "preprocessor"
        assert [c["command"] for c in calls] == ["introspect.handlers"]
    finally:
        driver.close()
        teardown_backend_ctl_channel(ch, router)
