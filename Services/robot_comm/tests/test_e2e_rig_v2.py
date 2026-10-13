"""Тесты автора обвязки e2e v2 и хука ``trace_sc`` (T3.5, часть developer).

Purpose:
    Доказать хук ``trace_sc`` ядра sim (литерал строк ``SC rec`` / ``SC act`` и «выключен — вывод прежний»)
    и обвязку ``e2e_rig_v2``: ``free_port``, ``bounded``, ``pulse``, штампы ``RecordingCore``, живой стенд
    (ping, рестарт на том же порту), предъявление исключений тика на выходе и уборку при сбое подъёма.
    Ожидаемые значения — литералы брифа ``plans/robot-protocol-v2/tasks/T3.5.md``. Приёмка сценариев
    «клиент <-> sim» — не здесь (слепой тестер, ``test_sim_e2e_v2.py``).

Stability: lite
"""

from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace

import pytest

from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core import wire_v2
from Services.robot_comm.core.protocol_v2 import CONSTANTS, OP, REG
from Services.robot_comm.programs import Point, compile_program
from Services.robot_comm.programs.generators import return_slot
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.tests import e2e_rig_v2
from Services.robot_comm.tests.e2e_rig_v2 import (
    FORBIDDEN_PORTS,
    WS_PARAMS,
    E2eRig,
    RecordingCore,
    bounded,
    free_port,
    pulse,
)

__all__: list[str] = []

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="robot_comm недоступен (нет pymodbus)")

SLOT = Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
SC_LITERAL = [
    "[v2] SC rec id=1 i=1 kind=JOINT spd=80",
    "[v2] SC rec id=1 i=2 kind=LINE spd=80",
    "[v2] SC act id=1 i=2 act=DO_ON val=1",
    "[v2] SC rec id=1 i=3 kind=LINE spd=80",
    "[v2] SC act id=1 i=3 act=DELAY_MS val=400",
    "[v2] SC rec id=1 i=4 kind=LINE spd=80",
    "[v2] SC rec id=1 i=5 kind=LINE spd=80",
    "[v2] SC rec id=1 i=6 kind=LINE spd=80",
    "[v2] SC act id=1 i=6 act=DO_OFF val=1",
    "[v2] SC rec id=1 i=7 kind=LINE spd=80",
    "[v2] SC act id=1 i=7 act=DELAY_MS val=400",
]
HOME_RAW = (3000, -2100, -400, -1000)  # HOME (300, -210, -40, -100) на проводе, x10
_WIRE_PREFIXES = ("[v2] SC rec", "[v2] SC act")


# --- хелперы ядра без TCP ----------------------------------------------------------------------


def _send(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> None:
    """Команда в mailbox и ровно один тик (разбор mailbox — на тике)."""
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick(0.01)


def _run_slot(core: RobotSimCoreV2) -> None:
    """SERVO 1, 7 записей ``return_slot`` в ``SC_BUF`` с offset 0, ``SC_RUN``, тики до ``TLM_ACTIVITY == 0``."""
    gp = return_slot(SLOT)
    scenario = compile_program(gp.program, gp.points, {}, WS_PARAMS)
    words = wire_v2.encode_scenario(scenario, params=WS_PARAMS, round_step=0.1)
    assert len(words) == 7
    _send(core, 1, OP["SERVO"], 1)
    for _ in range(50):
        if core.read(REG["TLM_SERVO"], 1)[0] == 1:
            break
        core.tick(0.01)
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1
    for index, record in enumerate(words):
        core.write(REG["SC_BUF"] + index * CONSTANTS["SC_STRIDE"], list(record))
    _send(core, 2, OP["SC_RUN"], 7, 1, 0)  # count, sc_id, offset
    for _ in range(2000):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return
        core.tick(0.01)
    pytest.fail("сценарий не завершился за 2000 тиков")


def _sc_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith(_WIRE_PREFIXES)]


