"""Тесты автора ``RobotClientV2``: гонки, порядок записей, seq, О3, О5, probe-до-записи (T3.1).

Стенд — ``FakeRobotTransport`` поверх настоящего ``RobotSimCoreV2`` (``ticks_per_read=0``): время робота
идёт только из ``sleep`` клиента (он делает ``core.tick()``), часы клиента — ручные. Барьеры стоят на самой
записи (хук ``after_tx`` / ``before_tx`` на ``transaction``), а не на входе в метод. Один тест
(``test_real_stack_*``) собран из настоящих ``SimRobotServer`` + ``ModbusDevice``.
Адреса и коды — литералами из protocol-spec; приёмку против sim v2 пишет tester (``test_client_v2_acceptance``).
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk.errors import ModbusIOError
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2, StopResult
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.errors import (
    RobotAborted,
    RobotCommandError,
    RobotNak,
    RobotNotConnectedError,
    RobotSyncError,
    RobotTimeout,
    WrongFirmware,
)
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.server.sim_robot import SimRobotServer
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

# --- литералы протокола -------------------------------------------------------------------
CMD_FLAG, CMD_SEQ = 0x1000, 0x1001
RES_SEQ, HB_PC, STOP_REQ, JOG_LEASE = 0x1010, 0x1020, 0x1021, 0x1022
TLM_ACTIVITY, TLM_SERVO = 0x1043, 0x1049
TLM_DONE_SEQ, TLM_ERR_SEQ, TLM_ERRNO_LAST, TLM_ERR_EVT = 0x1051, 0x1052, 0x1053, 0x1054
TLM_STOP_ACK, TLM_CFG_EPOCH = 0x105C, 0x105D
PMIR_BASE, PMIR_DICT = 0x3000, 0x3082
OP_PING, OP_PTP_MOVE, OP_SERVO, OP_PARAM_SET, OP_PARAM_APPLY = 0x01, 0x10, 0x41, 0x50, 0x52
E_RANGE, E_ABORTED, E_MOTION_FAULT = 3, 13, 11
P_WDG_ID, P_JOG_ID, P_EPOCH_ID = 96, 11, 98

MOVE_LONG = [3000, -1500, -400, -1000, 0, 1]  # из дома 60 мм на 1 % — сотни тиков
MOVE_SHORT = [3000, -2090, -400, -1000, 0, 100]

_FORBIDDEN_PORTS = frozenset({5021, 8765, 8766, 8091, 8092})
_DEADLINE_S = 10.0


class FixedRng:
    """Подставной ``random.Random``: ``randint`` всегда отдаёт заданное значение."""

    def __init__(self, value: int) -> None:
        self.value = value

    def randint(self, a: int, b: int) -> int:  # noqa: ARG002 — сигнатура random.Random
        return self.value


class HookTransport(FakeRobotTransport):
    """Fake с журналом чтений/записей и хуками на запись (барьер на самой записи)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log: list[tuple] = []  # ("r", addr, count) | ("tx", ops)
        self.before_tx = None
        self.after_tx = None
        self.read_filter = None

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        self.log.append(("r", address, count))
        out = super().read_registers(address, count)
        return self.read_filter(address, count, out) if self.read_filter else out

    def transaction(self, ops: list[tuple]) -> bool:
        self.log.append(("tx", list(ops)))
        if self.before_tx:
            self.before_tx(ops)
        ok = super().transaction(ops)
        if self.after_tx:
            self.after_tx(ops)
        return ok


def is_cmd_tx(ops: list[tuple]) -> bool:
    return len(ops) == 2 and ops[0][0] == "wm" and ops[0][1] == CMD_SEQ and ops[1] == ("w", CMD_FLAG, 1)


class Rig:
    def __init__(
        self, *, ticking: bool = True, rng: int = 100, config: dict | None = None, connect: bool = True, core=None
    ) -> None:
        self.core = core if core is not None else RobotSimCoreV2()
        self.transport = HookTransport(core=self.core, ticks_per_read=0)
        if connect:
            self.transport.connect()
        self.now = 0.0
        self.ticking = ticking
        self._tick_lock = threading.Lock()
        cfg = ClientV2Config.from_dict(config or {})
        self.client = RobotClientV2(self.transport, cfg, rng=FixedRng(rng), clock=lambda: self.now, sleep=self.sleep)

    def sleep(self, dt: float) -> None:
        with self._tick_lock:  # два потока клиента не тикают ядро одновременно
            self.now += dt
            if self.ticking:
                self.core.tick()

    def cmds(self) -> list[tuple[int, int, list[int]]]:
        """Команды mailbox из журнала записей: (seq, opcode, args)."""
        out = []
        for ops in self.transport.transactions:
            if is_cmd_tx(ops):
                seq, opcode, argc, *args = ops[0][2]
                assert argc == len(args)
                out.append((seq, opcode, args))
        return out

    def stop_writes(self) -> list[int]:
        return [op[2] for ops in self.transport.transactions for op in ops if op[1] == STOP_REQ]


def in_thread(fn, name: str = "t"):
    box: dict = {}
    done = threading.Event()

    def body() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 — исключение уходит в тест
            box["exc"] = exc
        finally:
            done.set()

    threading.Thread(target=body, name=name, daemon=True).start()
    return box, done


def join(done: threading.Event, what: str, deadline: float = _DEADLINE_S) -> None:
    if not done.wait(deadline):
        pytest.fail(f"зависание: {what}")


def all_values() -> dict[str, int]:
    return {name: int(PARAMS[pid]["default"]) for name, pid in PARAM_ID.items() if name != "P_CONFIG_EPOCH"}


# ============================================================================================
# Конфиг
# ============================================================================================


def test_config_defaults_are_literals() -> None:
    cfg = ClientV2Config.from_dict({})
    assert (cfg.poll_interval_s, cfg.longest_gap_s, cfg.res_timeout_s) == (0.02, 1.5, 2.0)
    assert (cfg.done_timeout_s, cfg.stop_echo_timeout_s, cfg.soft_echo_timeout_s) == (30.0, 1.0, 2.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"res_timeout_s": 1.0},  # < longest_gap 1.5
        {"soft_echo_timeout_s": 1.0},
        {"poll_interval_s": 0},
        {"unknown_field": 1},
    ],
)
def test_config_rejects_bad_fields_without_echoing_values(bad: dict) -> None:
    with pytest.raises(ValueError) as exc:
        ClientV2Config.from_dict(bad)
    for value in bad.values():
        assert f"={value!r}" not in str(exc.value)


# ============================================================================================
# probe и «запись только после чтения версии»
# ============================================================================================


def test_unprobed_cmd_on_wrong_firmware_raises_with_zero_writes() -> None:
    from Services.robot_comm.server.sim_core import RobotSimCore

    rig = Rig(core=RobotSimCore())
    with pytest.raises(WrongFirmware) as exc:
        rig.client.cmd("PING", [])
    assert exc.value.proto_ver == 0
    assert rig.transport.transactions == []
    assert [e for e in rig.transport.log if e[0] == "tx"] == []


def test_unprobed_first_cmd_writes_only_after_version_read() -> None:
    rig = Rig()
    rig.client.cmd("PING", [])
    assert rig.transport.log[0] == ("r", RES_SEQ, 80)  # версия читается до первой записи
    first_tx = next(i for i, e in enumerate(rig.transport.log) if e[0] == "tx")
    assert first_tx >= 3  # блок 0x1010..0x105F + два слота PMIR (watchdog, поводок) прочитаны раньше
    assert rig.transport.log[1] == ("r", PMIR_BASE + P_WDG_ID, 1)
    assert rig.transport.log[2] == ("r", PMIR_BASE + P_JOG_ID, 1)


