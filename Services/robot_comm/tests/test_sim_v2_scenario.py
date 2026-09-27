"""Независимые приёмочные тесты симулятора v2 — SC_RUN/сценарий (T2.3a),
написанные ДО реализации, из protocol-spec.md §3.4 (TLM_SC_*), §4 (хендшейк
mailbox), §5 (опкод SC_RUN), §6 (errno/reason), §7 (сценарий, целиком) и
params.md (P_WS_*, P_SPD_*, P_HAND, P_HOME_*). Источник истины — спека и
`protocol_v2`/`params_v2` (генерированные из delta_v2.yaml), не сам симулятор.

Сегодня `SC_RUN` отвечает NAK `E_INTERNAL` (см. `_UNIMPLEMENTED_OPS` в
`sim_core_v2.py`) — все тесты этого файла обязаны падать по этой причине.

Прочитано ДО написания тестов (в рамках FILES задачи): protocol-spec.md §3-4,
7-8; params.md (через сам `params_v2.py` — числа дефолтов сверены оттуда);
delta_v2.yaml не открывался (числа взяты из уже сгенерированных
`protocol_v2.py`/`params_v2.py`, YAML — не источник для теста, 1:1 с ним по
контракту); `programs/geometry.py` целиком (уже принятый оракул зоны, T2.2);
`server/sim_core_v2.py` — ЗАЯВЛЕННЫЙ скоуп «конструктор, tick, regs, write»
неcознательно превышен: `sed`/`grep` также показали модульный docstring
(перечисление, что реализовано в T2.1/T2.2 текстом, без деталей алгоритма),
имена констант активности (`TLM_ACTIVITY_IDLE/PTP/JOG/FAULT`, БЕЗ CVT/SCENARIO
— их там нет, они не реализованы), `_UNIMPLEMENTED_OPS`, `_FAULT_WHITELIST` и
сигнатуры `__init__`/`read`/`write`/`tick`. По `SC_RUN` в файле нет ничего,
кроме NAK-заглушки — контаминации по предмету теста (сценарий) не было, но
превышение скоупа раскрываю честно (см. отчёт). `test_sim_v2_motion.py`
прочитан целиком как образец стиля хелперов — по инструкции задачи это
разрешённый read-only образец, не импортируется, паттерны скопированы.

ЗАПРЕЩЕНО (не открывалось): `.claude/worktrees/rpv2-t2.3*` и любой другой
ворктри разработчика; исходники CVT/watchdog/VFD (вне скоупа этого файла —
другой тестер).

Изоляция (project-rules): ворктри на коммите c2a5c28f, до реализации T2.3.

=========================== ASSUMPTIONS (spec неоднозначен) ==========================
A1. `TLM_SC_DONE_N` («итог исполнения сценария», §3.4) читается как число
    успешно исполненных записей при полном успехе — то есть равно `count` на
    штатном завершении. Спека не даёт формулы явно; выбрано по аналогии с
    `TLM_SC_INDEX` («пройдено точек») и с `DONE_SEQ`-семантикой соседних
    опкодов (единственная другая интерпретация — что-то вроде счётчика вызовов
    SC_RUN — противоречит слову «итог» в ед. числе на одно исполнение).
A2. `rval0` (индекс) у `E_SC_RECORD` (§6, §7.2 п.2) — индекс ВНУТРИ
    исполняемого среза (0-based относительно `offset`), не абсолютный адрес в
    буфере. Спека говорит просто «индекс». Чтобы не завязывать RED/GREEN на
    этой развилке, единственный тест с `E_SC_RECORD` использует `offset=0`,
    где обе трактовки совпадают числом — неоднозначность не эксплуатируется.
A3. `ACT["DELAY_MS"]` — миллисекунды буквально (§7.1 явно указывает единицу
    «мс»), это не предположение. Предположение — ТОЛЬКО что действие
    стартует на тике прихода в точку (симметрично `DONE_SEQ`, который пишется
    на тике прихода, T2.2). Тест не пином точное число тиков задержки (по
    аналогии с окном ±1 тик у JOG-лиза в test_sim_v2_motion.py), а лишь то,
    что команда НЕ завершается на самом тике прихода при delay>0 — так что
    ошибка в трактовке границы тика не даёт ложный RED.
A4. §7.2 п.4: «TLM_SC_INDEX, опрос mailbox, ... обслуживаются только на
    EXACT-точках». Прочитано как: пока сценарий движется (включая транзит
    к LINE_PASS-точке), новая команда в CMD_FLAG НЕ обрабатывается и
    TLM_SC_INDEX не меняется; оба обновляются в момент прихода в ближайшую
    EXACT-точку (KIND != LINE_PASS), даже если по дороге была пройдена
    LINE_PASS-точка. Тест шлёт PING (`busy: allow`) в момент прихода на
    первую EXACT-точку и проверяет, что RES_SEQ не переключается на её seq,
    пока сценарий идёт через LINE_PASS-точку, и переключается только на
    следующей EXACT-точке — так тест верен при любой ГРАНУЛЯРНОСТИ гейта
    («раз в любую точку, но с задержкой» vs «раз в EXACT, не считая
    LINE_PASS»), поскольку в обоих чтениях LINE_PASS-точка сама по себе не
    обслуживает mailbox.
A5. Промежуточные точки сценария (включая LINE_PASS) симулятор проходит
    ТОЧНО (поза на каком-то тике равна raw-координатам записи) — по аналогии
    с уже принятой моделью клампинга последнего шага PTP/HOME/JOG (T2.2:
    `test_ptp_line_monotonic_over_ge3_ticks_and_arrives_exactly` и соседние).
    Если реализация вместо этого сглаживает непрерывно и никогда точно не
    касается LINE_PASS-точки — часть теста прогресса нужно будет
    пересобрать (см. отчёт, «что оставлено открытым»).
========================================================================================
"""

