# -*- coding: utf-8 -*-
"""Сквозной срез (Task 1.8): настоящий `CameraDevicePlugin` + фейк порта + настоящий `SourceProducer`.

Без моков framework: плагин создаётся как в процессе (`PluginContext` над `MockProcessServices` из
`plugins.testing` — штатный тестовый двойник сервисов), item отправляет настоящий `SourceProducer`.
Поток теста — daemon, ожидание только с дедлайном (`join(timeout)`): зависший плагин не вешает набор.
Ожидаемые значения — литералы из ACCEPTANCE задачи.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing.fake_port import make_port

PROCESS_NAME = "cam_fake"
ITEM_KEYS = {"frame", "camera_id", "device_id", "seq_id", "frame_id", "timestamp", "ts", "pixel_format"}


class _Rig:
    """Плагин + фейковый порт + `SourceProducer` в daemon-потоке; собранные item лежат в `items`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, **cfg) -> None:
        self.port = make_port(frame_period_s=0.02)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        config = {"auto_start": True, "camera_id": 3, **cfg}
        services = MockProcessServices(name=PROCESS_NAME, config=config)
        self.ctx = PluginContext(services=services, config=config)
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)
        self.plugin.start(self.ctx)
        self.items: list[dict] = []
        self.stop = threading.Event()
        producer = SourceProducer(
            self.plugin,
            None,
            lambda target, msg: self.items.append(msg["data"]),
            ["display"],
            target_fps=50,
        )
        self.thread = threading.Thread(target=producer.run_loop, args=(self.stop, threading.Event()), daemon=True)
        self.thread.start()

    def wait_items(self, count: int, timeout: float = 2.0) -> None:
        end = time.monotonic() + timeout
        while len(self.items) < count and time.monotonic() < end:
            time.sleep(0.01)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(2.0)
        self.plugin.shutdown(self.ctx)


@pytest.fixture
def rig(monkeypatch):
    made: list[_Rig] = []

    def factory(**cfg) -> _Rig:
        r = _Rig(monkeypatch, **cfg)
        made.append(r)
        return r

    yield factory
    for r in made:
        r.close()


def test_auto_start_даёт_item_с_frame_и_seq_id(rig):
    r = rig()
    time.sleep(0.5)
    r.wait_items(2)
    assert len(r.items) >= 1
    first = r.items[0]
    assert ITEM_KEYS <= set(first)
    assert first["camera_id"] == 3
    assert first["device_id"] == "FAKE-0001"
    assert first["pixel_format"] == "mono8"
    assert first["frame"].shape == (2, 4)  # фейк отдаёт кадр 4x2 mono8
    seqs = [item["seq_id"] for item in r.items]
    assert len(seqs) >= 2
    assert all(b > a for a, b in zip(seqs, seqs[1:], strict=False)), seqs


def test_release_останавливает_поток(rig):
    r = rig()
    r.wait_items(1)
    assert r.items, "поток чтения не отдал ни одного кадра"
    result: dict = {}
    t0 = time.monotonic()
    worker = threading.Thread(target=lambda: result.update(r.plugin.cmd_release_device({})), daemon=True)
    worker.start()
    worker.join(1.0)
    assert not worker.is_alive(), "release_device не вернулся за 1 с"
    assert time.monotonic() - t0 <= 1.0
    assert result["status"] == "ok"
    closes = [c for c in r.port.calls if c[0] == "close"]
    assert len(closes) == 1
    assert [c for c in r.port.calls if c[0] == "release"], "SDK не отпущен"
    assert r.port.sdk.refs == 0
    # после release кадры больше не идут
    before = len(r.port.calls)
    time.sleep(0.2)
    assert not [c for c in r.port.calls[before:] if c[0] == "get_frame"]


def test_без_auto_start_прибор_не_берётся_до_команды(rig):
    r = rig(auto_start=False)
    time.sleep(0.15)
    assert r.items == []
    assert not [c for c in r.port.calls if c[0] == "open"]
    assert r.plugin.cmd_take_device({})["status"] == "ok"
    r.wait_items(1)
    assert r.items


def test_frames_публикуется_метрикой(rig):
    r = rig()
    r.wait_items(3)
    status = r.plugin.cmd_get_status({})
    assert status["status"] == "ok"
    assert status["frames"] >= 3
    assert status["device_state"] == "grabbing"


def test_commands_содержит_take_device():
    assert {"take_device", "release_device", "get_status"} <= set(CameraDevicePlugin.commands)