@pytest.mark.parametrize("proto_ver", [0x0100, 0x0300, 0x0000])
def test_probe_wrong_major_reads_nothing_more(proto_ver: int) -> None:
    rig = Rig()
    rig.core.regs[0x1040] = proto_ver
    with pytest.raises(WrongFirmware) as exc:
        rig.client.probe()
    assert exc.value.proto_ver == proto_ver
    assert rig.transport.log == [("r", RES_SEQ, 80)]  # слоты PMIR не читались
    assert rig.transport.transactions == []


def test_probe_accepts_minor_version_bump() -> None:
    rig = Rig()
    rig.core.regs[0x1040] = 0x0207
    rig.client.probe()


def test_unconnected_transport_raises_not_connected_without_write() -> None:
    rig = Rig(connect=False)
    for call in (
        lambda: rig.client.cmd("PING", []),
        lambda: rig.client.stop(2),
        rig.client.kick_heartbeat,
        rig.client.jog_lease,
        lambda: rig.client.sync_params(all_values(), 1),
    ):
        with pytest.raises(RobotNotConnectedError):
            call()
    assert rig.transport.log == [] and rig.transport.transactions == []


def test_periods_come_from_probe_mirror_and_none_when_watchdog_off() -> None:
    rig = Rig()
    assert rig.client.heartbeat_period_s is None and rig.client.jog_lease_period_s is None
    rig.client.probe()
    assert rig.client.heartbeat_period_s == 0.75  # P_WDG_TIMEOUT_MS 3000 / 4000
    assert rig.client.jog_lease_period_s == pytest.approx(0.1)  # P_JOG_LEASE_MS 300 / 3000
    off = Rig()
    off.core.regs[PMIR_BASE + P_WDG_ID] = 0
    off.client.probe()
    assert off.client.heartbeat_period_s is None


# ============================================================================================
# Пульс и поводок
# ============================================================================================


def test_heartbeat_first_write_changes_register_and_wraps_16_bit() -> None:
    rig = Rig()
    rig.core.regs[HB_PC] = 0xFFFF
    rig.client.probe()
    rig.client.kick_heartbeat()
    rig.client.kick_heartbeat()
    assert rig.transport.transactions == [[("w", HB_PC, 0)], [("w", HB_PC, 1)]]


def test_jog_lease_increments_from_probe_base_in_its_own_register() -> None:
    rig = Rig()
    rig.core.regs[JOG_LEASE] = 7
    rig.client.probe()
    rig.client.jog_lease()
    assert rig.transport.transactions == [[("w", JOG_LEASE, 8)]]


# ============================================================================================
# cmd: порядок записей, аргументы, seq
# ============================================================================================


def test_cmd_transaction_is_data_block_then_flag_in_one_call() -> None:
    rig = Rig(rng=100)
    rig.client.cmd("PTP_MOVE", [3000, -2090, -400, -1000, 0, 100])
    assert rig.transport.transactions == [
        [("wm", CMD_SEQ, [100, OP_PTP_MOVE, 6, 3000, 0xF7D6, 0xFE70, 0xFC18, 0, 100]), ("w", CMD_FLAG, 1)]
    ]


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("PING", [1]),
        ("PTP_MOVE", [1, 2]),
        ("NO_SUCH_OP", []),
        ("SERVO", [-32768]),
        ("SERVO", [65536]),
        ("SERVO", [1.5]),
    ],
)
def test_cmd_bad_arguments_raise_value_error_without_write(op: str, args: list) -> None:
    rig = Rig()
    with pytest.raises(ValueError) as exc:
        rig.client.cmd(op, args)
    assert "65536" not in str(exc.value) and "32768" not in str(exc.value)
    assert rig.transport.transactions == []


def test_seq_starts_at_rng_value_then_plus_one() -> None:
    rig = Rig(rng=100)
    first = rig.client.cmd("PING", [])
    second = rig.client.cmd("PING", [])
    assert (first.seq, second.seq) == (100, 101)


def test_seq_skips_current_res_done_and_err_seq() -> None:
    rig = Rig(rng=100)
    rig.core.regs[RES_SEQ], rig.core.regs[TLM_DONE_SEQ], rig.core.regs[TLM_ERR_SEQ] = 100, 101, 102
    assert rig.client.cmd("PING", []).seq == 103


def test_seq_zero_is_never_issued_and_65535_wraps_to_1() -> None:
    zero = Rig(rng=0)
    assert zero.client.cmd("PING", []).seq == 1
    wrap = Rig(rng=65535)
    assert [wrap.client.cmd("PING", []).seq for _ in range(2)] == [65535, 1]


# ============================================================================================
# cmd: разбор NAK
# ============================================================================================


def test_nak_e_range_with_reason_carries_reason_text_and_rvals() -> None:
    rig = Rig()
    with pytest.raises(RobotNak) as exc:
        rig.client.cmd("PTP_MOVE", [3000, -2100, -400, -1000, 5, 50])  # kind = 5 -> R_KIND
    nak = exc.value
    assert (nak.errno, nak.reason, nak.index, nak.rvals) == (E_RANGE, 1, None, (1,))
    assert nak.text.endswith(": KIND")


def test_nak_e_range_without_rvalc_ignores_stale_rval_from_previous_reply() -> None:
    rig = Rig()
    with pytest.raises(RobotNak):  # оставляет RVAL0 = 1 с RVALC = 1
        rig.client.cmd("PTP_MOVE", [3000, -2100, -400, -1000, 5, 50])
    with pytest.raises(RobotNak) as exc:  # теперь RVALC = 0, RVAL0 в регистре остался прежним
        rig.client.cmd("PTP_MOVE", [3000, -2100, -400, -1000, 0, 101])
    assert exc.value.reason is None and exc.value.rvals == ()
    assert exc.value.text == "Значение или цель вне допустимого диапазона (rval0 — причина)"


def test_nak_e_sc_record_gets_index_and_reason() -> None:
    # E_SC_RECORD (8): rval0 = индекс записи, rval1 = причина; блок RES = [seq, NAK=2, errno, rvalc, rvals...]
    with pytest.raises(RobotNak) as exc:
        RobotClientV2._parse_res([9, 2, 8, 2, 4, 6, 0, 0, 0, 0, 0, 0])
    nak = exc.value
    assert (nak.errno, nak.index, nak.reason, nak.rvals) == (8, 4, 6, (4, 6))
    assert nak.text.endswith(": последняя точка LINE_PASS")


