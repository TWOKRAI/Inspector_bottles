# -*- coding: utf-8 -*-
"""Task 4c (слепые тесты по REDS 1-5): ключ ``run_locked_commands: [release_device, take_device]`` у узла камеры.

Настоящие объекты: ``CameraDevicePlugin`` (``driver: fake``) + ``PluginOrchestrator`` + ``CommandManager`` +
``RunFlag`` + настоящий ``WorkerManager`` (``MockWorkerManager`` без ``has_worker`` камеру не поднимет).
Команды зовутся только через ``cm.handle_command`` (внутренний dict; конверт роутера здесь не виден).
``pdef`` собран вручную с теми же ключами, что в рецепте (слой: ``multiprocess_prototype`` не импортируется).
Механизм запирания лежит в ``main``, поэтому тесты зелёные до кода задачи; их непустота доказывается инъекциями
в ``_LOCKED`` и в проводку флага (см. отчёт тестера). Вызов, который может зависнуть, идёт в daemon-потоке с
дедлайном. Ожидаемые значения — литералы из REDS.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.process_manager_module.core.run_flag import RunFlag
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.plugin_base import CameraDevicePlugin

pytestmark = pytest.mark.timeout(60)

_JOIN_S = 30.0
_REFUSAL = {"status": "error", "error": "running", "message": "сначала ОСТАНОВИТЬ"}
_LOCKED = ["release_device", "take_device"]  # то же, что ключ в рецепте camera_device_demo.yaml


def _pdef(locked: list[str] | None = None, *, with_key: bool = True) -> dict[str, Any]:
    pdef: dict[str, Any] = {
        "plugin_class": "Services.camera_device.plugin_base.CameraDevicePlugin",
        "plugin_name": "camera_device",
        "driver": "fake",
        "camera_id": 0,
        "device_select": "first",
    }
    if with_key:
        pdef["run_locked_commands"] = list(_LOCKED if locked is None else locked)
    return pdef


def _in_daemon(fn: Callable[[], Any], deadline_s: float = _JOIN_S) -> Any:
    """``fn`` в daemon-потоке с дедлайном; исключение потока пробрасывается, результат возвращается."""
    box: dict[str, Any] = {}

    def go() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["exc"] = exc

    th = threading.Thread(target=go, daemon=True, name="camera-run-locked-scenario")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"сценарий завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


class _Rig:
    def __init__(self, pdef: dict[str, Any]) -> None:
        self.services = MockProcessServices(name="cam_run_locked")
        self.cm = CommandManager("cam_run_locked_cm")
        self.cm.initialize()
        self.services.command_manager = self.cm
        self.flag = RunFlag(False)
        self.services._run_active = self.flag
        self.wm = WorkerManager("cam_run_locked_wm")
        self.services.worker_manager = self.wm
        self.orch = PluginOrchestrator(services=self.services)
        self.orch.load_and_configure_managers([pdef])
        self.orch.boot()

    @property
    def plugin(self) -> CameraDevicePlugin:
        return self.orch.plugins[0]

    def call(self, command: str, data: dict | None = None) -> Any:
        return self.cm.handle_command({"command": command, "data": {} if data is None else data})

    def state(self) -> str:
        return self.call("get_status")["state"]

    def close(self) -> None:
        try:
            self.orch.shutdown()
        finally:
            self.wm.stop_all_workers(2.0)


def _scenario(pdef: dict[str, Any], body: Callable[[_Rig], None]) -> None:
    """Собрать rig, выполнить ``body`` и снять rig; всё в daemon-потоке с дедлайном."""

    def run() -> None:
        rig = _Rig(pdef)
        try:
            body(rig)
        finally:
            rig.close()

    _in_daemon(run)


# --------------------------------------------------------------------------- #
# REDS 1: флаг СНЯТ — обе команды исполняются
# --------------------------------------------------------------------------- #


def test_release_device_runs_when_flag_clear() -> None:
    def body(rig: _Rig) -> None:
        assert rig.state() == "grabbing", "предусловие: после boot() камера открыта"
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.state() == "closed"

    _scenario(_pdef(), body)


def test_take_device_runs_when_flag_clear() -> None:
    def body(rig: _Rig) -> None:
        assert rig.call("release_device")["status"] == "ok"
        assert rig.state() == "closed", "предусловие: камера закрыта"
        reply = rig.call("take_device")
        assert reply["status"] == "ok", reply
        assert rig.state() == "grabbing"

    _scenario(_pdef(), body)


# --------------------------------------------------------------------------- #
# REDS 2: флаг ВЗВЕДЁН — обе команды отказаны литералом, состояние не меняется
# --------------------------------------------------------------------------- #


def test_release_device_refused_when_flag_set() -> None:
    def body(rig: _Rig) -> None:
        assert rig.state() == "grabbing", "предусловие: камера открыта"
        rig.flag.set()
        assert rig.call("release_device") == _REFUSAL
        assert rig.state() == "grabbing"

    _scenario(_pdef(), body)


def test_take_device_refused_when_flag_set() -> None:
    def body(rig: _Rig) -> None:
        assert rig.call("release_device")["status"] == "ok"  # флаг снят
        assert rig.state() == "closed", "предусловие: камера закрыта"
        rig.flag.set()
        assert rig.call("take_device") == _REFUSAL
        assert rig.state() == "closed"

    _scenario(_pdef(), body)


# --------------------------------------------------------------------------- #
# REDS 3: флаг ВЗВЕДЁН — остальные команды работают (живая правка 2.4 остаётся)
# --------------------------------------------------------------------------- #

_APPLY_DATA = {"params": {"exposure_time": 5000.0}}


@pytest.mark.parametrize(
    ("command", "data", "expected"),
    [
        ("get_status", None, {"status": "ok"}),
        ("read_params", None, {"success": True}),
        ("describe_params", None, {"success": True}),
        ("list_devices", None, {"success": True}),
        ("trigger_software", None, {"success": True}),
    ],
    ids=["get_status", "read_params", "describe_params", "list_devices", "trigger_software"],
)
def test_unlocked_command_succeeds_when_flag_set(command: str, data: dict | None, expected: dict) -> None:
    def body(rig: _Rig) -> None:
        assert rig.state() == "grabbing", "предусловие: камера открыта"
        rig.flag.set()
        reply = rig.call(command, data)
        for key, value in expected.items():
            assert reply[key] == value and type(reply[key]) is type(value), (command, reply)

    _scenario(_pdef(), body)


def test_reset_stats_succeeds_when_flag_set() -> None:
    def body(rig: _Rig) -> None:
        rig.flag.set()
        assert rig.call("reset_stats") == {"success": True}

    _scenario(_pdef(), body)


def test_apply_params_succeeds_when_flag_set() -> None:
    def body(rig: _Rig) -> None:
        assert rig.state() == "grabbing", "предусловие: камера открыта"
        rig.flag.set()
        reply = rig.call("apply_params", _APPLY_DATA)
        assert reply == {"success": True, "applied": ["exposure_time"], "on_device": True}

    _scenario(_pdef(), body)


# --------------------------------------------------------------------------- #
# REDS 4: контроль — без ключа взведённый флаг ничего не запирает
# --------------------------------------------------------------------------- #


def test_release_device_runs_without_key_when_flag_set() -> None:
    def body(rig: _Rig) -> None:
        assert rig.state() == "grabbing", "предусловие: камера открыта"
        rig.flag.set()
        reply = rig.call("release_device")
        assert reply["status"] == "ok", reply
        assert rig.state() == "closed"

    _scenario(_pdef(with_key=False), body)


# --------------------------------------------------------------------------- #
# REDS 5: reset_stats при взведённом флаге исполняется (frames обнуляется)
# --------------------------------------------------------------------------- #


def test_reset_stats_zeroes_frames_when_flag_set() -> None:
    def body(rig: _Rig) -> None:
        end = time.monotonic() + 10.0
        while rig.call("get_status")["frames"] < 1 and time.monotonic() < end:
            rig.plugin.produce()
            time.sleep(0.01)
        assert rig.call("get_status")["frames"] >= 1, "предусловие: хотя бы один кадр прошёл через produce()"
        rig.flag.set()
        assert rig.call("reset_stats") == {"success": True}
        assert rig.call("get_status")["frames"] == 0

    _scenario(_pdef(), body)
