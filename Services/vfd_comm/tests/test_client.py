"""Тесты VfdClient.

Два уровня:
1. Юнит — против минимального стаба RegisterTransport (байты на проводе,
   порядок маркера, валидация, heartbeat-трекинг).
2. Интеграция моста — против FakeRobotTransport (фейк-робот с Lua-семантикой
   зеркала: обновление только по VFD_FLAG, заморозка без команд).
"""

from __future__ import annotations

import pytest

from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.vfd_comm.core.client import VfdClient
from Services.vfd_comm.core.config import VfdConfig
from Services.vfd_comm.core.registers import (
    REG_CMD_DIR,
    REG_CMD_FREQ,
    REG_CMD_RESET,
    REG_CMD_RUN,
    REG_ST_BASE,
    REG_VFD_FLAG,
    STATE_FWD,
    STATE_REV,
    STATE_STOP,
)
from Services.vfd_comm.errors import VfdBridgeStaleError, VfdFrequencyError


class StubTransport:
    """Минимальный стаб: хранит регистры, журналирует транзакции."""

    def __init__(self) -> None:
        self.holding: dict[int, int] = {}
        self.transactions: list[list[tuple]] = []

    @property
    def is_connected(self) -> bool:
        return True

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        return [self.holding.get(address + i, 0) for i in range(count)]

    def transaction(self, ops: list[tuple]) -> bool:
        self.transactions.append(list(ops))
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
def vfd(stub: StubTransport) -> VfdClient:
    return VfdClient(stub)


# --- юнит: байты на проводе ---


def test_run_wire_format_flag_last(vfd: VfdClient, stub: StubTransport) -> None:
    """Контракт с Lua: freq -> dir -> run -> FLAG ПОСЛЕДНИМ."""
    vfd.run(50.0)
    ops = stub.transactions[-1]
    assert ops == [
        ("w", REG_CMD_FREQ, 5000),
        ("w", REG_CMD_DIR, 0),
        ("w", REG_CMD_RUN, 1),
        ("w", REG_VFD_FLAG, 1),
    ]


def test_run_reverse_sets_dir(vfd: VfdClient, stub: StubTransport) -> None:
    vfd.run(10.0, reverse=True)
    assert ("w", REG_CMD_DIR, 1) in stub.transactions[-1]


def test_run_default_frequency(stub: StubTransport) -> None:
    vfd = VfdClient(stub, VfdConfig(default_freq_hz=15.0))
    vfd.run()
    assert ("w", REG_CMD_FREQ, 1500) in stub.transactions[-1]


def test_set_freq_on_the_fly(vfd: VfdClient, stub: StubTransport) -> None:
    vfd.set_freq(25.5)
    assert stub.transactions[-1] == [("w", REG_CMD_FREQ, 2550), ("w", REG_VFD_FLAG, 1)]


def test_stop_and_reset(vfd: VfdClient, stub: StubTransport) -> None:
    vfd.stop()
    assert stub.transactions[-1] == [("w", REG_CMD_RUN, 0), ("w", REG_VFD_FLAG, 1)]
    vfd.reset_fault()
    assert stub.transactions[-1] == [
        ("w", REG_CMD_RUN, 0),
        ("w", REG_CMD_RESET, 1),
        ("w", REG_VFD_FLAG, 1),
    ]


def test_frequency_out_of_range_rejected(vfd: VfdClient) -> None:
    with pytest.raises(VfdFrequencyError):
        vfd.run(60.0)  # дефолтный максимум 50
    with pytest.raises(VfdFrequencyError):
        vfd.set_freq(-1.0)