def test_nak_unknown_errno_gets_fallback_text() -> None:
    with pytest.raises(RobotNak) as exc:
        RobotClientV2._parse_res([9, 2, 99, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert exc.value.text == "неизвестная ошибка"


# ============================================================================================
# cmd: ответ не пришёл — метка «в полёте»
# ============================================================================================


def test_response_timeout_then_next_cmd_settles_inflight_without_new_write() -> None:
    rig = Rig(ticking=False)
    with pytest.raises(RobotTimeout) as first:
        rig.client.cmd("PING", [])
    assert (first.value.stage, first.value.seq) == ("response", 100)
    assert len(rig.cmds()) == 1
    with pytest.raises(RobotTimeout) as second:  # робот всё ещё молчит: досмотр прежнего seq, записи нет
        rig.client.cmd("PING", [])
    assert (second.value.stage, second.value.seq) == ("response", 100)
    assert len(rig.cmds()) == 1
    rig.ticking = True
    assert rig.client.cmd("PING", []).seq == 101  # метка снята: пишет сразу
    assert [c[0] for c in rig.cmds()] == [100, 101]


def test_late_response_to_inflight_seq_lets_next_cmd_proceed() -> None:
    rig = Rig(ticking=False)
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PING", [])
    rig.core.tick()  # робот наконец ответил на seq 100
    rig.ticking = True
    assert rig.client.cmd("PING", []).seq == 101


# ============================================================================================
# wait_done
# ============================================================================================


def test_wait_done_rejects_foreign_seq_and_instant_ops() -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.client.wait_done(5)  # команд ещё не было
    ping = rig.client.cmd("PING", [])
    with pytest.raises(ValueError):
        rig.client.wait_done(ping.seq)  # PING — не done_seq
    move = rig.client.cmd("PTP_MOVE", MOVE_SHORT)
    rig.client.cmd("PING", [])  # мгновенная команда не сбивает базу ожидания
    with pytest.raises(ValueError):
        rig.client.wait_done(move.seq + 50)
    rig.client.wait_done(move.seq)
    assert rig.core.regs[TLM_DONE_SEQ] == move.seq


def test_wait_done_times_out_when_robot_never_finishes() -> None:
    rig = Rig(config={"done_timeout_s": 3.0})
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.ticking = False
    with pytest.raises(RobotTimeout) as exc:
        rig.client.wait_done(move.seq)
    assert (exc.value.stage, exc.value.seq) == ("done", move.seq)
    assert 3.0 <= rig.now - 0 and rig.now < 30.0


def test_wait_done_motion_fault_is_command_error_not_aborted() -> None:
    rig = Rig()
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.core.inject_motion_fault()
    with pytest.raises(RobotCommandError) as exc:
        rig.client.wait_done(move.seq)
    assert type(exc.value) is RobotCommandError
    assert (exc.value.errno, exc.value.seq) == (E_MOTION_FAULT, move.seq)


def test_wait_done_sees_fault_that_happened_between_cmd_write_and_cmd_return() -> None:
    """База ``ERR_EVT`` снята ДО записи CMD: авария сразу после приёма команды не теряется."""
    rig = Rig()

    def fault_right_after_accept(ops: list[tuple]) -> None:
        if is_cmd_tx(ops):
            rig.core.tick()  # робот принял команду и начал ход
            rig.core.inject_motion_fault()

    rig.transport.after_tx = fault_right_after_accept
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.transport.after_tx = None
    with pytest.raises(RobotCommandError) as exc:
        rig.client.wait_done(move.seq)
    assert (exc.value.errno, exc.value.seq) == (E_MOTION_FAULT, move.seq)


def test_wait_done_foreign_event_while_running_does_not_fail_the_wait() -> None:
    """Чужое событие ERR_EVT между базой и записью CMD: команда идёт (ACTIVITY ≠ 0, 5) — ждём дальше."""
    rig = Rig()

    def foreign_event(ops: list[tuple]) -> None:
        if is_cmd_tx(ops):
            rig.core.regs[TLM_ERR_SEQ] = 4242
            rig.core.regs[TLM_ERRNO_LAST] = 12
            rig.core.regs[TLM_ERR_EVT] = (rig.core.regs[TLM_ERR_EVT] + 1) & 0xFFFF

    rig.transport.before_tx = foreign_event
    move = rig.client.cmd("PTP_MOVE", MOVE_SHORT)
    rig.client.wait_done(move.seq)  # без исключения


def test_wait_done_masked_abort_event_is_reported_when_robot_is_idle() -> None:
    """ERR_EVT изменился, ERR_SEQ не наш, DONE_SEQ не наш, ACTIVITY = 0 -> «событие обрыва перекрыто»."""
    rig = Rig()
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.core._active = None  # команда исчезла без DONE (перекрыта): ACTIVITY -> 0
    rig.core.regs[TLM_ACTIVITY] = 0
    rig.core.regs[TLM_ERR_SEQ] = move.seq + 1000
    rig.core.regs[TLM_ERR_EVT] = (rig.core.regs[TLM_ERR_EVT] + 1) & 0xFFFF
    with pytest.raises(RobotCommandError) as exc:
        rig.client.wait_done(move.seq)
    assert exc.value.errno is None and exc.value.text == "событие обрыва перекрыто"


def test_wait_done_ack_seq_change_alone_is_not_an_abort() -> None:
    """Ловушка р.1: TLM_ACK_SEQ от чужого PARAM_GET не считается обрывом."""
    rig = Rig()
    move = rig.client.cmd("PTP_MOVE", MOVE_SHORT)
    rig.client.cmd("PARAM_GET", [0])  # мгновенный чужой ACK поверх
    rig.client.wait_done(move.seq)


# ============================================================================================
# poll_errors
# ============================================================================================


def test_poll_errors_reports_abort_once_with_text_and_cursor_from_probe() -> None:
    rig = Rig()
    rig.core.regs[TLM_ERR_EVT] = 5
    rig.client.probe()
    assert rig.client.poll_errors() == []
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.client.stop(2)
    [event] = rig.client.poll_errors()
    assert (event.evt, event.seq, event.errno, event.missed) == (6, move.seq, E_ABORTED, 0)
    assert event.text == "Движение прервано стопом"
    assert rig.client.poll_errors() == []


def test_poll_errors_counts_missed_events_and_wraps_16_bit() -> None:
    rig = Rig()
    rig.core.regs[TLM_ERR_EVT] = 0xFFFF
    rig.client.probe()
    rig.core.regs[TLM_ERR_EVT] = 2  # 0xFFFF -> 2 = 3 события, два из них потеряны
    [event] = rig.client.poll_errors()
    assert (event.evt, event.missed) == (2, 2)


# ============================================================================================
# stop
# ============================================================================================


@pytest.mark.parametrize("level", [0, 4, -1, True, 2.0, None])
def test_stop_bad_level_raises_without_write(level) -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.client.stop(level)
    assert rig.transport.transactions == []


def test_stop_value_is_next_seq_after_ack_times_four_plus_level() -> None:
    rig = Rig()
    rig.core.regs[TLM_STOP_ACK] = 10 * 4 + 2
    assert rig.client.stop(3) is StopResult.ACKED
    assert rig.client.stop(1) is StopResult.ACKED
    assert rig.stop_writes() == [11 * 4 + 3, 12 * 4 + 1]


def test_stop_seq_wraps_16383_to_1() -> None:
    rig = Rig()
    rig.core.regs[TLM_STOP_ACK] = 16383 * 4 + 2
    rig.client.stop(2)
    assert rig.stop_writes() == [1 * 4 + 2]


def test_stop_superseded_when_echo_is_already_newer() -> None:
    rig = Rig(ticking=False)

    def newer_stop_wins(ops: list[tuple]) -> None:
        if ops == [("w", STOP_REQ, 1 * 4 + 2)]:
            rig.core.regs[TLM_STOP_ACK] = 2 * 4 + 3  # чужой стоп с seq 2 уже отвечен

    rig.transport.after_tx = newer_stop_wins
    assert rig.client.stop(2) is StopResult.SUPERSEDED


def test_stop_echo_older_than_ours_is_not_superseded() -> None:
    rig = Rig(ticking=False, config={"stop_echo_timeout_s": 1.0, "poll_interval_s": 0.1})
    rig.core.regs[TLM_STOP_ACK] = 5 * 4 + 2
    with pytest.raises(RobotTimeout) as exc:
        rig.client.stop(2)
    assert exc.value.stage == "stop_echo"


@pytest.mark.parametrize(("level", "timeout"), [(2, 1.0), (3, 1.0), (1, 3.0)])
def test_stop_echo_timeout_depends_on_level(level: int, timeout: float) -> None:
    rig = Rig(
        ticking=False,
        config={
            "stop_echo_timeout_s": 1.0,
            "soft_echo_timeout_s": 3.0,
            "longest_gap_s": 0.5,
            "poll_interval_s": 0.1,
            "res_timeout_s": 0.5,
        },
    )
    rig.client.probe()
    start = rig.now
    with pytest.raises(RobotTimeout) as exc:
        rig.client.stop(level)
    assert exc.value.stage == "stop_echo"
    assert timeout <= rig.now - start < timeout + 0.25


def test_stop_write_is_single_fc6_in_one_transaction() -> None:
    rig = Rig()
    rig.client.stop(2)
    assert rig.transport.transactions == [[("w", STOP_REQ, 1 * 4 + 2)]]


# ============================================================================================
# О5: команда done_seq, обогнанная стопом
# ============================================================================================


def _stop_inside_cmd_window(rig: Rig, level: int, *, before_write: bool = False) -> None:
    """Барьер на самой записи CMD: стоп ``level`` вклинивается ДО неё (после чтения базы) или сразу ПОСЛЕ
    (до ACK). После HALT серво выключено, и робот отказал бы любой ход — тест включает его обратно."""
    fired = []

    def hook(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and not fired:
            fired.append(1)
            rig.client.stop(level)
            rig.core.regs[TLM_SERVO] = 1

    if before_write:
        rig.transport.before_tx = hook
    else:
        rig.transport.after_tx = hook


@pytest.mark.parametrize(
    ("window_level", "reissued", "before_write"),
    [(1, 2, False), (2, 2, False), (1, 2, True), (2, 2, True), (3, 3, True)],
    ids=["soft-after", "hard-after", "soft-before", "hard-before", "halt-before"],
)
def test_done_seq_command_overtaken_by_stop_reissues_halt_if_halt_else_hard(
    window_level: int, reissued: int, before_write: bool
) -> None:
    rig = Rig()
    rig.client.probe()
    _stop_inside_cmd_window(rig, window_level, before_write=before_write)
    with pytest.raises(RobotAborted) as exc:
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    assert exc.value.errno == E_ABORTED
    assert rig.stop_writes() == [1 * 4 + window_level, 2 * 4 + reissued]
    rig.core.tick()  # робот видит повторный стоп и обрывает принятый после стопа ход
    assert rig.core.regs[TLM_ACTIVITY] == 0
    assert rig.core.regs[TLM_ERRNO_LAST] == E_ABORTED
    assert rig.core.regs[TLM_SERVO] == (0 if reissued == 3 else 1)


def test_instant_command_overtaken_by_stop_still_returns_its_result() -> None:
    rig = Rig()
    rig.client.probe()
    _stop_inside_cmd_window(rig, 2)
    result = rig.client.cmd("SERVO", [1])
    assert result.rvals == ()
    assert rig.stop_writes() == [1 * 4 + 2]  # повторного стопа нет


def test_stop_completed_before_cmd_does_not_abort_it() -> None:
    rig = Rig()
    rig.client.stop(2)
    result = rig.client.cmd("PTP_MOVE", MOVE_SHORT)
    rig.client.wait_done(result.seq)
    assert rig.stop_writes() == [1 * 4 + 2]


def test_failed_stop_write_still_counts_as_generation() -> None:
    """Запись могла дойти, хотя транспорт вернул ошибку: поколение растёт в finally."""
    rig = Rig()
    rig.client.probe()
    fired = []

    def hook(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and not fired:
            fired.append(1)
            rig.transport.fail_next_op = True
            with pytest.raises(ModbusIOError):
                rig.client.stop(2)

    rig.transport.after_tx = hook
    with pytest.raises(RobotAborted):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    assert rig.core.regs[STOP_REQ] == 2 * 4 + 2  # первый стоп (seq 1) не дошёл; повтор получил seq 2


# ============================================================================================
# Гонки: стоп и остальные методы не ждут mailbox
# ============================================================================================


def test_stop_and_side_channels_do_not_wait_for_a_blocked_cmd_but_second_cmd_does() -> None:
    rig = Rig()
    rig.client.probe()
    in_wait = threading.Event()
    release = threading.Event()
    base_sleep = rig.sleep

    def sleep(dt: float) -> None:
        if threading.current_thread().name == "cmd-thread":
            in_wait.set()
            assert release.wait(_DEADLINE_S), "тест не отпустил поток cmd"
            return
        base_sleep(dt)

    rig.client._sleep = sleep
    rig.ticking = False  # робот ходит только по sleep других потоков
    first, first_done = in_thread(lambda: rig.client.cmd("PING", []), "cmd-thread")
    assert in_wait.wait(_DEADLINE_S), "cmd не дошёл до ожидания ответа"

    rig.ticking = True
    side = {
        "stop": lambda: rig.client.stop(2),
        "heartbeat": rig.client.kick_heartbeat,
        "jog": rig.client.jog_lease,
        "errors": rig.client.poll_errors,
    }
    for name, fn in side.items():
        box, done = in_thread(fn, f"side-{name}")
        join(done, f"{name} ждёт замок mailbox")
        assert "exc" not in box, box.get("exc")
    assert not first_done.is_set(), "первый cmd вернулся до отпускания — стенд не держал замок"

    second, second_done = in_thread(lambda: rig.client.cmd("PING", []), "cmd2-thread")
    assert not second_done.wait(0.3), "второй cmd не должен идти, пока первый держит mailbox"
    release.set()
    join(first_done, "первый cmd")
    join(second_done, "второй cmd")
    assert "exc" not in first and "exc" not in second, (first.get("exc"), second.get("exc"))
    assert first["value"].seq != second["value"].seq


# ============================================================================================
# sync_params
# ============================================================================================


def _param_cmds(rig: Rig) -> list[tuple[int, int, list[int]]]:
    return rig.cmds()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.pop("P_SPD_JOG"),
        lambda v: v.__setitem__("P_NO_SUCH", 1),
        lambda v: v.__setitem__("P_CONFIG_EPOCH", 3),
        lambda v: v.__setitem__("P_SPD_JOG", 70000),
    ],
    ids=["missing", "unknown", "epoch-key", "word-out-of-range"],
)
def test_sync_params_bad_values_raise_before_any_write(mutate) -> None:
    rig = Rig()
    values = all_values()
    mutate(values)
    with pytest.raises(ValueError):
        rig.client.sync_params(values, 1)
    assert rig.transport.transactions == []
    assert rig.transport.log == []  # ни записей, ни даже чтений


@pytest.mark.parametrize("epoch", [0, 65536, -1, True, 1.0])
def test_sync_params_bad_epoch_raises_before_any_write(epoch) -> None:
    rig = Rig()
    with pytest.raises(ValueError):
        rig.client.sync_params(all_values(), epoch)
    assert rig.transport.transactions == []


def test_sync_params_order_apply_before_epoch_and_epoch_once_last() -> None:
    rig = Rig()
    report = rig.client.sync_params(all_values(), 7)
    ops = [(c[1], c[2]) for c in rig.cmds()]
    expected_sets = len(PARAM_ID) - 1  # все, кроме метки
    assert [o for o, _ in ops].count(OP_PARAM_SET) == expected_sets + 1
    assert ops[-1] == (OP_PARAM_SET, [P_EPOCH_ID, 7])
    assert [a for o, a in ops if o == OP_PARAM_SET and a[0] == P_EPOCH_ID] == [[P_EPOCH_ID, 7]]
    # В словаре есть параметры apply=reinit (12 шт.) -> после их записи TLM_CFG_PENDING = 1 -> один PARAM_APPLY
    assert [o for o, _ in ops].count(OP_PARAM_APPLY) == 1
    assert ops[-2][0] == OP_PARAM_APPLY
    assert (report.sent, report.applied, report.epoch) == (expected_sets, True, 7)
    assert rig.core.regs[TLM_CFG_EPOCH] == 7


def test_sync_params_mirror_mismatch_raises_and_does_not_write_epoch() -> None:
    rig = Rig()

    def corrupt(address: int, count: int, out: list[int]) -> list[int]:
        if address == PMIR_BASE and count > 50:  # сверка PMIR
            out = list(out)
            out[5] ^= 1
        return out

    rig.transport.read_filter = corrupt
    with pytest.raises(RobotSyncError) as exc:
        rig.client.sync_params(all_values(), 3)
    default = int(PARAMS[5]["default"]) & 0xFFFF
    assert (exc.value.param_id, exc.value.expected, exc.value.actual) == (5, default, default ^ 1)
    assert rig.core.regs[TLM_CFG_EPOCH] == 0
    assert all(c[2][0] != P_EPOCH_ID for c in rig.cmds() if c[1] == OP_PARAM_SET)


def test_sync_params_nak_propagates_and_does_not_write_epoch() -> None:
    rig = Rig()
    values = all_values()
    values["P_SPD_DEFAULT"] = 0  # min = 1 -> E_RANGE
    with pytest.raises(RobotNak) as exc:
        rig.client.sync_params(values, 3)
    assert exc.value.errno == E_RANGE
    assert rig.core.regs[TLM_CFG_EPOCH] == 0
    assert all(c[2][0] != P_EPOCH_ID for c in rig.cmds() if c[1] == OP_PARAM_SET)


def test_sync_params_same_epoch_but_other_dictionary_resends_everything() -> None:
    rig = Rig()
    rig.client.sync_params(all_values(), 2)
    rig.core.regs[PMIR_DICT] = 1  # отпечаток словаря не тот
    before = len(rig.cmds())
    report = rig.client.sync_params(all_values(), 2)
    assert report.sent == len(PARAM_ID) - 1
    assert len([c for c in rig.cmds()[before:] if c[1] == OP_PARAM_SET]) == len(PARAM_ID)


def test_sync_params_same_epoch_and_dictionary_writes_nothing_and_reads_only_two_registers() -> None:
    rig = Rig()
    rig.client.sync_params(all_values(), 2)
    rig.transport.log.clear()
    report = rig.client.sync_params(all_values(), 2)
    assert (report.sent, report.applied, report.epoch) == (0, False, 2)
    assert rig.transport.log == [("r", TLM_CFG_EPOCH, 1), ("r", PMIR_DICT, 1)]


def test_sync_params_updates_periods_from_pc_values() -> None:
    rig = Rig()
    values = all_values()
    values["P_WDG_TIMEOUT_MS"] = 4000
    values["P_JOG_LEASE_MS"] = 600
    rig.client.sync_params(values, 1)
    assert rig.client.heartbeat_period_s == 1.0
    assert rig.client.jog_lease_period_s == pytest.approx(0.2)


def test_sync_params_reads_stay_within_read_max() -> None:
    rig = Rig()
    rig.client.sync_params(all_values(), 1)
    assert max(e[2] for e in rig.transport.log if e[0] == "r") <= 125


# ============================================================================================
# Настоящий стек (без дублёров)
# ============================================================================================


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_stack_ping_stop_and_heartbeat_over_tcp() -> None:
    port = _free_port()
    assert port not in _FORBIDDEN_PORTS
    server = SimRobotServer(host="127.0.0.1", port=port, unit_id=ROBOT_UNIT_ID, core=RobotSimCoreV2())
    server.start()
    device = ModbusDevice(ModbusConfig(host="127.0.0.1", port=port, unit_id=ROBOT_UNIT_ID))
    try:
        deadline = time.monotonic() + 5.0
        while not device.connect():
            assert time.monotonic() < deadline, "sim не принял соединение"
            time.sleep(0.05)
        client = RobotClientV2(device, ClientV2Config.from_dict({"poll_interval_s": 0.01}))
        box, done = in_thread(
            lambda: (client.cmd("PING", []), client.stop(1), client.kick_heartbeat(), client.poll_errors()), "real"
        )
        join(done, "реальный стек")
        assert "exc" not in box, box.get("exc")
        ping, stop_result, _, errors = box["value"]
        assert list(ping.rvals)[0] == 0x0200
        assert stop_result is StopResult.ACKED
        assert errors == []
    finally:
        device.disconnect()
        server.stop()


# ============================================================================================
# Ревью 1: probe, гонка probe со стопом и пульсом, метка «в полёте», замок стопа, перекрытое событие
# ============================================================================================


def test_failed_probe_leaves_client_unprobed_and_blocks_every_write() -> None:
    from Services.robot_comm.server.sim_core import RobotSimCore

    rig = Rig()
    rig.client.probe()
    rig.transport.core = RobotSimCore()  # на том же адресе теперь прошивка v1
    with pytest.raises(WrongFirmware):
        rig.client.probe()
    for call in (
        rig.client.kick_heartbeat,
        rig.client.jog_lease,
        lambda: rig.client.stop(2),
        lambda: rig.client.cmd("PING", []),
    ):
        with pytest.raises(WrongFirmware):
            call()
    assert rig.transport.transactions == []


def _once_on_block_read(rig: Rig, action) -> None:
    """Хук на чтение блока 0x1010/80 (шаг (1) probe): ``action`` выполняется один раз, ПОСЛЕ чтения блока."""
    fired = []

    def read_filter(address: int, count: int, out: list[int]) -> list[int]:
        if address == RES_SEQ and count == 80 and not fired:
            fired.append(1)
            action()
        return out

    rig.transport.read_filter = read_filter


def test_probe_racing_stop_does_not_roll_stop_seq_back_to_stale_echo() -> None:
    rig = Rig()
    rig.client.probe()
    _once_on_block_read(rig, lambda: rig.client.stop(2))
    rig.client.probe()  # блок с эхом 0 прочитан, затем во время probe прошёл стоп seq 1
    rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.client.stop(2)
    for _ in range(5):
        rig.core.tick()
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 2]  # второе значение иное -> робот его не проигнорирует
    assert rig.core.regs[TLM_ACTIVITY] == 0


def test_probe_racing_heartbeat_does_not_roll_back_heartbeat_value() -> None:
    rig = Rig()
    rig.core.regs[HB_PC] = 10
    rig.client.probe()
    _once_on_block_read(rig, rig.client.kick_heartbeat)
    rig.client.probe()
    rig.client.kick_heartbeat()
    assert rig.transport.transactions == [[("w", HB_PC, 11)], [("w", HB_PC, 12)]]


def test_transport_error_on_cmd_write_keeps_inflight_mark_so_next_cmd_settles_first() -> None:
    rig = Rig(ticking=False)
    rig.client.probe()
    fired = []

    def boom(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and not fired:
            fired.append(1)
            raise ModbusIOError("обрыв на записи CMD")

    rig.transport.before_tx = boom
    with pytest.raises(ModbusIOError):
        rig.client.cmd("PTP_MOVE", MOVE_SHORT)
    with pytest.raises(RobotTimeout) as exc:  # робот молчит: досмотр seq 100, своей записи нет
        rig.client.cmd("PING", [])
    assert (exc.value.stage, exc.value.seq) == ("response", 100)
    assert rig.cmds() == []


def test_late_ack_of_inflight_done_seq_command_after_stop_reissues_hard_and_aborts_next_cmd() -> None:
    rig = Rig(ticking=False)
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.ticking = True
    rig.client.stop(2)  # стоп 1 обрабатывается в одном тике ДО mailbox: ход принят уже после стопа
    with pytest.raises(RobotAborted):
        rig.client.cmd("PING", [])
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 2]
    assert [c[1] for c in rig.cmds()] == [OP_PTP_MOVE]  # PING не записан
    for _ in range(3):
        rig.core.tick()
    assert rig.core.regs[TLM_ACTIVITY] == 0


def test_late_nak_of_inflight_command_after_stop_does_not_abort_next_cmd() -> None:
    rig = Rig(ticking=False)
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PTP_MOVE", [3000, -2100, -400, -1000, 0, 101])  # spd 101 -> NAK
    rig.ticking = True
    rig.client.stop(2)
    assert rig.client.cmd("PING", []).rvals[0] == 0x0200
    assert rig.stop_writes() == [1 * 4 + 2]


def test_stop_req_is_written_inside_stop_lock() -> None:
    """Пока первая запись STOP_REQ висит, вторая НЕ начинается; значения записей растут."""
    rig = Rig()
    rig.client.probe()
    in_write = threading.Event()
    release = threading.Event()
    first = [True]

    def hang_first_write(ops: list[tuple]) -> None:
        if ops[0][1] == STOP_REQ and first:
            first.clear()
            in_write.set()
            release.wait(0.3)

    rig.transport.before_tx = hang_first_write
    _, done1 = in_thread(lambda: rig.client.stop(2), "stop-1")
    assert in_write.wait(_DEADLINE_S)
    _, done2 = in_thread(lambda: rig.client.stop(2), "stop-2")
    time.sleep(0.15)
    begun = [e for e in rig.transport.log if e[0] == "tx" and e[1][0][1] == STOP_REQ]
    assert len(begun) == 1, "вторая запись STOP_REQ началась, пока первая висела: выдача seq и запись разошлись"
    release.set()
    join(done1, "stop-1")
    join(done2, "stop-2")
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 2]


