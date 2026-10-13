"""Тесты автора T3.2: порядок пинг-понга, метка стопа, исключения ``run_chunks``, блоки FC16, отказ до записи.

Стенд — ``HookTransport`` (``FakeRobotTransport`` с журналом чтений/записей и хуками ``before_tx`` / ``after_tx`` /
``read_filter``) над настоящим ``RobotSimCoreV2`` при ``ticks_per_read=0``: время робота идёт только из ``sleep``
клиента (он делает ``core.tick()``), часы клиента — ручные. Хуки стоят на самой записи. Один тест
(``test_live_server_run``) собран из настоящих ``SimRobotServer`` + ``ModbusDevice``. Адреса, коды и ожидания —
литералы из protocol-spec, не из проверяемого кода. Вызов ``run_chunks`` — в daemon-потоке с дедлайном.

Stability: lite
"""

from __future__ import annotations

import math
import socket
import threading
import time

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.robot_comm.core import wire_v2
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.errors import RobotAborted, RobotNak, RobotTimeout
from Services.robot_comm.programs import (
    Action,
    CompileError,
    FrameDef,
    Move,
    Point,
    Program,
    Record,
    Scenario,
    compile_program,
)
from Services.robot_comm.programs.generators import draw
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.server.sim_robot import SimRobotServer
from Services.robot_comm.testing.fake_transport import FakeRobotTransport
from Services.robot_comm.tests.e2e_rig_v2 import WS_PARAMS

# --- литералы протокола (protocol-spec §2, §3, §7) ------------------------------------------
CMD_FLAG, CMD_SEQ = 0x1000, 0x1001
RES_SEQ, STOP_REQ = 0x1010, 0x1021
TLM_BASE, TLM_COUNT = 0x1040, 32
DONE_OFF = 0x1051 - 0x1040  # TLM_DONE_SEQ в блоке TLM
TLM_STOP_ACK = 0x105C
TLM_ACTIVITY, TLM_ERR_SEQ = 0x1043, 0x1052  # TLM_ERRNO_LAST = 0x1053 читается вторым словом
E_ABORTED = 13
SC_BASE, SC_WORDS = 0x1400, 330  # SC_CAP 55 * SC_STRIDE 6
OP_SC_RUN, OP_PTP_MOVE = 0x30, 0x10
HARD = 2
E_BUSY = 4
HALF = 27
WRITE_CHUNK = 30

PARAMS = {
    "P_WS_R_MIN": 100,
    "P_WS_R_MAX": 600,
    "P_WS_Z_MIN": -150,
    "P_WS_Z_MAX": 0,
    "P_WS_RZ_MIN": -360,
    "P_WS_RZ_MAX": 360,
    "P_WS_ANG_MIN": -165,
    "P_WS_ANG_MAX": 165,
    "P_WS_BOX_EN": 0,
    "P_WS_X_MIN": -600,
    "P_WS_X_MAX": 600,
    "P_WS_Y_MIN": -600,
    "P_WS_Y_MAX": 600,
    "P_HAND": 1,
}

MOVE_LONG = [3000, -1500, -400, -1000, 0, 1]  # из дома 60 мм на 1 % — сотни тиков
_DEADLINE_S = 30.0
_FORBIDDEN_PORTS = frozenset({5021, 8765, 8766, 8091, 8092})


