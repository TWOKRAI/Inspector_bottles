# -*- coding: utf-8 -*-
"""Проводка 2.4b: настоящие `RegistersManager` и `PluginOrchestrator._on_register_update` -> журнал фейк-порта.

Правка идёт ровно тем путём, каким её шлёт GUI: `register_update` -> `_on_register_update` в «системном» потоке ->
`RegistersManager.set_field_value` -> колбэк подписки плагина -> `session.apply` -> поток-владелец -> порт.
Фейками остаются только порт и менеджер воркеров процесса (`MockProcessServices`). Ожидаемые значения — литералы.
Ожидание эффекта — с дедлайном; «ничего не случилось» подтверждает сторожевая правка после (подписка жива).
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health import get_or_create_health_state
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.testing.fake_port import make_port

pytestmark = pytest.mark.timeout(60)

REG = "camera_device"
CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}
_NOISE = frozenset({"get_frame", "describe_param"})


class _Rig:
    """Настоящий плагин + `RegistersManager` + `PluginOrchestrator` (обработчик `register_update`) + фейк порта."""

    def __init__(self, monkeypatch, port) -> None:
        self.port = port
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        self.services = MockProcessServices(name="cam_wire", config=CFG)
        self.wm = WorkerManager("test_cam_wire")
        self.services.worker_manager = self.wm
        self.rm = RegistersManager(registers={REG: CameraDeviceRegisters()})
        self.ctx = PluginContext(services=self.services, config=CFG, registers=self.rm, plugin_name=REG)
        self.orch = PluginOrchestrator(self.services)
        self.orch._registers_manager = self.rm
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def register_update(self, field: str, value) -> dict:
        """`register_update` как из системного потока процесса: отдельный поток, результат обработчика."""
        box: dict = {}

        def system_thread() -> None:
            box["result"] = self.orch._on_register_update({"data": {"register": REG, "field": field, "value": value}})

        thread = threading.Thread(target=system_thread, name="system_sim", daemon=True)
        thread.start()
        thread.join(10.0)
        assert not thread.is_alive(), "обработчик register_update не вернулся за 10 с"
        return box["result"]

    def take(self) -> dict:
        return self.plugin.cmd_take_device({})

    def journal(self, start: int = 0) -> list[tuple]:
        return [(name, args) for name, args, _ in self.port.calls[start:] if name not in _NOISE]

    def close(self) -> None:
        self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    built: list[_Rig] = []

    def factory(port=None) -> _Rig:
        rig = _Rig(monkeypatch, port if port is not None else make_port(frame_period_s=0.02))
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.close()


def _wait(predicate, what: str, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"за {timeout} с не случилось: {what}")


def _wrote(rig: _Rig, start: int, value: float) -> bool:
    return ("set_param", ("ExposureTime", value)) in rig.journal(start)


def test_register_update_доходит_до_журнала_фейка(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    result = rig.register_update("exposure_time", 1200.0)

    assert result["success"] is True, result
    _wait(lambda: _wrote(rig, base, 1200.0), "set_param(ExposureTime, 1200.0) в журнале фейка")
    _wait(lambda: ("get_param", ("ExposureTime",)) in rig.journal(base), "обратное чтение узла")
    assert [name for name, _ in rig.journal(base)] == ["set_param", "get_param"], "лишние вызовы порта (stop_grabbing?)"


def test_неизвестная_policy_не_ломает_колбэк_и_следующая_правка_доходит(make, monkeypatch):
    rig = make()
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)
    with monkeypatch.context() as local:
        local.setattr(rig.plugin, "_apply_policy", lambda field: "bogus")
        result = rig.register_update("exposure_time", 1100.0)  # ValueError сеанса колбэк ловит сам
    assert result["success"] is True, result
    time.sleep(0.2)
    assert rig.journal(base) == [], "неизвестная policy дошла до порта"
    assert get_or_create_health_state(rig.services).snapshot()["errors"] == 1, "исключение не учтено как инцидент"

    rig.register_update("exposure_time", 1300.0)

    _wait(lambda: _wrote(rig, base, 1300.0), "следующая правка после отказа policy")


def test_повторный_configure_без_shutdown_не_двоит_set_param(make):
    rig = make()
    rig.plugin.configure(rig.ctx)  # второй configure того же плагина без shutdown
    # у `RegistersManager` нет публичного счёта подписчиков: `_field_observers` читаем напрямую (колбэк на поле — один)
    assert len(rig.rm._field_observers[(REG, "exposure_time")]) == 1, "подписки задвоились"
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    rig.register_update("exposure_time", 1250.0)

    _wait(lambda: _wrote(rig, base, 1250.0), "правка дошла")
    time.sleep(0.3)
    writes = [call for call in rig.journal(base) if call == ("set_param", ("ExposureTime", 1250.0))]
    assert len(writes) == 1, f"set_param вызван {len(writes)} раз(а): подписки задвоились"


def test_правка_до_take_device_ничего_не_ломает_и_входит_в_план_следующего_take(make):
    rig = make()

    result = rig.register_update("exposure_time", 1500.0)

    assert result["success"] is True, result
    assert rig.port.calls == [], "порт тронут до take_device"
    assert rig.take()["status"] == "ok"
    assert _wrote(rig, 0, 1500.0), rig.journal()


def test_правка_при_busy_и_closed_не_принимается_без_исключения(make):
    busy = make(make_port(busy_for_s=60.0))
    assert busy.take()["device_state"] == "busy"
    base = len(busy.port.calls)
    assert busy.register_update("exposure_time", 1400.0)["success"] is True
    time.sleep(0.2)
    assert ("set_param", ("ExposureTime", 1400.0)) not in busy.journal(base)

    closed = make()
    assert closed.take()["status"] == "ok"
    closed.plugin.cmd_release_device({})
    base = len(closed.port.calls)
    assert closed.register_update("exposure_time", 1450.0)["success"] is True
    time.sleep(0.2)
    assert closed.journal(base) == []
    assert get_or_create_health_state(closed.services).snapshot()["errors"] == 0, "отказ приёма не инцидент"


def test_после_shutdown_правка_не_доходит_даже_при_новом_захвате(make):
    rig = make()
    assert rig.take()["status"] == "ok"
    rig.plugin.shutdown(rig.ctx)
    rig.plugin.shutdown(rig.ctx)  # повторный shutdown — пустая операция
    assert rig.take()["status"] == "ok"  # сеанс снова идёт: если подписка жива, правка дошла бы до порта
    base = len(rig.port.calls)

    assert rig.register_update("exposure_time", 1350.0)["success"] is True

    time.sleep(0.4)
    assert rig.journal(base) == [], "подписка пережила shutdown"


def test_после_повторного_configure_и_shutdown_не_остаётся_подписок_первого_configure(make):
    """Колбэки первого `configure` не теряются: иначе после `shutdown` они бы пережили плагин (утечка подписок)."""
    rig = make()
    rig.plugin.configure(rig.ctx)
    rig.plugin.shutdown(rig.ctx)
    assert rig.take()["status"] == "ok"
    base = len(rig.port.calls)

    assert rig.register_update("exposure_time", 1360.0)["success"] is True

    time.sleep(0.4)
    assert rig.journal(base) == [], "подписка первого configure пережила shutdown"