def test_wait_done_ignores_foreign_vfd_event_while_move_is_running() -> None:
    """Асинхронный E_VFD_LINK посреди хода (ERR_SEQ = 0, ACTIVITY = PTP) не обрывает ожидание: итог — DONE."""
    rig = Rig()
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    base_sleep = rig.client._sleep
    ticks = [0]

    def sleep(dt: float) -> None:
        base_sleep(dt)
        ticks[0] += 1
        if ticks[0] == 20:
            rig.core.inject_vfd_link_fault()

    rig.client._sleep = sleep
    rig.client.wait_done(move.seq)
    assert ticks[0] > 20
    assert rig.core.regs[TLM_ERR_EVT] == 1 and rig.core.regs[TLM_DONE_SEQ] == move.seq


def test_wait_done_after_stop_raises_robot_aborted_with_seq_and_errno() -> None:
    rig = Rig()
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.client.stop(2)
    with pytest.raises(RobotAborted) as exc:
        rig.client.wait_done(move.seq)
    assert (exc.value.seq, exc.value.errno) == (move.seq, E_ABORTED)


def test_reconnect_between_calls_reprobes_instead_of_using_stale_error_cursor() -> None:
    rig = Rig()
    rig.core.regs[TLM_ERR_EVT] = 10
    rig.client.probe()
    rig.transport.disconnect()
    with pytest.raises(RobotNotConnectedError):
        rig.client.poll_errors()
    rig.core.regs[TLM_ERR_EVT] = 4  # робот перезапустился
    rig.transport.connect()
    assert rig.client.poll_errors() == []  # без перепроверки: missed = 65530


