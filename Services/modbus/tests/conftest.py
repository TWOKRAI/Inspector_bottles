"""Фикстуры тестов Modbus — fake sdk-клиент без pymodbus и железа."""

from __future__ import annotations

from typing import Any

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk.errors import ModbusConnectionError, ModbusIOError


class FakeSdkClient:
    """Имитация ModbusSdkClient в памяти.

    Хранит регистры/coils в dict, позволяет программировать сбои:
        fail_connect — connect() бросит ModbusConnectionError;
        fail_next_op — следующая операция бросит ModbusIOError.
    """

    def __init__(self, config: ModbusConfig | None = None) -> None:
        self.config = config
        self._connected = False
        self.holding: dict[int, int] = {}
        self.inputs: dict[int, int] = {}
        self.coils: dict[int, bool] = {}
        self.discrete: dict[int, bool] = {}
        self.fail_connect = False
        self.fail_next_op = False
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    # --- соединение ---
    def connect(self) -> bool:
        if self.fail_connect:
            raise ModbusConnectionError("fake: connect failed")
        self._connected = True
        return True

    def close(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _maybe_fail(self, op: str, *args: Any) -> None:
        self.calls.append((op, args))
        if self.fail_next_op:
            self.fail_next_op = False
            raise ModbusIOError(f"fake: {op} failed")

    # --- чтение ---
    def read_holding(self, address: int, count: int) -> list[int]:
        self._maybe_fail("read_holding", address, count)
        return [self.holding.get(address + i, 0) for i in range(count)]

    def read_input(self, address: int, count: int) -> list[int]:
        self._maybe_fail("read_input", address, count)
        return [self.inputs.get(address + i, 0) for i in range(count)]

    def read_coils(self, address: int, count: int) -> list[bool]:
        self._maybe_fail("read_coils", address, count)
        return [self.coils.get(address + i, False) for i in range(count)]

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        self._maybe_fail("read_discrete_inputs", address, count)
        return [self.discrete.get(address + i, False) for i in range(count)]

    # --- запись ---
    def write_register(self, address: int, value: int) -> None:
        self._maybe_fail("write_register", address, value)
        self.holding[address] = value

    def write_registers(self, address: int, values: list[int]) -> None:
        self._maybe_fail("write_registers", address, values)
        for i, v in enumerate(values):
            self.holding[address + i] = v

    def write_coil(self, address: int, value: bool) -> None:
        self._maybe_fail("write_coil", address, value)
        self.coils[address] = value


class FakeClock:
    """Управляемые монотонные часы для детерминированных тестов uptime."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def config() -> ModbusConfig:
    return ModbusConfig(host="127.0.0.1", port=5020, unit_id=1)


@pytest.fixture
def fake_client() -> FakeSdkClient:
    return FakeSdkClient()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def device(config: ModbusConfig, fake_client: FakeSdkClient, clock: FakeClock):
    """ModbusDevice поверх fake-клиента и управляемых часов."""
    return ModbusDevice(config, client=fake_client, clock=clock)
