"""Тесты GenericModbusDriver: tick читает r-записи, write валидирует access/min/max."""

from __future__ import annotations

import threading

import pytest

from Services.modbus.core.protocol_file import DeviceProtocol, RegisterMeta
from Services.modbus.core.register_map import Reg, RegisterMap

from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock


class FakeRegisterTransport:
    """Минимальный фейковый RegisterTransport для тестов generic_modbus."""

    def __init__(self) -> None:
        self._connected = True
        self._regs: dict[int, int] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        return [self._regs.get(address + i, 0) for i in range(count)]

    def transaction(self, ops: list[tuple]) -> bool:
        for kind, address, value in ops:
            if kind == "w":
                self._regs[address] = int(value)
            elif kind == "wm":
                for i, v in enumerate(value):
                    self._regs[address + i] = int(v)
        return True


def _make_protocol() -> DeviceProtocol:
    """Протокол с r, w, rw записями для тестов."""
    rmap = RegisterMap(
        {
            "temp": Reg(0x100),
            "setpoint": Reg(0x200, scale=100),
            "control": Reg(0x300),
        }
    )
    meta = {
        "temp": RegisterMeta(name="temp", kind="reg", access="r", unit="°C"),
        "setpoint": RegisterMeta(
            name="setpoint",
            kind="reg",
            access="rw",
            scale=100,
            unit="°C",
            min=0,
            max=100,
        ),
        "control": RegisterMeta(name="control", kind="reg", access="w"),
    }
    return DeviceProtocol(
        name="test_sensor",
        kind="generic_modbus",
        description="Тестовый датчик",
        register_map=rmap,
        meta=meta,
    )


@pytest.fixture
def entry() -> DeviceEntry:
    return DeviceEntry(
        id="sensor_1",
        name="Датчик",
        kind="generic_modbus",
        protocol="test_sensor",
        transport={"type": "tcp"},
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def transport() -> FakeRegisterTransport:
    return FakeRegisterTransport()


@pytest.fixture
def driver(entry, transport, clock) -> GenericModbusDriver:
    proto = _make_protocol()
    d = GenericModbusDriver(
        entry,
        proto,
        transport=transport,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    d.connect()
    return d


class TestGenericModbusTick:
    """tick() — чтение r/rw-записей протокола."""

    def test_tick_reads_r_and_rw(self, driver, transport) -> None:
        """tick читает temp (r) и setpoint (rw), НЕ control (w)."""
        transport._regs[0x100] = 250  # temp = 250 (без scale)
        transport._regs[0x200] = 5000  # setpoint = 50.0 (scale=100)

        stop = threading.Event()
        snap = driver.tick(stop)

        assert snap is not None
        assert snap["quality"] == "good"
        assert "values" in snap
        values = snap["values"]
        # temp прочитан
        assert "temp" in values
        # setpoint прочитан
        assert "setpoint" in values
        # control (w-only) НЕ прочитан
        assert "control" not in values

    def test_tick_disconnected(self, entry, clock) -> None:
        """tick без соединения -> bad."""
        proto = _make_protocol()
        d = GenericModbusDriver(entry, proto, clock=clock.clock, sleep=clock.sleep)
        stop = threading.Event()
        snap = d.tick(stop)
        assert snap["quality"] == "bad"


class TestGenericModbusPartialReadQuality:
    """A-13 (bug-hunt 2026-07-20): раньше quality="good" ставился при ЛЮБОМ
    непустом values — частичное чтение (1 регистр из 2/10) маскировалось под
    полный успех. Теперь good — только полный набор r/rw-записей."""

    def test_partial_read_is_stale_not_good(self, driver, transport, monkeypatch) -> None:
        """1 из 2 r/rw записей провалилась -> quality=stale, значения частичные."""
        transport._regs[0x100] = 250  # temp
        transport._regs[0x200] = 5000  # setpoint

        original_read = driver.protocol.register_map.read

        def flaky_read(device, name):
            if name == "setpoint":
                raise RuntimeError("модбас оборвался на этом регистре")
            return original_read(device, name)

        monkeypatch.setattr(driver.protocol.register_map, "read", flaky_read)

        stop = threading.Event()
        snap = driver.tick(stop)

        assert snap is not None
        assert snap["quality"] == "stale"
        assert "temp" in snap["values"]
        assert "setpoint" not in snap["values"]

    def test_full_read_failure_is_bad(self, driver, transport, monkeypatch) -> None:
        """Все r/rw записи провалились -> quality=bad (не good, не stale)."""

        def always_fail(device, name):
            raise RuntimeError("транспорт недоступен")

        monkeypatch.setattr(driver.protocol.register_map, "read", always_fail)

        stop = threading.Event()
        snap = driver.tick(stop)

        assert snap is not None
        assert snap["quality"] == "bad"
        assert snap["values"] == {}


class TestGenericModbusCallRead:
    """call read — чтение одного регистра."""

    def test_read_ok(self, driver, transport) -> None:
        transport._regs[0x100] = 42
        result = driver.call("read", {"name": "temp"})
        assert result["status"] == "ok"
        assert result["name"] == "temp"

    def test_read_write_only_rejected(self, driver) -> None:
        """Чтение w-only -> ошибка."""
        result = driver.call("read", {"name": "control"})
        assert result["status"] == "error"
        assert "только на запись" in result["message"]

    def test_read_unknown_name(self, driver) -> None:
        result = driver.call("read", {"name": "nonexistent"})
        assert result["status"] == "error"
        assert "не найдена" in result["message"]


class TestGenericModbusCallWrite:
    """call write — запись с валидацией."""

    def test_write_ok(self, driver, transport) -> None:
        result = driver.call("write", {"values": {"setpoint": 42.0}})
        assert result["status"] == "ok"
        assert "setpoint" in result["written"]

    def test_write_readonly_rejected(self, driver) -> None:
        result = driver.call("write", {"values": {"temp": 99}})
        assert result["status"] == "error"
        assert "только на чтение" in result["message"]

    def test_write_over_max_rejected(self, driver) -> None:
        result = driver.call("write", {"values": {"setpoint": 150.0}})
        assert result["status"] == "error"
        assert "150.0" in result["message"]

    def test_write_under_min_rejected(self, driver) -> None:
        result = driver.call("write", {"values": {"setpoint": -5.0}})
        assert result["status"] == "error"
        assert "-5.0" in result["message"]

    def test_write_unknown_name(self, driver) -> None:
        result = driver.call("write", {"values": {"nonexistent": 1}})
        assert result["status"] == "error"
        assert "не найдена" in result["message"]

    def test_write_empty_values(self, driver) -> None:
        result = driver.call("write", {"values": {}})
        assert result["status"] == "error"

    def test_unknown_op(self, driver) -> None:
        result = driver.call("delete", {})
        assert result["status"] == "error"