@pytest.mark.parametrize(
    ("ours_before", "echo_seq", "superseded"),
    [
        (16382, 1, True),  # круг 16383 -> 1: «новее» на 1
        (16382, 8191, True),  # ровно полкруга по модулю 16383 (по модулю 16384 было бы 8192)
        (16382, 8192, False),  # дальше полкруга — эхо старее
        (16382, 0, False),  # 0 вне круга (эхо с загрузки) — не новее
    ],
)
def test_stop_superseded_window_is_modulo_16383(ours_before: int, echo_seq: int, superseded: bool) -> None:
    rig = Rig(ticking=False, config={"stop_echo_timeout_s": 0.3, "poll_interval_s": 0.1})
    rig.core.regs[TLM_STOP_ACK] = ours_before * 4 + 2

    def echo(ops: list[tuple]) -> None:
        if ops[0][1] == STOP_REQ:
            rig.core.regs[TLM_STOP_ACK] = echo_seq * 4 + 3

    rig.transport.after_tx = echo
    if superseded:
        assert rig.client.stop(2) is StopResult.SUPERSEDED
    else:
        with pytest.raises(RobotTimeout):
            rig.client.stop(2)
    assert rig.stop_writes() == [16383 * 4 + 2]


# ============================================================================================
# Ревью 2: О5 на путях с исключением, probe не снимает метку done_seq, stop без is_connected, уровень не понижается
# ============================================================================================