class HookTransport(FakeRobotTransport):
    """Fake с журналом чтений (с прочитанным) и записей и хуками на запись."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log: list[tuple] = []  # ("r", addr, count, out) | ("tx", ops)
        self.before_tx = None
        self.after_tx = None
        self.read_filter = None

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        out = super().read_registers(address, count)
        if self.read_filter:
            out = self.read_filter(address, count, out)
        self.log.append(("r", address, count, list(out)))
        return out

    def transaction(self, ops: list[tuple]) -> bool:
        self.log.append(("tx", list(ops)))
        if self.before_tx:
            self.before_tx(ops)
        ok = super().transaction(ops)
        if self.after_tx:
            self.after_tx(ops)
        return ok


class Rig:
    def __init__(self, *, core: RobotSimCoreV2 | None = None, servo: bool = True) -> None:
        self.core = core if core is not None else RobotSimCoreV2()
        self.transport = HookTransport(core=self.core, ticks_per_read=0)
        self.transport.connect()
        self.now = 0.0
        self._tick_lock = threading.Lock()
        cfg = ClientV2Config.from_dict({"done_timeout_s": 100000.0})
        self.client = RobotClientV2(self.transport, cfg, rng=_FixedRng(100), clock=lambda: self.now, sleep=self.sleep)
        self.client.probe()
        if servo:
            self.client.servo(True)

    def sleep(self, dt: float) -> None:
        with self._tick_lock:
            self.now += dt
            self.core.tick()


class _FixedRng:
    def __init__(self, value: int) -> None:
        self.value = value

    def randint(self, a: int, b: int) -> int:  # noqa: ARG002 — сигнатура random.Random
        return self.value


def bounded(fn, deadline: float = _DEADLINE_S):
    """Вызов в daemon-потоке с дедлайном; исключение уходит в тест."""
    box: dict = {}

    def body() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение уходит в тест
            box["exc"] = exc

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        pytest.fail(f"зависание: вызов не завершился за {deadline} с")
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


def circle(n: int, ang_from: float = -60.0, ang_to: float = 60.0) -> Scenario:
    """n точек на окружности r = 300, z = -50: 0 JOINT, каждая 4-я и последняя LINE, прочие LINE_PASS."""
    records = []
    for i in range(n):
        angle = math.radians(ang_from + (ang_to - ang_from) * i / (n - 1))
        kind = "JOINT" if i == 0 else "LINE" if (i % 4 == 3 or i == n - 1) else "LINE_PASS"
        records.append(
            Record(
                x=300.0 * math.cos(angle),
                y=300.0 * math.sin(angle),
                z=-50.0,
                rz=0.0,
                kind=kind,
                action="NONE",
                aparam=0,
            )
        )
    return Scenario(records=tuple(records), step_of=tuple(range(n)))


# --- разбор журнала ----------------------------------------------------------------------------


def is_cmd_tx(ops: list[tuple]) -> bool:
    return len(ops) == 2 and ops[0][0] == "wm" and ops[0][1] == CMD_SEQ and ops[1] == ("w", CMD_FLAG, 1)


def sc_run_of(entry: tuple) -> tuple[int, list[int]] | None:
    """(seq, [count, sc_id, offset, spd_pct, accel, accur]) для записи журнала SC_RUN, иначе None."""
    if entry[0] != "tx" or not is_cmd_tx(entry[1]):
        return None
    seq, opcode, _argc, *args = entry[1][0][2]
    return (seq, args) if opcode == OP_SC_RUN else None


def is_buf_tx(entry: tuple) -> bool:
    return entry[0] == "tx" and any(
        op[0] == "wm" and op[1] < SC_BASE + SC_WORDS and SC_BASE < op[1] + len(op[2]) for op in entry[1]
    )


def stop_values(entries: list[tuple]) -> list[int]:
    return [op[2] for e in entries if e[0] == "tx" for op in e[1] if op[0] == "w" and op[1] == STOP_REQ]


def run_indices(log: list[tuple]) -> list[int]:
    return [i for i, e in enumerate(log) if sc_run_of(e) is not None]


# ============================================================================================
# порядок и раскладка
# ============================================================================================


def test_chunk_order_run_upload_done() -> None:
    """SC_RUN k -> все блоки куска k+1 -> чтение TLM с DONE_SEQ == seq k -> SC_RUN k+1 (60 записей: 3 куска)."""
    rig = Rig()
    report = bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    log = rig.transport.log
    runs = run_indices(log)
    assert len(runs) == 3 == len(report.chunks)
    for k in range(2):
        seq = sc_run_of(log[runs[k]])[0]
        done_at = next(
            i
            for i in range(runs[k], len(log))
            if log[i][:3] == ("r", TLM_BASE, TLM_COUNT) and log[i][3][DONE_OFF] == seq
        )
        blocks = [i for i in range(runs[k], runs[k + 1]) if is_buf_tx(log[i])]
        assert blocks, f"кусок {k + 1} не загружен между SC_RUN {k} и SC_RUN {k + 1}"
        assert all(runs[k] < i < done_at for i in blocks), f"блок куска {k + 1} записан после DONE куска {k}"
        assert done_at < runs[k + 1]
    assert not [i for i in range(runs[2], len(log)) if is_buf_tx(log[i])], "после последнего SC_RUN загрузка"


def test_offsets_alternate() -> None:
    """Смещения SC_RUN 0, 27, 0; первый блок загрузки куска k лежит по SC_BASE + offset_k * 6."""
    rig = Rig()
    report = bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    log = rig.transport.log
    runs = [sc_run_of(e)[1] for e in log if sc_run_of(e) is not None]
    assert [offset for _count, _sc_id, offset, *_ in runs] == [0, 27, 0]
    assert [sc_id for _count, sc_id, _offset, *_ in runs] == [1, 2, 3]
    assert [c[2] for c in report.chunks] == [0, 27, 0]
    run_at = run_indices(log)
    first_block = [next(i for i in range(len(log)) if is_buf_tx(log[i]))]
    first_block += [next(i for i in range(run_at[k], len(log)) if is_buf_tx(log[i])) for k in range(2)]
    assert [log[i][1][0][1] for i in first_block] == [0x1400, 0x1400 + 27 * 6, 0x1400]


def test_fc16_blocks_le_write_chunk() -> None:
    """Каждая запись буфера сценария — не больше 30 регистров; блок в 30 регистров есть (тест не пуст)."""
    rig = Rig()
    bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    sizes = [len(op[2]) for e in rig.transport.log if is_buf_tx(e) for op in e[1]]
    assert sizes
    assert max(sizes) <= WRITE_CHUNK
    assert WRITE_CHUNK in sizes


# --- T3.9: стартовое состояние SC_RUN куска k+1 = состояние конца куска k -------------------

_SHEET = FrameDef(name="sheet", origin=(300, -100, -100), on_x=(400, -100, -100), in_plane=(300, 0, -100))
_STROKE100 = (tuple((0.5 * j, 20) for j in range(100)),)
_ACC30_POINTS = {f"p{j}": Point(name=f"p{j}", x=300 + 5 * j, y=-100, z=-100, rz=0, hand=1) for j in range(30)}


def _acc30(*, accur_zero_after_p2: bool) -> Scenario:
    """30 записей: ACCEL 30000 после записи 1, ACCUR 1 после записи 2 (и ACCUR 0 после записи 3 у ``ACC30Z``)."""
    steps: list[Move | Action] = [
        Move(point="p0", kind="JOINT"),
        Action(act="ACCEL", value=30000),
        Move(point="p1", kind="LINE"),
        Action(act="ACCUR", value=1),
    ]
    for j in range(2, 30):
        steps.append(Move(point=f"p{j}", kind="LINE"))
        if accur_zero_after_p2 and j == 2:
            steps.append(Action(act="ACCUR", value=0))
    program = Program(name="acc30z" if accur_zero_after_p2 else "acc30", steps=tuple(steps))
    return compile_program(program, _ACC30_POINTS, {}, WS_PARAMS)


def _stroke100() -> Scenario:
    gp = draw(_STROKE100, frame="sheet", hand=1, rz=0.0, pen_down=0.0, pen_up=5.0)
    return compile_program(gp.program, gp.points, {"sheet": _SHEET}, WS_PARAMS)


def test_run_chunks_passes_end_state_of_previous_chunk() -> None:
    """``SC_RUN`` куска k+1 несёт последние SPEED_PCT / ACCEL / ACCUR записей ``0..end_k``; кусок 1 — нули.

    По журналу записей (``sc_run_of``): ``[count, sc_id, offset, spd_pct, accel, accur]``. Штрих 100 точек (SPEED_PCT
    30 в записи 1, 100 в записи 100): куски 2-5 идут на 30, последний кусок свою 100 не передаёт никому.
    ``ACC30`` — ACCEL 30000 и ACCUR 1 (HIGH, кодом 2). ``ACC30Z`` — после ACCUR 1 стоит ACCUR 0: ROUGH уходит
    кодом 1, а не 0 «не задано» (ловушка совпавших констант: ``P_ACCUR_DEFAULT`` тоже 0). НЕ доказывает: влияние
    ACCEL/ACCUR на движение (sim их только хранит), прошивку (обработчик ``SC_RUN`` — Ф4).
    """
    cases = [
        (
            _stroke100(),
            [
                [2, 1, 0, 0, 0, 0],
                [27, 2, 27, 30, 0, 0],
                [27, 3, 0, 30, 0, 0],
                [27, 4, 27, 30, 0, 0],
                [19, 5, 0, 30, 0, 0],
            ],
        ),
        (_acc30(accur_zero_after_p2=False), [[27, 1, 0, 0, 0, 0], [3, 2, 27, 0, 30000, 2]]),
        (_acc30(accur_zero_after_p2=True), [[27, 1, 0, 0, 0, 0], [3, 2, 27, 0, 30000, 1]]),
    ]
    for scenario, expected in cases:
        rig = Rig()
        bounded(lambda scenario=scenario, rig=rig: rig.client.run_chunks(scenario, params=WS_PARAMS), 120.0)
        runs = [sc_run_of(e)[1] for e in rig.transport.log if sc_run_of(e) is not None]
        assert runs == expected


# ============================================================================================
# метка стопа
# ============================================================================================


def test_foreign_stop_before_next_sc_run_stops_after_ack() -> None:
    """Чужой HARD в STOP_REQ на самой записи SC_RUN куска 1: после ACK клиент пишет свой HARD и бросает RobotAborted.

    Проверка метки ДО SC_RUN чужой стоп не видит (он приходит вместе с командой) — ловит только проверка после ACK.
    Управление возвращается только после остановки робота: в момент возврата робот в простое, событие обрыва
    (ERR_SEQ = seq SC_RUN куска 1, ERRNO 13) уже выставлено. Время робота идёт только из ``sleep`` клиента, поэтому
    состояние ядра после возврата заморожено — это снимок «в момент возврата».
    """
    rig = Rig()
    foreign = (500 << 2) | HARD

    def before_tx(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and ops[0][2][1] == OP_SC_RUN and ops[0][2][4] == 2:  # sc_id 2 = кусок 1
            rig.core.write(STOP_REQ, [foreign])

    rig.transport.before_tx = before_tx
    with pytest.raises(RobotAborted):
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    assert rig.core.read(TLM_ACTIVITY, 1) == [0], "run_chunks вернул управление, пока робот исполняет кусок"
    log = rig.transport.log
    runs = run_indices(log)
    assert len(runs) == 2, "кусок 2 запущен после чужого стопа"
    assert rig.core.read(TLM_ERR_SEQ, 2) == [sc_run_of(log[runs[1]])[0], E_ABORTED]
    ours = stop_values(log[runs[1] :])
    assert ours, "после ACK SC_RUN клиент не записал стоп"
    assert all(v & 3 == HARD for v in ours)
    assert foreign not in ours


def test_o5_abort_inside_sc_run_returns_after_robot_stopped() -> None:
    """Свой stop(HARD) между записью SC_RUN куска 1 и его ACK -> О5 в cmd() -> RobotAborted после остановки робота.

    Стоп в простое робот подтверждает эхом и затем принимает SC_RUN; клиент на ACK видит сменившееся поколение,
    повторяет стоп без ожидания эха (О5) — run_chunks обязан дождаться обрыва команды. Снимок ядра в момент возврата.
    """
    rig = Rig()
    state = {"done": False}

    def after_tx(ops: list[tuple]) -> None:
        if not state["done"] and is_cmd_tx(ops) and ops[0][2][1] == OP_SC_RUN and ops[0][2][4] == 2:
            state["done"] = True
            rig.client.stop(HARD)

    rig.transport.after_tx = after_tx
    with pytest.raises(RobotAborted) as info:
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    log = rig.transport.log
    runs = run_indices(log)
    assert len(runs) == 2
    seq1 = sc_run_of(log[runs[1]])[0]
    assert info.value.seq == seq1
    assert len(stop_values(log[runs[1] :])) == 2, "ожидались свой стоп и повтор стопа О5"
    assert rig.core.read(TLM_ACTIVITY, 1) == [0], "run_chunks вернул управление, пока робот исполняет кусок"
    assert rig.core.read(TLM_ERR_SEQ, 2) == [seq1, E_ABORTED]


def test_failed_stop_after_ack_raises_transport_error() -> None:
    """Чужой стоп на SC_RUN куска 1, а запись своего STOP_REQ падает ConnectionError -> наружу ConnectionError.

    Недоставленный стоп не прячется за RobotAborted («стоп уже прошёл»): вызывающий узнаёт, что стоп не доставлен.
    """
    rig = Rig()
    foreign = (500 << 2) | HARD

    def before_tx(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and ops[0][2][1] == OP_SC_RUN and ops[0][2][4] == 2:
            rig.core.write(STOP_REQ, [foreign])
        if any(op[0] == "w" and op[1] == STOP_REQ for op in ops):
            raise ConnectionError("link down")

    rig.transport.before_tx = before_tx
    with pytest.raises(ConnectionError) as info:
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    assert not isinstance(info.value, RobotAborted)
    assert any("кусок принят" in note for note in getattr(info.value, "__notes__", []))
    assert len(run_indices(rig.transport.log)) == 2


def test_param_get_signed_roundtrip() -> None:
    """Знаковый параметр: param_set("P_WS_Z_MIN", -1500) -> param_get == -1500 (не 64036)."""
    rig = Rig(servo=False)
    rig.client.param_set("P_WS_Z_MIN", -1500)
    assert rig.client.param_get("P_WS_Z_MIN") == -1500


def test_stop_ack_change_before_upload() -> None:
    """TLM_STOP_ACK меняется на чтении сразу после проверки (3) куска 0: ни одного блока куска 1, RobotAborted.

    Тест привязан к порядку одиночных чтений TLM_STOP_ACK после SC_RUN: 1-е — проверка (3), 2-е — проверка (4) перед
    загрузкой. Путь обрыва сверяется отдельно: стопа клиент не пишет (значит, не проверка (3)), текст — «во время
    загрузки», и DONE куска 0 прочитан (значит, ждали текущий кусок, а не оборвали на (1) следующего).
    """
    rig = Rig()
    state = {"armed": False, "seen": 0}

    def after_tx(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and ops[0][2][1] == OP_SC_RUN:
            state["armed"] = True

    def read_filter(address: int, count: int, out: list[int]) -> list[int]:
        if state["armed"] and address == TLM_STOP_ACK and count == 1:
            state["seen"] += 1
            if state["seen"] >= 2:  # 1-е чтение — проверка (3), 2-е — проверка перед загрузкой
                return [(out[0] + 4) & 0xFFFF]
        return out

    rig.transport.after_tx = after_tx
    rig.transport.read_filter = read_filter
    with pytest.raises(RobotAborted) as info:
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    log = rig.transport.log
    runs = run_indices(log)
    assert len(runs) == 1
    assert not [e for e in log[runs[0] :] if is_buf_tx(e)], "кусок 1 загружен после смены TLM_STOP_ACK"
    assert stop_values(log[runs[0] :]) == [], "обрыв пришёл от проверки (3), а не перед загрузкой"
    assert "загрузки" in str(info.value)
    seq0 = sc_run_of(log[runs[0]])[0]
    assert any(e[:3] == ("r", TLM_BASE, TLM_COUNT) and e[3][DONE_OFF] == seq0 for e in log[runs[0] :])


def test_stop_during_upload_no_more_blocks() -> None:
    """stop(HARD) после первого блока куска 1 (между блоками): дальше 0 записей буфера, нет SC_RUN, RobotAborted."""
    rig = Rig()
    state = {"runs": 0, "stopped_at": None}

    def after_tx(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and ops[0][2][1] == OP_SC_RUN:
            state["runs"] += 1
        elif state["runs"] == 1 and state["stopped_at"] is None and is_buf_tx(("tx", ops)):
            rig.client.stop(HARD)
            state["stopped_at"] = len(rig.transport.log)

    rig.transport.after_tx = after_tx
    with pytest.raises(RobotAborted):
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    assert state["stopped_at"] is not None
    after = rig.transport.log[state["stopped_at"] :]
    assert not [e for e in after if is_buf_tx(e)], "после стопа записан блок буфера"
    assert not [e for e in after if sc_run_of(e) is not None], "после стопа выдан SC_RUN"


# ============================================================================================
# исключения
# ============================================================================================


def test_nak_on_sc_run_does_not_stop() -> None:
    """Чужой PTP на том же ядре -> SC_RUN получает NAK E_BUSY -> RobotNak наружу, STOP_REQ клиент не пишет."""
    rig = Rig()
    other_t = HookTransport(core=rig.core, ticks_per_read=0)
    other_t.connect()
    other = RobotClientV2(
        other_t, ClientV2Config.from_dict({}), rng=_FixedRng(30000), clock=lambda: rig.now, sleep=rig.sleep
    )
    other.cmd("PTP_MOVE", MOVE_LONG)
    with pytest.raises(RobotNak) as info:
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    assert info.value.errno == E_BUSY
    assert stop_values(rig.transport.log) == []


def test_response_timeout_on_sc_run_writes_hard_stop() -> None:
    """Ответ на SC_RUN подавлен -> RobotTimeout("response") наружу, после SC_RUN записан STOP_REQ уровня HARD."""
    rig = Rig()
    state = {"mute": False}

    def before_tx(ops: list[tuple]) -> None:
        if is_cmd_tx(ops) and ops[0][2][1] == OP_SC_RUN:
            state["mute"] = True

    def read_filter(address: int, count: int, out: list[int]) -> list[int]:
        if state["mute"] and address == RES_SEQ:
            return [0, *out[1:]]
        return out

    rig.transport.before_tx = before_tx
    rig.transport.read_filter = read_filter
    with pytest.raises(RobotTimeout) as info:
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))
    assert info.value.stage == "response"
    log = rig.transport.log
    runs = run_indices(log)
    assert len(runs) == 1
    stops = stop_values(log[runs[0] :])
    assert stops and stops[0] & 3 == HARD


def test_exception_from_on_progress_stops_robot() -> None:
    """on_progress бросает посреди куска 1 -> то же исключение наружу, STOP_REQ HARD записан."""
    rig = Rig()

    class Boom(Exception):
        pass

    def on_progress(done: int, total: int) -> None:
        if done > 24:  # кусок 1 начинается с записи 24
            raise Boom("cb")

    with pytest.raises(Boom):
        bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS, on_progress=on_progress))
    log = rig.transport.log
    runs = run_indices(log)
    assert len(runs) == 2
    stops = stop_values(log[runs[1] :])
    assert stops and stops[0] & 3 == HARD


def test_second_run_chunks_raises() -> None:
    """Второй run_chunks из другого потока при идущем первом -> RuntimeError без единой записи; после — снова можно."""
    rig = Rig()
    state: dict = {}

    def on_progress(done: int, total: int) -> None:
        if "second" in state:
            return
        before = len(rig.transport.transactions)
        box: dict = {}

        def second() -> None:
            try:
                rig.client.run_chunks(circle(60), params=PARAMS)
                box["result"] = "ok"
            except BaseException as exc:  # noqa: BLE001 — исключение уходит в тест
                box["exc"] = exc

        thread = threading.Thread(target=second, daemon=True)
        thread.start()
        thread.join(10.0)
        state["second"] = box
        state["writes"] = len(rig.transport.transactions) - before

    bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS, on_progress=on_progress))
    assert isinstance(state["second"].get("exc"), RuntimeError), state["second"]
    assert state["writes"] == 0
    report = bounded(lambda: rig.client.run_chunks(circle(60), params=PARAMS))  # флаг снят
    assert report.total == 60


def test_line_pass_run_too_long_rejected_before_write() -> None:
    """JOINT + 27 LINE_PASS + LINE -> CompileError(шаг записи 27, причина 0) до первой записи в регистры."""
    rig = Rig()
    kinds = ["JOINT", *(["LINE_PASS"] * 27), "LINE"]
    records = tuple(
        Record(x=300.0, y=float(i), z=-50.0, rz=0.0, kind=kind, action="NONE", aparam=0) for i, kind in enumerate(kinds)
    )
    scenario = Scenario(records=records, step_of=tuple(i * 10 for i in range(len(kinds))))
    before = len(rig.transport.log)
    with pytest.raises(CompileError) as info:
        bounded(lambda: rig.client.run_chunks(scenario, params=PARAMS))
    assert (info.value.step, info.value.reason) == (270, 0)
    assert "27" in str(info.value)
    assert rig.transport.log[before:] == []


def test_trailing_line_pass_cut_by_end_is_last_pass() -> None:
    """Сценарий кончается рядом LINE_PASS короче половины -> CompileError(step_of[n-1], 6), без IndexError."""
    with pytest.raises(CompileError) as info:
        wire_v2.plan_chunks(["JOINT", *(["LINE_PASS"] * 5)], 27, (0, 1, 2, 3, 4, 5))
    assert (info.value.step, info.value.reason) == (5, 6)


def test_upload_masks_signed_words_to_u16() -> None:
    """upload принимает знаковые слова и пишет их u16 (дополнительный код): -1 -> 65535, -500 -> 65036."""
    rig = Rig(servo=False)
    rig.client.upload([(-1, -500, 0, 0, 2, 0)], 27)
    writes = [op for e in rig.transport.log if is_buf_tx(e) for op in e[1]]
    assert writes == [("wm", 0x1400 + 27 * 6, [65535, 65036, 0, 0, 2, 0])]


# ============================================================================================
# настоящий стек
# ============================================================================================


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_live_server_run() -> None:
    """SimRobotServer + ModbusDevice: 60 записей с отрицательными координатами (y < 0, z = -50) доходят до DONE.

    Отрицательное слово без ``& 0xFFFF`` настоящий транспорт не пропустит (фейк пропустил бы).
    """
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

        def run():
            client.probe()
            client.servo(True)
            return client.run_chunks(circle(60), params=PARAMS)

        report = bounded(run, deadline=60.0)
        assert report.total == 60
        assert [c[2] for c in report.chunks] == [0, 27, 0]
        assert circle(60).records[0].y < 0
    finally:
        device.disconnect()
        server.stop()
