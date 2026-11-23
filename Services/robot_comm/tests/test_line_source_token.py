# -*- coding: utf-8 -*-
"""Task 0.12a: ``LineLink`` (отладочная дверь линии) шлёт ``hello`` с токеном из файла порта.

Хост — настоящий ``SocketChannel`` с ``authenticator``; ``on_inbound`` отвечает
``{"success": True, "request_id": ...}``. ``HOME`` и ``USERPROFILE`` — во временный каталог:
настоящий ``~/.multiprocess_framework`` не трогается. Вызов, который может зависнуть, —
в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="line_source транзитивно подтягивает Qt-модули фреймворка")

from multiprocess_framework.modules.router_module.channels.socket_auth import token_authenticator
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel
from Services.robot_comm.gui.line_source import LineLink

TOKEN = "ab" * 32


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


def test_line_link_connects_to_authenticated_host(tmp_home: Path) -> None:
    received: list[dict[str, Any]] = []
    channel: SocketChannel | None = None

    def on_inbound(msg: dict[str, Any]) -> None:
        received.append(msg)
        if "request_id" in msg and channel is not None:
            channel.send({"success": True, "request_id": msg["request_id"]})

    channel = SocketChannel("backend_ctl", port=0, on_inbound=on_inbound, authenticator=token_authenticator(TOKEN))
    assert channel.start() is True
    path = tmp_home / ".multiprocess_framework" / f"ctl_{channel.port}.token"
    path.parent.mkdir(parents=True)
    path.write_text(TOKEN + "\n", encoding="ascii")

    link = LineLink("127.0.0.1", channel.port, mode="poll", connect_timeout_s=2.0)
    box: dict[str, Any] = {}

    def open_link() -> None:
        try:
            link.open()
            box["ok"] = True
        except BaseException as exc:  # noqa: BLE001 — показывается в assert ниже
            box["exc"] = exc

    try:
        thread = threading.Thread(target=open_link, daemon=True)
        thread.start()
        thread.join(5.0)
        assert not thread.is_alive(), "link.open() не завершился за 5.0 с"
        assert "exc" not in box, repr(box.get("exc"))
        assert box.get("ok") is True
        assert [m.get("command") for m in received] == ["state.get_subtree"]
    finally:
        link.close()
        channel.close()
