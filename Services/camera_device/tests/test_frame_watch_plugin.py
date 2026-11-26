# -*- coding: utf-8 -*-
"""Тесты автора W2-t2: плагин камеры и «триггер без кадра» (настоящие плагин, сеанс, `WorkerManager`, фейк порта).

Дерево — маленький приёмник `merge` (верхние ключи узла плагина), метрики — настоящее `PluginLevels`.
`produce()` зовёт сам тест; все циклы с дедлайном.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.frame_watch import FrameWatch
from Services.camera_device.interface import PortError
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port

_CFG = {
    "auto_start": False,
    "device_select": "serial",
    "device_serial": "FAKE-0001",
    "timeout_ms": 100,
    "frame_watch": "message",
    "frame_watch_deadline_ms": 200,
}
_RECONNECT = {"reconnect": True, "link_silence_s": 0.5, "reconnect_interval_s": 0.5}


class _Node:
    """Приёмник `state_proxy`: верхние ключи узла плагина."""

    def __init__(self) -> None:
        self.data: dict = {}

    def merge(self, path: str, data: dict) -> None:
        self.data.update(data)

    def delete(self, path: str) -> None:
        pass


class _Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, port: Any, take: bool = True, **cfg: Any) -> None:
        config = {**_CFG, **cfg}
        self.port = port
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        self.services = MockProcessServices(name="cam", config=config, plugin_levels=PluginLevels())
        self.services.worker_manager = self.workers = WorkerManager("test_frame_watch_plugin")
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.ctx.state_proxy = self.tree = _Node()
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)
        if take:
            self.take()

    def take(self) -> None:
        assert self.plugin.cmd_take_device({})["status"] == "ok"

    @property
    def block(self) -> dict:
        return self.tree.data.get("frame_watch") or {}

    def drive(self, seconds: float, until: Callable[[], bool] | None = None) -> None:
        """`produce()` каждые 10 мс `seconds` секунд; с `until` — до условия, не дождались — падение."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.plugin.produce()
            if until is not None and until():
                return
            time.sleep(0.01)
        assert until is None, f"не дождались за {seconds} с; блок {self.block}"

    def unplug(self) -> None:
        self.drive(0.1)
        self.port.disconnect()
        self.drive(0.2)  # кадр, летевший в момент обрыва, дошёл

    def metric(self) -> Any:
        return self.services.plugin_levels.publications().get("camera_device", {}).get("trigger_missed")

    def lines(self, level: str, part: str) -> list[str]:
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and part in e["msg"]]

    def seen(self) -> None:
        assert self.plugin.cmd_trigger_seen({}) == {"success": True}

    def miss(self, total: int) -> None:
        self.seen()
        self.drive(3.0, lambda: self.block.get("misses") == total)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(port: Any = None, **cfg: Any) -> _Rig:
        rig = _Rig(monkeypatch, port or fake_port.make_port(frame_period_s=0.01), **cfg)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.plugin.shutdown(rig.ctx)
        rig.workers.stop_all_workers(2.0)


def _gated_port() -> tuple[Any, dict]:
    """Фейк, отдающий кадр только после `execute`; `state["fail"]` — `execute` бросает."""
    port = fake_port.make_port()
    state = {"permits": 0, "delivered": 0, "fail": False, "silent": False}
    get_frame, execute = port.get_frame, port.execute

    def gated_get_frame(timeout_ms: int) -> Any:
        if not state["permits"]:
            time.sleep(0.005)
            return None
        state["permits"] -= 1
        frame = get_frame(timeout_ms)
        state["delivered"] += 1
        return frame

    def gated_execute(binding: Any) -> None:
        execute(binding)
        if state["fail"]:
            raise PortError("network", "execute")
        if not state["silent"]:
            state["permits"] += 1  # `execute` и `get_frame` зовёт один поток-владелец

    port.get_frame, port.execute = gated_get_frame, gated_execute
    return port, state


def test_message_without_frame_opens_miss(make, monkeypatch):
    monkeypatch.setattr(plugin_base, "_TICK_S", 5.0)  # смена `open_miss` обязана дойти раньше окна
    rig = make()
    rig.unplug()
    rig.seen()
    rig.drive(2.0, lambda: rig.block.get("open_miss") is True)
    assert (rig.block["misses"], rig.block["source"], rig.block["deadline_ms"]) == (1, "message", 200)
    rig.drive(8.0, lambda: rig.metric() == 1)
    assert len(rig.lines("WARNING", "триггер без кадра: срок 200 мс")) == 1


def test_frame_closes_miss(make):
    rig = make(**_RECONNECT)
    rig.unplug()
    rig.miss(1)
    rig.drive(6.0, lambda: rig.tree.data["link"]["state"] == "lost")
    rig.port.restore()
    rig.drive(8.0, lambda: rig.block.get("open_miss") is False)
    assert rig.block["misses"] == 1
    assert len(rig.lines("INFO", "пропущено 1")) == 1


def test_free_run_trigger_with_frame_no_miss(make):
    rig = make()
    rig.drive(0.2)
    rig.seen()
    rig.drive(1.0)
    rig.drive(3.0, lambda: rig.block.get("triggers") == 1)
    assert rig.block["misses"] == 0