from __future__ import annotations

import math

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import ACT, CONSTANTS, ERR, KIND, OP, REASON, REG, REG_COUNT
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7
TICK_S = 0.01

# TLM_ACTIVITY=4 SCENARIO — литерал из таблицы протокола (protocol-spec §3.4);
# в sim_core_v2.py константы для него ещё нет (не реализовано), поэтому число,
# не импорт, как ACK/NAK в этом же файле и в T2.1/T2.2.
ACTIVITY_SCENARIO = 4


# --------------------------------------------------------------------------- #
# Регистр-хелперы — паттерн test_sim_v2_motion.py, скопирован, не импортирован
# (файл вне FILES этой задачи).
# --------------------------------------------------------------------------- #


def mm(eng: float) -> int:
    return round(eng * 10)


class RecordingRegs(list):
    """list, фиксирующий каждый __setitem__ — для теста порядка записи (И5)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.write_log: list[int] = []

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            self.write_log.extend(range(*key.indices(len(self))))
        else:
            idx = key + len(self) if key < 0 else key
            self.write_log.append(idx)
        super().__setitem__(key, value)


def last_pos(log: list[int], addr: int) -> int:
    positions = [i for i, a in enumerate(log) if a == addr]
    assert positions, f"адрес {addr:#06x} ни разу не записан в этом логе"
    return positions[-1]


def first_pos(log: list[int], addr: int) -> int:
    assert addr in log, f"адрес {addr:#06x} ни разу не записан в этом логе"
    return log.index(addr)


def cmd(core, seq: int, opcode: int, *args: int, argc: int | None = None) -> dict:
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    n = len(args) if argc is None else argc
    core.write(REG["CMD_ARGC"], [n])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    return read_res(core)


def queue_cmd(core, seq: int, opcode: int, *args: int) -> None:
    """Как cmd(), но БЕЗ tick()/чтения ответа — чтобы контролировать, на каком
    именно тике команда попадёт в mailbox (нужно для теста гейта И4/§7.2.4)."""
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])


def read_res(core) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    seq_written = core.read(REG["RES_SEQ"], 1)[0]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals, "seq": seq_written}


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def recording_core() -> RobotSimCoreV2:
    regs = RecordingRegs([0] * REG_SPACE_SIZE_V2)
    return RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)


def run_until_activity_zero(core, max_ticks: int = 3000) -> int:
    for i in range(max_ticks):
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            return i
        core.tick(TICK_S)
    pytest.fail(f"команда всё ещё активна после {max_ticks} тиков — цикл не должен зависать")


def servo_on(core, seq: int = 1) -> None:
    res = cmd(core, seq, OP["SERVO"], 1)
    assert res["status"] == ACK, "предусловие: серво должно включаться"


def home_target() -> tuple[int, int, int, int]:
    x = PARAMS[PARAM_ID["P_HOME_X"]]["default"]
    y = PARAMS[PARAM_ID["P_HOME_Y"]]["default"]
    z = PARAMS[PARAM_ID["P_HOME_Z"]]["default"]
    rz = PARAMS[PARAM_ID["P_HOME_RZ"]]["default"]
    return x, y, z, rz


def expected_extra_ticks(distance_mm: float, v_mm_s: float, dt: float = TICK_S) -> int:
    """Скопировано из test_sim_v2_motion.py (T2.2, принятая формула тайминга
    PTP: step = min(v*dt, MAX_STEP_MM); тиков = ceil(distance/step); ACK —
    первый из них)."""
    cap = 100.0 / 3.0
    step = min(v_mm_s * dt, cap)
    return math.ceil(distance_mm / step) - 1


def write_scenario(core, offset: int, records: list[tuple]) -> None:
    """records: список (x_mm, y_mm, z_mm, rz_mm, kind, action, aparam),
    stride 6, protocol-spec §7.1: OP = KIND + 256*ACTION."""
    for i, (x, y, z, rz, kind, action, aparam) in enumerate(records):
        op = kind + 256 * action
        addr = REG["SC_BUF"] + (offset + i) * CONSTANTS["SC_STRIDE"]
        core.write(addr, [mm(x), mm(y), mm(z), mm(rz), op, aparam])


# Дефолтная рабочая зона (см. params_v2.PARAMS, сверено с test_sim_v2_motion.py
# DEFAULT_WS): r in [100,600] мм, z in [-150,0] мм, rz in [-360,360]°,
# сектор angle in [-165,165]°, box выключен. HOME=(300,-210,-40,-100).
# Точки этого файла — варьируют только X при y=-210 (как и в T2.2-тестах),
# держась в r<=600: x_max при y=-210 -> sqrt(600²-210²)=562.05мм.


# =========================================================================== #
# 1. Счастливый путь: DO/DELAY/SPEED в одном сценарии + восстановление
#    P_SPD_DEFAULT после выхода (§7.2 п.5)
# =========================================================================== #


def test_scenario_moves_with_do_delay_speed():
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()

    records = [
        (400.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["DO_ON"], 5),
        (450.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["SPEED_PCT"], 50),
        (500.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["DELAY_MS"], 20),
    ]
    write_scenario(core, 0, records)

    res = cmd(core, 2, OP["SC_RUN"], 3, 111, 0)
    assert res["status"] == ACK, f"SC_RUN должен приниматься: {res}"
    move_seq = res["seq"]
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == ACTIVITY_SCENARIO

    target_raw = mm(500.0)
    arrived_tick = None
    for i in range(3000):
        x = core.read(REG["TLM_X"], 1)[0]
        if x == target_raw and arrived_tick is None:
            arrived_tick = i
            # DELAY_MS=20 > 0 -> обязана пройти минимум ещё одна миллисекунда
            # симулированного времени -> на самом тике прихода команда ещё
            # не должна завершиться (A3).
            assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, (
                "DELAY_MS>0 не должен давать мгновенное завершение на тике прихода"
            )
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            break
        core.tick(TICK_S)
    else:
        pytest.fail("сценарий не завершился за 3000 тиков")

    assert arrived_tick is not None, "робот обязан был дойти до последней точки (500,-210,-40,-100)"
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq
    do_mask = core.read(REG["TLM_DO_MASK"], 1)[0]
    assert do_mask == (1 << (5 - 1)), f"DO_ON канал 5 должен выставить бит 4 маски, получено {do_mask:#06x}"
    assert core.read(REG["TLM_SC_INDEX"], 1)[0] == 3
    assert core.read(REG["TLM_SC_TOTAL"], 1)[0] == 3
    assert core.read(REG["TLM_SC_DONE_N"], 1)[0] == 3  # A1

    # §7.2 п.5: на любом выходе восстанавливается P_SPD_DEFAULT — проверяем
    # тем же тайминг-оракулом, что и T2.2 (100мм, spd_pct=0 -> default 80%).
    res2 = cmd(core, 3, OP["PTP_MOVE"], mm(400.0), mm(-210.0), mm(-40.0), mm(-100.0), KIND["LINE"], 0)
    assert res2["status"] == ACK
    spd_l = PARAMS[PARAM_ID["P_SPD_L"]]["default"]
    pct = PARAMS[PARAM_ID["P_SPD_DEFAULT"]]["default"]
    v = spd_l * pct / 100.0
    expected = expected_extra_ticks(100.0, v)
    extra = run_until_activity_zero(core, max_ticks=200)
    assert extra == expected, (
        f"после сценария со SPEED_PCT=50 в теле скорость должна вернуться к P_SPD_DEFAULT "
        f"(ожидалось {expected} доп.тиков, получено {extra})"
    )


# =========================================================================== #
# 2. Прогресс/mailbox обслуживаются только на EXACT-точках (§7.2 п.4, A4/A5)
# =========================================================================== #


def test_progress_only_on_exact_points():
    core = fresh_core()
    servo_on(core, 1)

    p1 = (400.0, -210.0, -40.0, -100.0)  # EXACT (LINE), индекс 1
    p2 = (450.0, -210.0, -40.0, -100.0)  # LINE_PASS — НЕ EXACT
    p3 = (500.0, -210.0, -40.0, -100.0)  # EXACT (LINE), последняя, индекс 3

    records = [
        (*p1, KIND["LINE"], ACT["NONE"], 0),
        (*p2, KIND["LINE_PASS"], ACT["NONE"], 0),
        (*p3, KIND["LINE"], ACT["NONE"], 0),
    ]
    write_scenario(core, 0, records)

    res = cmd(core, 2, OP["SC_RUN"], 3, 7, 0)
    assert res["status"] == ACK
    move_seq = res["seq"]

    x_p1, x_p2, x_p3 = mm(p1[0]), mm(p2[0]), mm(p3[0])
    reached_p1 = False
    pinged = False
    reached_p3 = False

    for _ in range(3000):
        x = core.read(REG["TLM_X"], 1)[0]

        if x == x_p1 and not reached_p1:
            reached_p1 = True
            assert core.read(REG["TLM_SC_INDEX"], 1)[0] == 1, "индекс должен обновиться ровно на первой EXACT-точке"
            # PING (busy: allow) во время сценария — гейт §7.2 п.4/A4.
            queue_cmd(core, 99, OP["PING"])
            pinged = True

        if reached_p1 and not reached_p3:
            assert core.read(REG["TLM_SC_INDEX"], 1)[0] == 1, (
                "индекс не должен меняться, пока не пройдена следующая EXACT-точка"
            )
            assert core.read(REG["RES_SEQ"], 1)[0] == move_seq, (
                "PING, отправленный во время транзита к LINE_PASS-точке, не должен "
                "обрабатываться раньше следующей EXACT-точки"
            )

        if x == x_p3:
            reached_p3 = True
            break

        core.tick(TICK_S)
    else:
        pytest.fail("сценарий не дошёл до последней точки за 3000 тиков")

    assert reached_p1, "точка p1 не была достигнута ни на одном тике (A5)"
    assert pinged
    assert reached_p3, "точка p3 не была достигнута ни на одном тике (A5)"
    # На EXACT-точке PING наконец обслуживается (в этом же тике или chiar
    # раньше следующего — не позже прихода на p3).
    core.tick(TICK_S)
    assert core.read(REG["RES_SEQ"], 1)[0] == 99, "PING должен обработаться на/у следующей EXACT-точки"
    assert core.read(REG["TLM_SC_INDEX"], 1)[0] == 3, "индекс должен догнать все пройденные записи на EXACT-точке"


# =========================================================================== #
# 3. Валидация ВСЕГО среза до движения: первая плохая запись -> NAK,
#    rval0=индекс, rval1=причина, поза не изменилась (§7.2 п.1-2)
# =========================================================================== #


@pytest.mark.parametrize(
    "kind,action,aparam,expected_reason,label",
    [
        (5, ACT["NONE"], 0, REASON["R_KIND"], "kind вне {LINE,LINE_PASS,JOINT}"),
        (KIND["LINE"], 99, 0, REASON["R_ACTION"], "action вне таблицы §7.1"),
        (KIND["LINE"], ACT["DO_ON"], 17, REASON["R_APARAM"], "DO_ON канал вне 1..16"),
    ],
)
def test_bad_record_nak_index_reason_no_motion(kind, action, aparam, expected_reason, label):
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()

    good = (420.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0)
    bad = (500.0, -210.0, -40.0, -100.0, kind, action, aparam)
    write_scenario(core, 0, [good, bad])

    res = cmd(core, 2, OP["SC_RUN"], 2, 5, 0)
    assert res["status"] == NAK, label
    assert res["errno"] == ERR["E_SC_RECORD"], label
    assert res["rvalc"] == 2, label
    assert res["rvals"][0] == 1, f"{label}: индекс плохой записи (offset=0, A2) должен быть 1"
    assert res["rvals"][1] == expected_reason, label
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, f"{label}: ничего не должно было поехать"
    assert core.read(REG["TLM_X"], 1)[0] == hx, f"{label}: поза должна остаться домашней даже с валидной первой записью"
    assert core.read(REG["TLM_Y"], 1)[0] & 0xFFFF == hy & 0xFFFF, label


# =========================================================================== #
# 4. count/offset вне допустимого -> E_SC_COUNT (§6, §7.2 п.1)
# =========================================================================== #


@pytest.mark.parametrize(
    "count,offset,label",
    [
        (0, 0, "count=0 вне 1..SC_CAP"),
        (CONSTANTS["SC_CAP"] + 1, 0, "count>SC_CAP"),
        (10, CONSTANTS["SC_CAP"] - 5, "offset+count>SC_CAP"),
    ],
)
def test_sc_count_zero_over_capacity_offset_overflow(count, offset, label):
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()

    res = cmd(core, 2, OP["SC_RUN"], count, 1, offset)
    assert res["status"] == NAK, label
    assert res["errno"] == ERR["E_SC_COUNT"], label
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, label
    assert core.read(REG["TLM_X"], 1)[0] == hx, label


# =========================================================================== #
# 5. Пинг-понг: два SC_RUN с разными offset читают СВОИ записи буфера (§7.4)
# =========================================================================== #


def test_ping_pong_two_offsets():
    core = fresh_core()
    servo_on(core, 1)

    buf_a = [(420.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0)]
    write_scenario(core, 0, buf_a)
    res_a = cmd(core, 2, OP["SC_RUN"], 1, 10, 0)
    assert res_a["status"] == ACK
    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == mm(420.0)
    assert core.read(REG["TLM_SC_ID"], 1)[0] == 10
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == res_a["seq"]

    buf_b = [(500.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0)]
    write_scenario(core, 30, buf_b)
    res_b = cmd(core, 3, OP["SC_RUN"], 1, 20, 30)
    assert res_b["status"] == ACK, "второй SC_RUN с offset=30 должен приниматься независимо от буфера offset=0"
    run_until_activity_zero(core)
    assert core.read(REG["TLM_X"], 1)[0] == mm(500.0), (
        "робот должен был исполнить запись ИЗ offset=30 (500мм), а не повторно offset=0 (420мм)"
    )
    assert core.read(REG["TLM_SC_ID"], 1)[0] == 20
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == res_b["seq"]


# =========================================================================== #
# 6. Стоп посреди сценария -> E_ABORTED, никогда DONE_SEQ, DO не тронут
#    (§7.2 п.6, §8 п.6)
# =========================================================================== #


def test_stop_mid_scenario_aborted_do_untouched():
    core = fresh_core()
    servo_on(core, 1)
    res_do = cmd(core, 2, OP["DO_SET"], 3, 1)  # канал3 ON заранее -> маска бит2=4
    assert res_do["status"] == ACK
    do_before = core.read(REG["TLM_DO_MASK"], 1)[0]
    assert do_before == 4

    hx, hy, hz, hrz = home_target()
    # 250мм при потолке шага MAX_STEP_MM=100/3мм/тик даёт >= ceil(250/(100/3))=8
    # тиков МИНИМУМ при любой трактовке скорости сценария — запас на прерывание.
    far = (550.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["DO_OFF"], 3)
    write_scenario(core, 0, [far])

    res = cmd(core, 3, OP["SC_RUN"], 1, 9, 0)
    assert res["status"] == ACK
    move_seq = res["seq"]
    done_before = core.read(REG["TLM_DONE_SEQ"], 1)[0]

    core.tick(TICK_S)
    core.tick(TICK_S)
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] != 0, "сценарий должен ещё лететь после 2 тиков (запас по MAX_STEP_MM)"
    assert core.read(REG["TLM_X"], 1)[0] != mm(550.0), "не должен был долететь за 2 тика"

    core.write(REG["STOP_REQ"], [2])  # HARD (level=2), seq·4+level, seq любой ненулевой цикл — здесь просто level
    core.tick(TICK_S)

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == 0, "HARD обязан прервать сценарий немедленно"
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_ABORTED"]
    assert core.read(REG["TLM_ERR_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == done_before, "стоп НИКОГДА не должен давать DONE_SEQ (§8 п.6)"
    frozen_x = core.read(REG["TLM_X"], 1)[0]
    assert mm(300.0) < frozen_x < mm(550.0), "поза должна замереть строго между стартом и целью"
    assert core.read(REG["TLM_DO_MASK"], 1)[0] == do_before, (
        "DO_OFF записи не должен был исполниться (точка не достигнута) — маска не тронута (§7.2 п.6)"
    )


# =========================================================================== #
# 7. DONE_SEQ/TLM_SC_DONE_N после последней записи + порядок И5 (TRAPS)
# =========================================================================== #


def test_done_seq_and_sc_done_n_after_last_record():
    core = recording_core()
    servo_on(core, 1)

    records = [
        (420.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0),
        (480.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0),
    ]
    write_scenario(core, 0, records)

    res = cmd(core, 2, OP["SC_RUN"], 2, 3, 0)
    assert res["status"] == ACK
    move_seq = res["seq"]

    log = None
    for _ in range(3000):
        core.regs.write_log.clear()
        core.tick(TICK_S)
        if core.read(REG["TLM_ACTIVITY"], 1)[0] == 0:
            log = list(core.regs.write_log)
            break
    else:
        pytest.fail("сценарий не завершился за 3000 тиков")

    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_SC_DONE_N"], 1)[0] == 2  # A1
    assert core.read(REG["TLM_SC_INDEX"], 1)[0] == 2
    assert core.read(REG["TLM_SC_TOTAL"], 1)[0] == 2

    # И5 (TRAPS): DONE_SEQ пишется отдельной записью ПОСЛЕ остального блока
    # события (protocol-spec §3.4 «Порядок записи событий»).
    done_pos = first_pos(log, REG["TLM_DONE_SEQ"])
    assert last_pos(log, REG["TLM_ACTIVITY"]) < done_pos
    assert last_pos(log, REG["TLM_MOVING"]) < done_pos
    assert last_pos(log, REG["TLM_X"]) < done_pos
    assert last_pos(log, REG["TLM_SC_INDEX"]) < done_pos


# =========================================================================== #
# 8. E2E на дефолтных параметрах, реалистичные дистанции (без PARAM_SET)
# =========================================================================== #


def test_scenario_on_battle_defaults():
    core = fresh_core()
    servo_on(core, 1)
    hx, hy, hz, hrz = home_target()

    records = [
        (420.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["NONE"], 0),  # 120мм от дома
        (500.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["DO_ON"], 2),  # +80мм, DO2 ON
        (560.0, -210.0, -40.0, -100.0, KIND["LINE"], ACT["DELAY_MS"], 10),  # +60мм, пауза
        (float(hx) / 10.0, float(hy) / 10.0, float(hz) / 10.0, float(hrz) / 10.0, KIND["JOINT"], ACT["NONE"], 0),
    ]
    write_scenario(core, 0, records)

    res = cmd(core, 2, OP["SC_RUN"], 4, 42, 0)
    assert res["status"] == ACK, f"дефолтный e2e-сценарий должен приниматься: {res}"
    move_seq = res["seq"]

    run_until_activity_zero(core, max_ticks=3000)

    assert core.read(REG["TLM_X"], 1)[0] == hx, "финальная JOINT-точка возвращает робота домой"
    assert core.read(REG["TLM_DONE_SEQ"], 1)[0] == move_seq
    assert core.read(REG["TLM_SC_INDEX"], 1)[0] == 4
    assert core.read(REG["TLM_SC_TOTAL"], 1)[0] == 4
    assert core.read(REG["TLM_SC_DONE_N"], 1)[0] == 4  # A1
    do_mask = core.read(REG["TLM_DO_MASK"], 1)[0]
    assert do_mask == (1 << (2 - 1)), f"DO_ON канал 2 -> бит1 маски, получено {do_mask:#06x}"
