"""Тесты автора T5.3e.5a (REDS 5a2): команда ``robot_park_all`` плагина на настоящем ``CommandManager``.

Purpose:
    Хазарды проводки команды: исполнитель ``device_io`` (не поток приёма, ``robot_stop`` не встаёт за ней), отказ без
    исполнителя до обращения к менеджеру, отказ после хука ``request_stop``, ответ ``status: "error"`` менеджера не
    перетирается. Обвязка — ``Rig`` / ``RouterPath`` слепой приёмки SPI.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import FakeDriver, RouterPath, Rig, bounded

pytestmark = pytest.mark.timeout(60)

EXECUTORS = {"device_io": {}}


@pytest.fixture
def make_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Rig]]:
    rigs: list[Rig] = []

    def new(sub: str = "main", **kwargs: Any) -> Rig:
        path = tmp_path / sub
        path.mkdir(parents=True, exist_ok=True)
        rig = Rig(path, monkeypatch, **kwargs)
        rigs.append(rig)
        return rig

    yield new
    for rig in reversed(rigs):
        rig.close()


class _ManagerSpy:
    """Подмена ``robot_park_all`` менеджера: вызовы, ожидание на ``Event``, ответ по сценарию."""

    def __init__(self, answer: dict | None = None, hold: threading.Event | None = None) -> None:
        self.calls: list[dict] = []
        self.entered = threading.Event()
        self.hold = hold
        self.answer = answer if answer is not None else {"status": "ok", "timeout_s": 30.0, "robots": {}}

    def __call__(self, data: dict, *, should_stop: Callable[[], bool]) -> dict:
        self.calls.append({"data": dict(data), "stop": should_stop()})
        self.entered.set()
        if self.hold is not None:
            assert self.hold.wait(10.0)
        return dict(self.answer)


def _spy(rig: Rig, monkeypatch: pytest.MonkeyPatch, spy: _ManagerSpy) -> None:
    monkeypatch.setattr(rig.plugin._manager, "robot_park_all", spy)


def test_command_through_router_on_executor(make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ один и вне потока роутера; пока команда ждёт, ``robot_stop`` по тому же пути отвечает < 0,3 с."""
    rig = make_rig(executors=EXECUTORS)
    rig.factory("robot", lambda entry, proto: FakeDriver(entry, proto))
    rig.upsert("r1", "robot", "delta_v2")
    assert rig.connect("r1") is True
    hold = threading.Event()
    spy = _ManagerSpy(hold=hold)
    _spy(rig, monkeypatch, spy)
    park_path = RouterPath(rig)
    worker = threading.Thread(target=lambda: park_path.request("robot_park_all", {}, deadline_s=15.0), daemon=True)
    worker.start()
    try:
        assert spy.entered.wait(5.0), "менеджер не вызван"
        stop_path = RouterPath(rig)
        t0 = time.monotonic()
        stop_path.request("robot_stop", {"device_id": "r1", "level": "SOFT"}, deadline_s=5.0)
        assert time.monotonic() - t0 < 0.3, time.monotonic() - t0
        assert len(stop_path.replies) == 1, stop_path.replies
        assert park_path.replies == [], "ответ park_all пришёл до конца ожидания"
    finally:
        hold.set()
        worker.join(15.0)
    assert not worker.is_alive()
    time.sleep(0.2)  # лишний ответ, если он есть, успел бы прийти
    assert len(park_path.replies) == 1, park_path.replies
    result, thread_name = park_path.replies[0]
    assert result == {"status": "ok", "timeout_s": 30.0, "robots": {}}, result
    assert thread_name != "router-thread", thread_name
    assert spy.calls == [{"data": {}, "stop": False}], spy.calls


def test_command_without_executor_refuses(make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig()
    spy = _ManagerSpy()
    _spy(rig, monkeypatch, spy)
    answer = rig.cmd("robot_park_all", {})
    assert answer == {"status": "error", "message": "robot_park_all: нет исполнителя device_io"}, answer
    assert spy.calls == []


def test_command_refuses_after_hook(make_rig: Callable[..., Rig]) -> None:
    """После хука ``request_stop(ctx)`` настоящий менеджер отказывает «идёт остановка хаба» (``should_stop``)."""
    rig = make_rig(executors=EXECUTORS)
    assert rig.cmd("robot_park_all", {})["status"] == "ok"
    bounded(lambda: rig.plugin.request_stop(rig.ctx))
    assert rig.cmd("robot_park_all", {}) == {"status": "error", "message": "идёт остановка хаба"}


def test_command_error_reply_kept(make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(executors=EXECUTORS)
    reply = {"status": "error", "timeout_s": 1.0, "elapsed_s": 2.5, "robots": {"r1": {"result": "timeout", "seq": 1}}}
    reply["message"] = "основная остановка не выполнена: r1"
    _spy(rig, monkeypatch, _ManagerSpy(answer=reply))
    assert rig.cmd("robot_park_all", {"timeout_s": 1.0}) == reply


def test_command_exception_is_error_reply(make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch) -> None:
    rig = make_rig(executors=EXECUTORS)

    def boom(_data: dict, *, should_stop: Callable[[], bool]) -> dict:
        raise RuntimeError("park_all")

    monkeypatch.setattr(rig.plugin._manager, "robot_park_all", boom)
    answer = rig.cmd("robot_park_all", {})
    assert answer["status"] == "error" and answer["message"] == "park_all", answer
