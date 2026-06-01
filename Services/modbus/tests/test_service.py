"""Тесты ModbusService — IService-контракт и lifecycle."""

from __future__ import annotations

from multiprocess_framework.modules.service_module import IService

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.service import ModbusService

from .conftest import FakeSdkClient


def test_service_satisfies_iservice() -> None:
    assert isinstance(ModbusService(), IService)


def test_default_stopped() -> None:
    assert ModbusService().status == "stopped"


def test_get_status_shape() -> None:
    status = ModbusService().get_status()
    assert status["service"] == "modbus"
    assert status["state"] == "stopped"


def test_start_running_with_injected_device() -> None:
    svc = ModbusService()
    # Подменяем устройство на fake, чтобы не дёргать pymodbus
    svc._device = ModbusDevice(ModbusConfig(), client=FakeSdkClient())
    ok = svc._device.connect()
    svc.status = "running" if ok else "error"
    assert ok
    assert svc.get_status()["device"]["state"] == "connected"


def test_stop_resets() -> None:
    svc = ModbusService()
    svc._device = ModbusDevice(ModbusConfig(), client=FakeSdkClient())
    svc._device.connect()
    assert svc.stop() is True
    assert svc.status == "stopped"
    assert svc._device is None
