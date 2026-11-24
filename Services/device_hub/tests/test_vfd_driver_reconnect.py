"""Реконнект VfdDriver: последняя частота живёт дольше VfdClient.

Реальные VfdDriver + VfdClient поверх стаба транспорта (клиент пересоздаётся в connect()).
Наблюдаемый эффект — что реально записал стаб в cmd_freq / cmd_run.
"""

from __future__ import annotations

import pytest

from Services.vfd_comm.core.registers import REG_CMD_FREQ, REG_CMD_RUN

from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.registry.entry import DeviceEntry


class StubTransport:
    """Минимальный RegisterTransport: хранит записанные регистры."""

    def __init__(self) -> None:
        self.holding: dict[int, int] = {}

    @property
    def is_connected(self) -> bool:
        return True

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        return [self.holding.get(address + i, 0) for i in range(count)]

    def transaction(self, ops: list[tuple]) -> bool:
        for kind, addr, value in ops:
            if kind == "w":
                self.holding[addr] = int(value)
            else:
                for i, v in enumerate(value):
                    self.holding[addr + i] = int(v)
        return True


@pytest.fixture
def stub() -> StubTransport:
    return StubTransport()


@pytest.fixture
def driver(stub: StubTransport) -> VfdDriver:
    entry = DeviceEntry(
        id="vfd_belt",
        name="ПЧ лента",
        kind="vfd",
        protocol="gd20_bridge",
        transport={"type": "bridge", "bridge": "robot_main"},
        params={"freq_max_hz": 50.0, "default_freq_hz": 10.0},
    )
    d = VfdDriver(entry, protocol=None, transport=stub)
    assert d.connect()
    return d


def _run_without_freq(driver: VfdDriver, stub: StubTransport) -> int:
    """Пуск без частоты через драйвер; возвращает cmd_freq, реально записанный стабом."""
    stub.holding[REG_CMD_RUN] = 0
    assert driver.call("run", {})["status"] == "ok"
    assert stub.holding[REG_CMD_RUN] == 1
    return stub.holding[REG_CMD_FREQ]


def test_last_freq_survives_disconnect_connect(driver: VfdDriver, stub: StubTransport) -> None:
    """set_freq(31) -> stop -> disconnect+connect -> run без частоты стартует на 31 Гц (3100), не на 10."""
    assert driver.call("set_freq", {"freq_hz": 31.0})["status"] == "ok"
    assert driver.call("stop", {})["status"] == "ok"
    driver.disconnect()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 3100


def test_last_freq_survives_set_degraded_connect(driver: VfdDriver, stub: StubTransport) -> None:
    """То же при отпадании носителя: set_degraded() вместо disconnect()."""
    assert driver.call("run", {"freq_hz": 31.0})["status"] == "ok"
    assert driver.call("stop", {})["status"] == "ok"
    assert driver.set_degraded()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 3100


def test_last_freq_survives_two_reconnects(driver: VfdDriver, stub: StubTransport) -> None:
    """Цепочка клиентов: disconnect (31 Гц) -> новая частота 25 -> set_degraded -> run без частоты: 25 Гц (2500)."""
    driver.call("set_freq", {"freq_hz": 31.0})
    driver.disconnect()
    driver.connect()
    driver.call("set_freq", {"freq_hz": 25.0})
    driver.set_degraded()
    driver.connect()
    assert _run_without_freq(driver, stub) == 2500


def test_first_run_without_any_freq_uses_default(driver: VfdDriver, stub: StubTransport) -> None:
    """Частоты не задавали ни разу (в т.ч. после реконнекта): пуск идёт на default_freq_hz (10 Гц -> 1000)."""
    assert _run_without_freq(driver, stub) == 1000
    driver.disconnect()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 1000


def test_zero_freq_is_not_carried_across_reconnect(driver: VfdDriver, stub: StubTransport) -> None:
    """set_freq(20) -> set_freq(0) -> реконнект -> run без частоты: 20 Гц (2000), ноль память не затёр."""
    driver.call("set_freq", {"freq_hz": 20.0})
    driver.call("set_freq", {"freq_hz": 0.0})
    assert stub.holding[REG_CMD_FREQ] == 0
    driver.disconnect()
    driver.connect()
    assert _run_without_freq(driver, stub) == 2000


def test_disconnect_without_client_is_safe(driver: VfdDriver, stub: StubTransport) -> None:
    """Повторный disconnect()/set_degraded() при уже отпущенном клиенте не падает и память не теряет."""
    driver.call("set_freq", {"freq_hz": 31.0})
    driver.disconnect()
    driver.disconnect()
    driver.set_degraded()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 3100


def test_reset_fault_clears_last_freq_across_reconnects(driver: VfdDriver, stub: StubTransport) -> None:
    """run(30) -> реконнект (память 30 перенесена) -> reset_fault -> реконнект -> run без частоты: 10 Гц (1000).

    Охрана «None не затирает» в драйвере оставила бы устаревшие 30 Гц и засеяла ими третьего клиента.
    """
    assert driver.call("run", {"freq_hz": 30.0})["status"] == "ok"
    driver.disconnect()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 3000  # память пережила первый реконнект
    assert driver.call("reset_fault", {})["status"] == "ok"
    driver.disconnect()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 1000


def test_stop_keeps_last_freq_across_reconnect(driver: VfdDriver, stub: StubTransport) -> None:
    """Обычный stop память не трогает и через реконнект: 25 Гц остаются (2500)."""
    driver.call("set_freq", {"freq_hz": 25.0})
    driver.call("stop", {})
    driver.set_degraded()
    assert driver.connect()
    assert _run_without_freq(driver, stub) == 2500