TLM_Y = 0x1045


def _ticks(rig: Rig, n: int = 3) -> None:
    for _ in range(n):
        rig.core.tick()


def _fail_read_once(rig: Rig, address: int, count: int) -> dict:
    """Одно чтение (address, count) падает ModbusIOError, когда armed['on'] взведён."""
    armed = {"on": False}

    def read_filter(a: int, c: int, out: list[int]) -> list[int]:
        if armed["on"] and a == address and c == count:
            armed["on"] = False
            raise ModbusIOError("инъекция: сбой чтения")
        return out

    rig.transport.read_filter = read_filter
    return armed


def _assert_move_stopped_by_reissue(rig: Rig, expected_writes: list[int]) -> None:
    assert rig.stop_writes() == expected_writes
    _ticks(rig)
    assert rig.core.regs[TLM_ACTIVITY] == 0
    assert rig.core.regs[TLM_ERRNO_LAST] == E_ABORTED


def test_o5_survives_res_read_failure_after_stop_in_window() -> None:
    """B2: стоп в окне, чтение RES падает -> метка остаётся, следующий cmd() повторяет стоп и поднимает RobotAborted."""
    rig = Rig()
    rig.client.probe()
    armed = _fail_read_once(rig, RES_SEQ, 12)
    fired = []

    def stop_in_window(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and not fired:
            fired.append(1)
            rig.client.stop(2)
            armed["on"] = True

    rig.transport.after_tx = stop_in_window
    with pytest.raises(ModbusIOError):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.transport.after_tx = None
    with pytest.raises(RobotAborted):
        rig.client.cmd("PING", [])
    _assert_move_stopped_by_reissue(rig, [1 * 4 + 2, 2 * 4 + 2])


def test_o5_survives_failed_reissue_write() -> None:
    """B3: повторная запись стопа упала -> метка остаётся, следующий cmd() пишет стоп снова и поднимает RobotAborted."""
    rig = Rig()
    rig.client.probe()
    fired = []

    def stop_in_window(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and not fired:
            fired.append(1)
            rig.client.stop(2)

    def fail_reissue(ops: list[tuple]) -> None:
        if ops[0][1] == STOP_REQ and rig.stop_writes():
            raise ModbusIOError("инъекция: сбой записи повторного стопа")

    rig.transport.after_tx = stop_in_window
    rig.transport.before_tx = fail_reissue
    with pytest.raises(ModbusIOError):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.transport.after_tx = None
    rig.transport.before_tx = None
    with pytest.raises(RobotAborted):
        rig.client.cmd("PING", [])
    _assert_move_stopped_by_reissue(rig, [1 * 4 + 2, 2 * 4 + 2])  # после ошибки stale -> probe -> seq 2 не потерян


def test_o5_survives_res_read_failure_on_settle_path() -> None:
    """B4: поздний ACK, чтение RES при досмотре падает -> метка остаётся, второй cmd() получает RobotAborted."""
    rig = Rig(ticking=False)
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.ticking = True
    rig.client.stop(2)
    armed = _fail_read_once(rig, RES_SEQ, 12)
    armed["on"] = True
    with pytest.raises(ModbusIOError):
        rig.client.cmd("PING", [])
    with pytest.raises(RobotAborted):
        rig.client.cmd("PING", [])
    _assert_move_stopped_by_reissue(rig, [1 * 4 + 2, 2 * 4 + 2])


def test_probe_between_timeout_and_next_cmd_keeps_done_seq_mark() -> None:
    """B1: timeout -> стоп -> probe -> PING: метка done_seq пережила probe, О5 сработал."""
    rig = Rig(ticking=False)
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.ticking = True
    rig.client.stop(2)
    rig.client.probe()
    with pytest.raises(RobotAborted):
        rig.client.cmd("PING", [])
    _assert_move_stopped_by_reissue(rig, [1 * 4 + 2, 2 * 4 + 2])


def test_probe_drops_inflight_mark_of_instant_opcode() -> None:
    rig = Rig(ticking=False)
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PING", [])
    rig.client.probe()
    rig.ticking = True
    assert rig.client.cmd("PING", []).seq == 101  # метки нет: пишет сразу, без досмотра seq 100


def test_stop_writes_after_transient_transport_error_on_modbus_device() -> None:
    """B5: одна случайная ошибка записи пульса -> ModbusDevice.is_connected False; stop(2) всё равно пишет STOP_REQ."""
    core = RobotSimCoreV2()
    log: list[tuple[int, object]] = []

    class FakeSdk:
        fail = False

        def connect(self) -> bool:
            return True

        def close(self) -> None:
            pass

        def read_holding(self, address: int, count: int) -> list[int]:
            core.tick()
            return core.read(address, count)

        def write_register(self, address: int, value: int) -> None:
            if self.fail:
                self.fail = False
                raise ModbusIOError("случайная ошибка")
            log.append((address, value))
            core.write(address, [value])

        def write_registers(self, address: int, values: list[int]) -> None:
            log.append((address, list(values)))
            core.write(address, list(values))

    sdk = FakeSdk()
    device = ModbusDevice(ModbusConfig(host="127.0.0.1", port=1, unit_id=ROBOT_UNIT_ID), client=sdk)
    assert device.connect()
    client = RobotClientV2(device, ClientV2Config.from_dict({}))
    client.probe()
    sdk.fail = True
    with pytest.raises(ModbusIOError):
        client.kick_heartbeat()
    assert device.is_connected is False  # предусловие: устройство считает связь оборванной
    try:
        client.stop(2)
    except Exception as exc:  # noqa: BLE001 — эхо могло не прочитаться на «оборванном» устройстве; важна запись
        assert not isinstance(exc, RobotNotConnectedError), "stop не должен упираться в is_connected"
    assert [value for address, value in log if address == STOP_REQ] == [1 * 4 + 2]


def test_stop_is_still_blocked_for_unprobed_client_on_dead_transport() -> None:
    rig = Rig(connect=False)
    with pytest.raises(RobotNotConnectedError):
        rig.client.stop(2)
    assert rig.transport.transactions == []


def test_stop_after_failed_probe_is_blocked() -> None:
    from Services.robot_comm.server.sim_core import RobotSimCore

    rig = Rig()
    rig.client.probe()
    rig.transport.core = RobotSimCore()
    with pytest.raises(WrongFirmware):
        rig.client.probe()
    rig.transport.disconnect()
    rig.transport.connect()
    with pytest.raises(WrongFirmware):
        rig.client.stop(2)
    assert rig.transport.transactions == []


def test_hard_then_soft_before_robot_tick_writes_hard_twice_and_move_is_stopped() -> None:
    """B6: HARD не подтверждён, SOFT из другого потока — пишется HARD; ход прерван, цели не достиг."""
    rig = Rig(config={"stop_echo_timeout_s": 20.0, "soft_echo_timeout_s": 20.0})
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    _ticks(rig, 20)
    go = threading.Event()  # робот «молчит» (часы и тики стоят), пока обе записи не лежат в регистре
    base_sleep = rig.sleep
    rig.client._sleep = lambda dt: base_sleep(dt) if go.is_set() else time.sleep(0.005)

    def wait_writes(n: int) -> None:
        deadline = time.monotonic() + _DEADLINE_S
        while len(rig.stop_writes()) < n:
            assert time.monotonic() < deadline, "запись стопа не появилась"
            time.sleep(0.005)

    hard, hard_done = in_thread(lambda: rig.client.stop(2), "stop-hard")
    wait_writes(1)
    soft, soft_done = in_thread(lambda: rig.client.stop(1), "stop-soft")
    wait_writes(2)
    go.set()
    join(hard_done, "stop-hard")
    join(soft_done, "stop-soft")
    assert "exc" not in hard and "exc" not in soft, (hard.get("exc"), soft.get("exc"))
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 2]  # второй стоп записан с уровнем HARD
    assert soft["value"] is StopResult.ACKED
    assert hard["value"] in (StopResult.ACKED, StopResult.SUPERSEDED)
    _ticks(rig, 450)  # хода хватило бы с запасом до цели
    assert rig.core.regs[TLM_ACTIVITY] == 0
    assert rig.core.regs[TLM_ERRNO_LAST] == E_ABORTED
    assert rig.core.regs[TLM_DONE_SEQ] != move.seq
    y_raw = rig.core.regs[TLM_Y] - 0x10000 if rig.core.regs[TLM_Y] >= 0x8000 else rig.core.regs[TLM_Y]
    assert y_raw < -1500  # цель по Y = -1500 (0.1 мм), ход остановлен до неё


def test_soft_is_written_as_hard_until_hard_is_acknowledged_then_as_soft() -> None:
    rig = Rig(ticking=False, config={"stop_echo_timeout_s": 0.3, "poll_interval_s": 0.1})
    with pytest.raises(RobotTimeout):
        rig.client.stop(2)  # эха нет: HARD не подтверждён
    with pytest.raises(RobotTimeout):
        rig.client.stop(1)
    rig.ticking = True
    assert rig.client.stop(1) is StopResult.ACKED  # пишется HARD, подтверждается
    assert rig.client.stop(1) is StopResult.ACKED  # подтверждённого сильного больше нет
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 2, 3 * 4 + 2, 4 * 4 + 1]