def _boom_belt(armed: threading.Event | None = None) -> BeltDrive:
    """Лента, чей ``advance`` бросает ``RuntimeError`` (сразу или после взвода ``armed``)."""
    belt = BeltDrive.from_enc_rate(7, 0.01)
    original = belt.advance

    def advance(dt_s: float) -> int:
        if armed is None or armed.is_set():
            raise RuntimeError("belt boom")
        return original(dt_s)

    belt.advance = advance
    return belt


# --- хук trace_sc -------------------------------------------------------------------------------


def test_trace_sc_lines_literal() -> None:
    lines: list[str] = []
    _run_slot(RobotSimCoreV2(trace_sc=True, on_event=lines.append))
    assert _sc_lines(lines) == SC_LITERAL


def test_trace_sc_off_keeps_output() -> None:
    on: list[str] = []
    off: list[str] = []
    _run_slot(RobotSimCoreV2(trace_sc=True, on_event=on.append))
    _run_slot(RobotSimCoreV2(on_event=off.append))
    assert _sc_lines(off) == []
    assert [line for line in on if not line.startswith(_WIRE_PREFIXES)] == off
    assert any(line.startswith("[v2] SC end id=1 done_n=7") for line in off)  # вывод не пуст: сравнивали не пустоту


# --- обвязка без TCP ----------------------------------------------------------------------------


class _FakeSocket:
    """Подменный ``socket.socket``: порты отдаются по очереди."""

    ports: list[int] = []

    def __init__(self, *_args: object) -> None:
        self._port = 0

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def bind(self, _address: tuple[str, int]) -> None:
        self._port = self.ports.pop(0) if len(self.ports) > 1 else self.ports[0]

    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", self._port)

    def close(self) -> None:
        return None


def _patch_socket(monkeypatch: pytest.MonkeyPatch, ports: list[int]) -> None:
    _FakeSocket.ports = list(ports)
    fake = SimpleNamespace(socket=_FakeSocket, AF_INET=socket.AF_INET, SOCK_STREAM=socket.SOCK_STREAM)
    monkeypatch.setattr(e2e_rig_v2, "socket", fake)


def test_free_port_skips_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    assert 5021 in FORBIDDEN_PORTS and 8870 in FORBIDDEN_PORTS and 40000 not in FORBIDDEN_PORTS
    _patch_socket(monkeypatch, [5021, 8870, 40000])
    assert free_port() == 40000
    _patch_socket(monkeypatch, [5021])  # последний порт повторяется
    with pytest.raises(RuntimeError):
        free_port()


def test_bounded_deadline_and_passthrough() -> None:
    gate = threading.Event()
    start = time.monotonic()
    with pytest.raises(TimeoutError) as info:
        bounded(lambda: gate.wait(5.0), 0.2)
    assert time.monotonic() - start < 1.0
    assert str(info.value) == "bounded: вызов не уложился в дедлайн"
    assert "deadline_s=0.2" in info.value.__notes__[0]
    gate.set()  # отпустить зависший daemon-поток

    def raiser() -> None:
        raise KeyError("k")

    with pytest.raises(KeyError):
        bounded(raiser)
    assert bounded(lambda: 42) == 42


def test_pulse_counts_stops_and_keeps_errors() -> None:
    calls: list[int] = []
    with pulse(lambda: calls.append(1), 0.02) as p:
        time.sleep(0.2)
    assert 5 <= p.count <= 12
    after = p.count
    time.sleep(0.1)
    assert p.count == after
    assert p.errors == []

    state = {"n": 0}

    def flaky() -> None:
        state["n"] += 1
        if state["n"] % 2 == 1:
            raise ValueError("odd")

    with pulse(flaky, 0.02) as q:
        time.sleep(0.2)
    assert q.errors != [] and all(isinstance(e, ValueError) for e in q.errors)
    assert q.count > len(q.errors)  # чётные вызовы прошли: поток продолжал после исключений


