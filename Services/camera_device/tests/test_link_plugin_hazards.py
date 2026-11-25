# -*- coding: utf-8 -*-
"""Тесты опасности плагина камеры при переподключении (W2-a1): заглушка без `reconnecting`, ответ `take_device`,
строка личности после переподключения.

Автор — исполнитель (teamlead). Порт — фейк ядра, сеанс, `WorkerManager` и контекст плагина — настоящие.
Вызов, который может зависнуть, идёт в daemon-потоке с дедлайном `join`. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port

_CFG = {
    "auto_start": False,
    "camera_id": 5,
    "device_select": "serial",
    "device_serial": "FAKE-0001",
    "timeout_ms": 100,
    "link_silence_s": 0.5,
    "reconnect_interval_s": 0.5,
}
_OPENED = "CameraDevicePlugin: device opened "


def _call(fn: Callable[[], Any], deadline: float = 8.0) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


def _await(pred: Callable[[], bool], message: str, deadline: float = 6.0) -> None:
    end = time.monotonic() + deadline
    while not pred():
        if time.monotonic() >= end:
            pytest.fail(f"не дождались за {deadline} с: {message}")
        time.sleep(0.01)


class _Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, port: Any, **cfg: Any) -> None:
        config = {**_CFG, **cfg}
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        self.services = MockProcessServices(name="cam_link_hz", config=config, plugin_levels=PluginLevels())
        self.wm = WorkerManager("test_link_plugin_hazards")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def lines(self, level: str, prefix: str) -> list[str]:
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and e["msg"].startswith(prefix)]

    def close(self) -> None:
        try:
            if getattr(self.plugin, "_session", None) is not None:
                _call(lambda: self.plugin.shutdown(self.ctx), 10.0)
        finally:
            self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(port: Any, **cfg: Any) -> _Rig:
        built = _Rig(monkeypatch, port, **cfg)
        rigs.append(built)
        return built

    yield factory
    for built in rigs:
        built.close()


class _BusyStub:
    """Сеанс-заглушка прежнего вида: только `state`, атрибута `reconnecting` нет."""

    state = "busy"


def test_readiness_without_reconnecting_attribute(make):
    """Заглушка без `reconnecting` в `busy`: прежний литерал причины, исключения нет."""
    rig = make(fake_port.make_port(frame_period_s=0.01))
    rig.plugin._session = _BusyStub()
    try:
        assert rig.plugin.readiness(rig.ctx) == [{"severity": "failure", "reason": "камера занята"}]
    finally:
        rig.plugin._session = None


@pytest.mark.parametrize(("reconnect", "expected"), [(True, True), (False, False)])
def test_take_reply_carries_reconnecting(make, reconnect, expected):
    """Прибор занят: ответ `take_device` несёт `reconnecting` (с `reconnect` — `True`, сеанс повторяет сам)."""
    rig = make(fake_port.make_port(busy_for_s=60.0, frame_period_s=0.01), reconnect=reconnect)
    reply = _call(lambda: rig.plugin.cmd_take_device({}))

    assert reply["status"] == "error"
    assert reply["device_state"] == "busy"
    assert reply["reconnecting"] is expected
    if reconnect:
        assert rig.plugin.readiness(rig.ctx) == [{"severity": "failure", "reason": "камера занята, переподключение"}]


def test_reconnect_does_not_repeat_identity_line(make):
    """Переподключение к тому же прибору: строка "device opened" не повторяется, вместо неё одна DEBUG."""
    port = fake_port.make_link_event_port(frame_period_s=0.01)
    rig = make(port, reconnect=True)
    assert _call(lambda: rig.plugin.cmd_take_device({}))["status"] == "ok"
    session = rig.plugin._session
    assert len(rig.lines("INFO", _OPENED)) == 1

    port.emit_link_event("disconnected")
    _await(lambda: session.link()["outages"] == 1, "потеря связи учтена")
    _await(lambda: session.state == "grabbing", "возврат в grabbing после переподключения")
    time.sleep(0.2)

    assert len(rig.lines("INFO", _OPENED)) == 1
    assert len(rig.lines("DEBUG", "CameraDevicePlugin: device reopened ")) == 1