def test_software_source_counts_trigger_software(make):
    port, state = _gated_port()
    rig = make(port, frame_watch="software", frame_watch_deadline_ms=1000)
    for number in range(1, 21):
        assert rig.plugin.cmd_trigger_software({}) == {"success": True}
        rig.drive(2.0, lambda: state["delivered"] >= number)
    rig.drive(1.5)
    assert (rig.block["triggers"], rig.block["misses"]) == (20, 0)
    assert rig.plugin.cmd_trigger_seen({}) == {"success": False, "error": "trigger_seen: frame_watch не message"}
    state["silent"] = True
    assert rig.plugin.cmd_trigger_software({}) == {"success": True}  # этот импульс ждёт кадра
    state["fail"] = True
    assert rig.plugin.cmd_trigger_software({})["success"] is False  # отозван только свой
    rig.drive(5.0, lambda: rig.block.get("misses") == 1)
    assert rig.block["triggers"] == 21


def test_pulses_before_run_dropped(make):
    rig = make()
    rig.unplug()
    rig.plugin.pause(rig.ctx)
    rig.seen()
    rig.plugin.resume(rig.ctx)
    time.sleep(0.4)
    rig.drive(1.2)
    assert (rig.block["triggers"], rig.block["misses"]) == (0, 0)


def test_stall_keeps_miss(make):
    rig = make()
    rig.unplug()
    rig.seen()
    time.sleep(1.2)
    rig.plugin.produce()
    assert (rig.block["misses"], rig.block["open_miss"]) == (1, True)


def test_reconnect_without_frame_keeps_open_miss(make):
    port, state = _gated_port()  # разрешений на кадр никто не даёт: камера по триггеру без импульсов на приборе
    rig = make(port, trigger_managed=True, trigger_mode="On", trigger_source="Line0", **_RECONNECT)
    rig.drive(0.1)
    port.disconnect()
    rig.drive(6.0, lambda: rig.tree.data["link"]["state"] == "lost")
    rig.miss(1)
    port.restore()
    rig.drive(8.0, lambda: rig.tree.data["link"]["state"] != "lost")
    rig.drive(1.3)
    assert (rig.tree.data["state"], state["delivered"]) == ("grabbing", 0)
    assert (rig.block["open_miss"], rig.block["misses"]) == (True, 1)


def test_reset_stats_resets_counts(make):
    rig = make()
    rig.unplug()
    rig.miss(1)
    assert rig.plugin.cmd_reset_stats({}) == {"success": True}
    assert rig.block == {
        "source": "message",
        "deadline_ms": 200,
        "triggers": 0,
        "misses": 0,
        "open_miss": False,
        "last_miss_ts": None,
    }  # открытый эпизод закрылся — дерево обновлено сразу, без `produce()`
    rig.drive(1.2)
    assert rig.metric() == 0
    assert rig.lines("INFO", "кадр после пропуска триггера") == []


def test_off_publishes_off_block_and_refuses(make, monkeypatch):
    polls: list[float] = []
    monkeypatch.setattr(FrameWatch, "poll", lambda self, now: polls.append(now) or 0)
    rig = make(frame_watch="off")
    assert rig.plugin.cmd_trigger_seen({})["success"] is False
    rig.drive(1.2)
    assert rig.block == {
        "source": "off",
        "deadline_ms": 200,
        "triggers": 0,
        "misses": 0,
        "open_miss": False,
        "last_miss_ts": None,
    }
    assert rig.metric() == 0
    assert polls == []


def test_repeated_misses_one_warning(make):
    rig = make()
    rig.unplug()
    for total in (1, 2, 3):
        rig.miss(total)
    rig.drive(0.3)
    assert len(rig.lines("WARNING", "триггер без кадра")) == 1


def test_not_counted_before_first_take(make):
    rig = make(take=False)
    rig.seen()  # success, но камера ещё не должна работать
    rig.drive(0.5)
    assert rig.lines("WARNING", "триггер без кадра") == []
    rig.take()
    rig.drive(1.2)
    assert (rig.block["triggers"], rig.block["misses"], rig.block["open_miss"]) == (0, 0, False)


def test_not_counted_after_release(make):
    rig = make()
    assert rig.plugin.cmd_release_device({})["status"] == "ok"
    rig.seen()
    rig.drive(1.2)
    assert (rig.block["triggers"], rig.block["misses"], rig.block["open_miss"]) == (0, 0, False)
    assert rig.lines("WARNING", "триггер без кадра") == []


def test_not_armed_by_rejected_take(make):
    rig = make()
    assert rig.plugin.cmd_release_device({})["status"] == "ok"
    assert rig.plugin.cmd_take_device({"timeout_s": 3600})["status"] == "error"  # отказ по аргументам, до сеанса
    rig.seen()
    rig.drive(1.2)
    assert (rig.block["triggers"], rig.block["misses"]) == (0, 0)


def test_counted_while_lost(make):
    rig = make(**_RECONNECT)
    rig.unplug()
    rig.drive(6.0, lambda: rig.tree.data["link"]["state"] == "lost")
    rig.miss(1)
    assert (rig.block["triggers"], rig.block["misses"], rig.block["open_miss"]) == (1, 1, True)