def test_recording_core_stamps_events_with_tick_time() -> None:
    rec = RecordingCore()
    _send(rec, 1, OP["SERVO"], 1)
    seq = 77
    done_index: int | None = None
    _send(rec, seq, OP["PTP_MOVE"], *HOME_RAW, 2, 100)  # JOINT нулевой длины в текущую позу
    for _ in range(5):
        if done_index is None and rec.read(REG["TLM_DONE_SEQ"], 1)[0] == seq:
            done_index = len(rec.ticks()) - 1  # первый тик, после которого регистр стал seq
        rec.tick(0.01)
    assert done_index is not None, "ход нулевой длины не завершился"
    ticks = rec.ticks()
    assert [round(t.t, 9) for t in ticks] == [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07]
    stamps = [stamp for stamp, text in rec.events() if text == f"[v2] DONE seq={seq} op=PTP_MOVE"]
    assert len(stamps) == 1
    assert stamps[0] == pytest.approx(ticks[done_index].t, abs=1e-9)


def test_recording_core_keeps_tick_exception() -> None:
    rec = RecordingCore(belt=_boom_belt())
    with pytest.raises(RuntimeError, match="belt boom") as info:
        rec.tick(0.01)
    assert rec.tick_errors() == [info.value]
    assert rec.ticks() == []  # тик не завершился — снимка нет


# --- живой стенд --------------------------------------------------------------------------------


def test_rig_live_ping_and_restart_same_port() -> None:
    with E2eRig() as rig:
        assert rig.port not in FORBIDDEN_PORTS
        bounded(rig.client.ping)
        bounded(lambda: rig.client.param_set("P_SPD_DEFAULT", 55))
        port = rig.port
        old_core = rig.core
        rig.restart()
        assert rig.port == port
        assert rig.core is not old_core
        bounded(rig.client.ping)
        assert bounded(lambda: rig.client.param_get("P_SPD_DEFAULT")) == 55
        rig.restart(keep_regs=False)
        bounded(rig.client.ping)
        assert bounded(lambda: rig.client.param_get("P_SPD_DEFAULT")) == 80


def test_rig_restart_retries_until_port_free() -> None:
    """Порт занят чужим сокетом 0.6 с после остановки сервера: ``restart`` повторяет подъём, а не падает."""
    with E2eRig() as rig:
        bounded(rig.server.stop, 5.0)
        squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        deadline = time.monotonic() + 3.0
        while True:
            try:
                squatter.bind(("127.0.0.1", rig.port))
                squatter.listen()
                break
            except OSError:
                assert time.monotonic() < deadline, "не удалось занять порт для проверки"
                time.sleep(0.05)
        release = threading.Timer(0.6, squatter.close)
        release.start()
        try:
            rig.restart()
        finally:
            release.cancel()
            squatter.close()
        bounded(rig.client.ping)


# Тикер умирает от belt — это предмет теста, предупреждение pytest о потоке не нужно.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_rig_exit_reports_tick_errors() -> None:
    armed = threading.Event()
    core_with_belt = RecordingCore(belt=_boom_belt(armed))
    with pytest.raises(AssertionError, match="RuntimeError"):  # noqa: PT012 — проверяется выход из with
        with E2eRig(core=core_with_belt) as rig:
            armed.set()
            deadline = time.monotonic() + 2.0
            while not rig.core.tick_errors():
                assert time.monotonic() < deadline, "тик не упал за 2 с"
                time.sleep(0.01)


# Тикер умирает от belt — это предмет теста, предупреждение pytest о потоке не нужно.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_rig_enter_failure_cleans_up() -> None:
    rig = E2eRig(core=RecordingCore(belt=_boom_belt()))
    entered = False
    with pytest.raises(AssertionError, match="RuntimeError") as info:
        with rig:
            entered = True
    assert entered is False
    assert info.value.__cause__ is not None
    deadline = time.monotonic() + 2.0
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", rig.port))
            probe.listen()
            break
        except OSError:
            assert time.monotonic() < deadline, "порт не освободился: сервер не остановлен"
            time.sleep(0.05)
        finally:
            probe.close()