def test_read_status_parses_mirror(vfd: VfdClient, stub: StubTransport) -> None:
    stub.holding.update(
        {
            REG_ST_BASE + 0: 1,
            REG_ST_BASE + 1: 5000,
            REG_ST_BASE + 2: 150,
            REG_ST_BASE + 3: 5400,
            REG_ST_BASE + 4: 0,
            REG_ST_BASE + 5: STATE_FWD,
            REG_ST_BASE + 6: 77,
            REG_ST_BASE + 7: 3,
        }
    )
    st = vfd.read_status()
    assert st.running and not st.reverse and not st.has_fault
    assert st.out_freq_hz == pytest.approx(50.0)
    assert st.current_a == pytest.approx(15.0)
    assert st.dcbus_v == pytest.approx(540.0)
    assert st.heartbeat == 77 and st.comm_errors == 3


def test_status_fault_detection(vfd: VfdClient, stub: StubTransport) -> None:
    stub.holding[REG_ST_BASE + 4] = 0x0021
    assert vfd.read_status().has_fault


# --- heartbeat-трекинг / живость моста ---


def test_stale_bridge_detected(stub: StubTransport) -> None:
    """heartbeat не растёт -> после stale_polls_limit опросов ensure_alive бросает."""
    vfd = VfdClient(stub, VfdConfig(stale_polls_limit=3))
    stub.holding[REG_ST_BASE + 6] = 10  # heartbeat заморожен
    for _ in range(4):
        vfd.poll()
    with pytest.raises(VfdBridgeStaleError, match="заморожено"):
        vfd.ensure_alive()


def test_alive_bridge_resets_counter(stub: StubTransport) -> None:
    vfd = VfdClient(stub, VfdConfig(stale_polls_limit=2))
    hb = 0

    real_read = stub.read_registers

    def reading(address: int, count: int = 1) -> list[int]:
        nonlocal hb
        hb += 1
        stub.holding[REG_ST_BASE + 6] = hb  # мост жив: hb растёт
        return real_read(address, count)

    stub.read_registers = reading  # type: ignore[method-assign]
    for _ in range(5):
        vfd.poll()
    vfd.ensure_alive()  # не бросает


# --- интеграция: мост через фейк-робота ---


@pytest.fixture
def bridge() -> FakeRobotTransport:
    transport = FakeRobotTransport(RobotSimCore())
    transport.connect()
    return transport


def test_bridge_run_updates_mirror(bridge: FakeRobotTransport) -> None:
    """Полный путь моста: команда -> mailbox -> «Lua» -> зеркало."""
    vfd = VfdClient(bridge)
    vfd.run(50.0)
    st = vfd.poll()
    assert st.running
    assert st.out_freq_hz == pytest.approx(50.0)
    assert st.status_word == STATE_FWD


def test_bridge_stop_reflected(bridge: FakeRobotTransport) -> None:
    vfd = VfdClient(bridge)
    vfd.run(20.0)
    vfd.poll()
    vfd.stop()
    st = vfd.poll()
    assert not st.running
    assert st.status_word == STATE_STOP
    assert st.out_freq_hz == 0.0


def test_bridge_reverse(bridge: FakeRobotTransport) -> None:
    vfd = VfdClient(bridge)
    vfd.run(30.0, reverse=True)
    assert vfd.poll().status_word == STATE_REV


def test_bridge_mirror_frozen_without_pulse(bridge: FakeRobotTransport) -> None:
    """Семантика реального Lua: без пульса VFD_FLAG зеркало (hb) заморожено."""
    vfd = VfdClient(bridge)
    hb1 = vfd.poll().heartbeat
    hb2 = vfd.read_status().heartbeat  # без пульса
    hb3 = vfd.read_status().heartbeat
    assert hb1 == hb2 == hb3  # читаем — но зеркало стоит
    hb4 = vfd.poll().heartbeat  # пульс -> Lua обновил
    assert hb4 != hb3


def test_bridge_poll_keeps_command(bridge: FakeRobotTransport) -> None:
    """Пульс не меняет команду: ПЧ продолжает крутиться на той же частоте."""
    vfd = VfdClient(bridge)
    vfd.run(40.0)
    for _ in range(3):
        st = vfd.poll()
    assert st.running and st.out_freq_hz == pytest.approx(40.0)