def test_hard_waiter_ignores_newer_echo_with_lower_level() -> None:
    rig = Rig(ticking=False, config={"stop_echo_timeout_s": 0.3, "poll_interval_s": 0.1})

    def soft_echo_newer(ops: list[tuple]) -> None:
        if ops[0][1] == STOP_REQ:
            rig.core.regs[TLM_STOP_ACK] = 2 * 4 + 1  # эхо новее (seq 2), но SOFT

    rig.transport.after_tx = soft_echo_newer
    with pytest.raises(RobotTimeout):
        rig.client.stop(2)


def test_hard_waiter_accepts_newer_echo_with_level_not_lower() -> None:
    rig = Rig(ticking=False)

    def halt_echo_newer(ops: list[tuple]) -> None:
        if ops[0][1] == STOP_REQ:
            rig.core.regs[TLM_STOP_ACK] = 2 * 4 + 3

    rig.transport.after_tx = halt_echo_newer
    assert rig.client.stop(2) is StopResult.SUPERSEDED


def test_probe_racing_error_poll_does_not_repeat_event() -> None:
    rig = Rig()
    rig.client.probe()

    def event_and_poll() -> None:
        rig.core.regs[TLM_ERR_EVT] = 1  # событие пришло после чтения блока probe
        assert rig.client.poll_errors() == []  # вложенный probe поставил курсор на 1

    _once_on_block_read(rig, event_and_poll)
    rig.client.probe()
    assert rig.client.poll_errors() == []  # курсор не откатился на устаревшее 0


def test_probe_racing_jog_lease_does_not_roll_back_jog_value() -> None:
    rig = Rig()
    rig.core.regs[JOG_LEASE] = 10
    rig.client.probe()
    _once_on_block_read(rig, rig.client.jog_lease)
    rig.client.probe()
    rig.client.jog_lease()
    assert rig.transport.transactions == [[("w", JOG_LEASE, 11)], [("w", JOG_LEASE, 12)]]


# ============================================================================================
# Ревью 3: молчащий слот после стопа, эхо везде, stale по исключению и по соединению, журнал эха
# ============================================================================================

CMD_SEQ_REG = 0x1001


def _timeout_stop_timeout_rig() -> Rig:
    """r3b: PTP без ответа -> стоп без эха -> PING без ответа (метка done_seq должна пережить этот досмотр)."""
    rig = Rig(ticking=False)
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PTP_MOVE", MOVE_LONG)
    with pytest.raises(RobotTimeout):
        rig.client.stop(2)  # записан, робот молчит
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PING", [])  # досмотр seq 100: тайм-аут, поколение стопа изменилось, слот жив
    return rig


def test_settle_timeout_after_stop_keeps_done_seq_mark_and_robot_late_ack_aborts_next_cmd() -> None:
    rig = _timeout_stop_timeout_rig()
    rig.core.tick()  # робот проснулся: стоп (эхо), затем mailbox принимает PTP уже после стопа
    rig.ticking = True
    with pytest.raises(RobotAborted):
        rig.client.cmd("PING", [])
    assert [c[1] for c in rig.cmds()] == [OP_PTP_MOVE]  # PING не записан
    _assert_move_stopped_by_reissue(rig, [1 * 4 + 2, 2 * 4 + 2])


def test_settle_timeout_after_stop_drops_mark_when_slot_is_dead_after_robot_reset() -> None:
    rig = _timeout_stop_timeout_rig()
    for address in (CMD_FLAG, CMD_SEQ_REG, TLM_STOP_ACK, STOP_REQ):  # робот перезагружен: регистры сброшены
        rig.core.regs[address] = 0
    rig.ticking = True
    with pytest.raises(RobotTimeout):  # слот мёртв: метка снимается, но этот вызов всё равно ничего не пишет
        rig.client.cmd("PING", [])
    result = rig.client.cmd("PING", [])
    assert result.rvals[0] == 0x0200
    assert [c[1] for c in rig.cmds()] == [OP_PTP_MOVE, OP_PING]


def test_settle_timeout_drops_mark_when_firmware_took_slot_and_died_without_response() -> None:
    """Lockout: CMD_FLAG = 0, CMD_SEQ = наш seq, RES нет -> слот не исполнится никогда, метка снимается."""
    rig = _timeout_stop_timeout_rig()
    rig.core.regs[CMD_FLAG] = 0  # прошивка забрала слот и перезапустилась, не записав RES
    with pytest.raises(RobotTimeout):  # этот вызов снимает метку, но сам ничего не пишет
        rig.client.cmd("PING", [])
    rig.ticking = True
    assert rig.client.cmd("PING", []).rvals[0] == 0x0200  # следующий пишет
    assert [c[1] for c in rig.cmds()] == [OP_PTP_MOVE, OP_PING]


def test_settle_timeout_without_stop_still_drops_mark() -> None:
    rig = Rig(ticking=False)
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PTP_MOVE", MOVE_SHORT)
    with pytest.raises(RobotTimeout):
        rig.client.cmd("PING", [])  # досмотр seq 100 без стопа: метка снята
    with pytest.raises(RobotTimeout) as exc:
        rig.client.cmd("PING", [])  # метки нет: записан новый seq 101 (с меткой дал бы снова seq 100 без записи)
    assert exc.value.seq == 101


def test_hard_echo_seen_by_cmd_base_read_clears_pending_so_next_soft_is_written_as_soft() -> None:
    """C1: HALT без эха, робот ответил, эхо прочитано базой cmd() -> SOFT пишется как SOFT, а не как HALT."""
    rig = Rig(ticking=False)
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.stop(3)
    rig.core.tick()  # эхо HALT появилось (серво выключено)
    rig.ticking = True
    rig.client.cmd("SERVO", [1])
    rig.client.cmd("PTP_MOVE", MOVE_LONG)
    with pytest.raises(RobotTimeout):  # SOFT посреди хода отвечает эхом в конце примитива — здесь не успеваем
        rig.client.stop(1)
    assert rig.stop_writes() == [1 * 4 + 3, 2 * 4 + 1]


def test_hard_echo_seen_by_wait_done_clears_pending() -> None:
    rig = Rig()
    rig.client.probe()
    move = rig.client.cmd("PTP_MOVE", MOVE_LONG)
    rig.ticking = False
    with pytest.raises(RobotTimeout):
        rig.client.stop(2)  # записан, эха нет
    rig.core.tick()  # эхо HARD, ход прерван
    rig.ticking = True
    with pytest.raises(RobotAborted):
        rig.client.wait_done(move.seq)  # его чтение TLM видит эхо
    assert rig.client.stop(1) is StopResult.ACKED
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 1]


def test_transport_exception_marks_client_stale_so_silent_reconnect_to_other_firmware_is_caught() -> None:
    from Services.robot_comm.server.sim_core import RobotSimCore

    rig = Rig()
    rig.client.probe()
    armed = _fail_read_once(rig, TLM_ERR_SEQ, 3)
    armed["on"] = True
    with pytest.raises(ModbusIOError):
        rig.client.poll_errors()
    rig.transport.core = RobotSimCore()  # транспорт тихо переподключился к иной прошивке
    with pytest.raises(WrongFirmware):
        rig.client.kick_heartbeat()
    assert rig.transport.transactions == []


def test_silent_reconnect_on_modbus_device_is_caught_by_connection_id() -> None:
    """C2: без единой ошибки на пути клиента: disconnect -> иная прошивка -> connect -> kick_heartbeat."""
    from Services.robot_comm.server.sim_core import RobotSimCore

    cores: list = [RobotSimCoreV2()]
    log: list[tuple[int, object]] = []

    class FakeSdk:
        def connect(self) -> bool:
            return True

        def close(self) -> None:
            pass

        def read_holding(self, address: int, count: int) -> list[int]:
            cores[0].tick()
            return cores[0].read(address, count)

        def write_register(self, address: int, value: int) -> None:
            log.append((address, value))
            cores[0].write(address, [value])

        def write_registers(self, address: int, values: list[int]) -> None:
            log.append((address, list(values)))
            cores[0].write(address, list(values))

    ticks = iter(range(1, 1000))
    device = ModbusDevice(
        ModbusConfig(host="127.0.0.1", port=1, unit_id=ROBOT_UNIT_ID),
        client=FakeSdk(),
        clock=lambda: float(next(ticks)),
    )
    assert device.connect()
    client = RobotClientV2(device, ClientV2Config.from_dict({}))
    client.probe()
    client.kick_heartbeat()
    assert [v for a, v in log if a == HB_PC] == [1]
    device.disconnect()
    cores[0] = RobotSimCore()  # на том же адресе теперь прошивка v1
    assert device.connect()
    with pytest.raises(WrongFirmware):
        client.kick_heartbeat()
    assert [v for a, v in log if a == HB_PC] == [1]  # второй записи нет


def test_stop_of_probed_client_still_writes_when_stale() -> None:
    rig = Rig()
    rig.client.probe()
    armed = _fail_read_once(rig, TLM_ERR_SEQ, 3)
    armed["on"] = True
    with pytest.raises(ModbusIOError):
        rig.client.poll_errors()  # клиент stale
    assert rig.client.stop(2) is StopResult.ACKED
    assert rig.stop_writes() == [1 * 4 + 2]


def test_stale_reprobe_does_not_reuse_unacknowledged_stop_value() -> None:
    """Повторный probe считает следующий stop_seq от более нового из STOP_REQ и эха: иначе робот проигнорирует стоп."""
    rig = Rig(ticking=False, config={"stop_echo_timeout_s": 0.3, "poll_interval_s": 0.1})
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.stop(2)  # записан 6, эха нет
    rig.client.probe()
    with pytest.raises(RobotTimeout):
        rig.client.stop(2)
    assert rig.stop_writes() == [1 * 4 + 2, 2 * 4 + 2]


def test_waiter_completes_from_echo_log_when_other_reader_saw_its_echo_before_it_was_overwritten() -> None:
    rig = Rig(ticking=False, config={"stop_echo_timeout_s": 0.3, "poll_interval_s": 0.1})
    seen = []

    def overwritten_echo(address: int, count: int, out: list[int]) -> list[int]:
        if address == TLM_STOP_ACK and count == 1 and not seen:
            seen.append(1)
            rig.client._note_echo(1 * 4 + 2)  # другой читатель (cmd/wait_done) видел наше эхо...
            return [2 * 4 + 1]  # ...а к нашему опросу его перекрыло более новое эхо ниже уровнем
        return out

    rig.transport.read_filter = overwritten_echo
    assert rig.client.stop(2) is StopResult.ACKED
