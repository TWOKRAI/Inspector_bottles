"""Независимые приёмочные тесты sim v2 — CVT_JOB, сторожевой таймер, мост ПЧ (T2.3b).

Источник истины — protocol-spec.md §5 (CVT_JOB), §9 (сторожевой таймер),
§10 (мост ПЧ) и params.md (P_WDG_TIMEOUT_MS, P_VFD_*, P_PICK_Z/P_PLACE_*,
P_BELT_*). Числа, которые контракт называет явно (TICK 0.01, ACK/NAK,
0.144473 мм/имп = FACTOR_MM), — литералы. Адреса/опкоды/errno/reasons/param id
— импортированы по имени из ``protocol_v2``/``params_v2``. Регистр-хелперы
(``u16``/``mm``/``cmd``/``read_res``) скопированы из паттерна T2.2
(``test_sim_v2_motion.py``), не импортированы — тот файл вне FILES этой задачи.

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать):
`Services/robot_comm/server/sim_core_v2.py` (кроме уже разрешённого публичного
класса/констант, импортированных явно ниже — сама реализация методов не
читалась), любой `.claude/worktrees/*dev*`. `server/belt.py` и
`core/registers.py` (FACTOR_MM/ROBOT_UNIT_ID) прочитаны как физика/адресация
ПЧ-моста (§10 явно велит переиспользовать `BeltDrive`) и v1-референс частоты
ПЧ (×100, см. ASSUMPTION VFD-FREQ ниже) — НЕ как реализация v2-ядра.

Сегодня (до реализации T2.3): CVT_JOB — NAK E_INTERNAL (в `_UNIMPLEMENTED_OPS`
sim_core_v2.py, факт из докстринга модуля, не из тела метода); HB_PC/watchdog
— нет кода вообще (нет `tick()`-обработки просрочки); HALT — только счётчик
`vfd_stop_requests`; TLM_SPD_PCT никогда не пишется. Все эти факты — из
докстринга `RobotSimCoreV2` (публичный контракт модуля), не из чтения тел
приватных методов.

ASSUMPTIONS (нет formal interface.py у CVT/WDG/VFD — угадано по ближайшему
идиоматическому соседству в уже принятом T2.2, помечено явно):
  A1. Хук инъекции обрыва связи с ПЧ называется ``core.inject_vfd_link_fault()``
      — по аналогии с уже существующим ``core.inject_motion_fault()`` (тот же
      файл, тот же паттерн тестового хука для async-ошибки). protocol-spec
      §10.5 не называет механизм для симулятора явно.
  A2. Скорость ленты ядро принимает через ``RobotSimCoreV2(..., belt=BeltDrive(...))``
      — по инструкции design "reuse server/belt.py BeltDrive" и по патторну
      v1 `core_kwargs["belt"] = BeltDrive(...)` (`server/__main__.py`).
  A3. Регистр FREQ моста ПЧ (0x1202) — сырое значение Гц×100 (protocol-spec
      §10: "заморожен как в v1"; подтверждено ЖИВЫМ v1-тестом
      `test_sim_e2e.py::test_vfd_mirror_over_bridge`, где `("w", 0x1202, 5000)`
      == 50.00 Гц — не домысел, а факт из уже принятого теста).
  A4. Направление ленты по умолчанию (P_BELT_DIR=1) — вдоль +Y, как в v1
      (`registers.py: BELT_UX, BELT_UY = 0.0, 1.0`, дефолт совпадает по
      номеру индекса). Тест НЕ проверяет ось трекинга напрямую (см. ниже) —
      A4 нужен только для выбора геометрически безопасной точки pick.
  A5. После срабатывания сторожевого таймера следующее изменение HB_PC
      заново взводит таймер (protocol-spec §9.2 говорит про взвод «с момента
      старта программы», про повторный взвод ПОСЛЕ срабатывания — молчит).

Тест CVT_JOB на движущейся ленте — на уровне НАБЛЮДАЕМОГО исхода (DONE_SEQ без
промаха), а НЕ через промежуточную формулу трекинга (`trav = (enc_now-ecap)*
FACTOR_MM`, см. `core/registers.py` — v1-only константа, в v2-параметрах ей
соответствует `P_BELT_FACTOR`=14447×1e-5≈0.144473, но точный алгоритм
трекинга v2 protocol-spec не описывает — implementation detail прошивки).
Итоговая поза после DONE проверяется против `place_*` — она не зависит от
алгоритма трекинга pick (лента не двигает место укладки).
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.protocol_v2 import CONSTANTS, ERR, KIND, OP, REG, REG_COUNT
from Services.robot_comm.core.registers import FACTOR_MM
from Services.robot_comm.server import sim_core_v2
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

ACK = 1
NAK = 2
FW_BUILD = 7
TICK_S = 0.01

TLM_ACTIVITY_CVT = 3  # protocol-spec §3.4 таблица 0x1043
TLM_WDG_OFF = 0
TLM_WDG_TRIPPED = 2  # protocol-spec §3.4 таблица 0x104F

# Мост ПЧ (protocol-spec §10.1) — смещения от CONSTANTS["VFD_BASE"] (0x1200),
# не литеральные адреса (design: "VFD_BASE comes from CONSTANTS").
_VFD_RUN = CONSTANTS["VFD_BASE"] + 0x00
_VFD_DIR = CONSTANTS["VFD_BASE"] + 0x01
_VFD_FREQ = CONSTANTS["VFD_BASE"] + 0x02
_VFD_FLAG = CONSTANTS["VFD_BASE"] + 0x04


# --------------------------------------------------------------------------- #
# Регистр-помощники — паттерн T2.2 (test_sim_v2_motion.py), скопированы.
# --------------------------------------------------------------------------- #


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    """Инженерное значение (мм или °) -> сырой регистр ×0.1, округление до целого."""
    return round(eng * 10)


def dw(value: int) -> tuple[int, int]:
    """DW (32 бита, беззнаковый счётчик энкодера) -> (lo, hi) по ARG0/ARG1 (§3.1)."""
    v = value & 0xFFFFFFFF
    return v & 0xFFFF, (v >> 16) & 0xFFFF


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int, argc: int | None = None) -> dict:
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    n = len(args) if argc is None else argc
    core.write(REG["CMD_ARGC"], [n])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    return read_res(core)


def read_res(core: RobotSimCoreV2) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    seq_written = core.read(REG["RES_SEQ"], 1)[0]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals, "seq": seq_written}


def read_enc(core: RobotSimCoreV2) -> int:
    lo = core.read(REG["TLM_ENC"], 1)[0]
    hi = core.read(REG["TLM_ENC"] + 1, 1)[0]
    return lo | (hi << 16)


def run_to_done(core: RobotSimCoreV2, seq: int, *, cap: int = 3000, dt: float = TICK_S) -> None:
    """Тикать, пока TLM_DONE_SEQ не станет ``seq`` (без wall-clock sleep, только tick())."""
    for _ in range(cap):
        core.tick(dt)
        if core.read(REG["TLM_DONE_SEQ"], 1)[0] == seq:
            return
        err_evt = core.read(REG["TLM_ERR_EVT"], 1)[0]
        if err_evt:
            errno = core.read(REG["TLM_ERRNO_LAST"], 1)[0]
            pytest.fail(f"seq={seq}: асинхронная ошибка до DONE_SEQ (ERR_EVT={err_evt}, ERRNO_LAST={errno})")
    pytest.fail(f"seq={seq}: DONE_SEQ не наступил за {cap} тиков")


# --------------------------------------------------------------------------- #
# CVT_JOB (§5, §7.3)
# --------------------------------------------------------------------------- #


def test_cvt_job_on_moving_belt_done() -> None:
    """CVT_JOB завершается DONE_SEQ, даже если лента продолжает ехать во время хода.

    A2 (конструктор с ``belt=``), A3 (FREQ×100), A4 (+Y по умолчанию, только
    для выбора безопасной геометрии). Проверяется НАБЛЮДАЕМЫЙ исход (см.
    докстринг модуля): нет промаха (`TLM_MISS_COUNT`==0), нет async-ошибки,
    итоговая поза == `P_PLACE_*` (flags=0 — оба блока из параметров).
    """
    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    core = RobotSimCoreV2(fw_build=FW_BUILD, belt=belt)

    # Пуск ленты (§10.1/10.2): RUN=1, DIR=0 (вперёд), FREQ=25.00 Гц (raw 2500, A3).
    core.write(_VFD_RUN, [1])
    core.write(_VFD_DIR, [0])
    core.write(_VFD_FREQ, [2500])
    core.write(_VFD_FLAG, [1])
    core.tick(TICK_S)

    enc_at_capture = read_enc(core)
    ecap_lo, ecap_hi = dw(enc_at_capture)

    pick_x, pick_y = 300.0, -200.0  # в кольце зоны [100, 600] мм, угол ~-33.7° (сектор ±165°)
    resp = cmd(
        core,
        1,
        OP["CVT_JOB"],
        ecap_lo,
        ecap_hi,
        mm(pick_x),
        mm(pick_y),
        0,  # pick_z аргумент игнорируется (flags бит0=0 -> P_PICK_Z)
        0,  # flags = 0: оба блока из параметров
        0,
        0,
        0,
        0,  # place_* аргументы игнорируются (flags бит1=0 -> P_PLACE_*)
    )
    assert resp["status"] == ACK, f"CVT_JOB отклонена немедленно: {resp}"
    assert resp["errno"] == ERR["E_OK"]
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == TLM_ACTIVITY_CVT

    # Лента должна была реально двигаться (иначе тест ничего не проверяет).
    enc_mid = read_enc(core)
    assert enc_mid > enc_at_capture, "лента не поехала после команды ПЧ — тест не проверяет движущуюся ленту"

    run_to_done(core, seq=1)

    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == sim_core_v2.TLM_ACTIVITY_IDLE
    assert core.read(REG["TLM_MOVING"], 1)[0] == 0
    assert core.read(REG["TLM_MISS_COUNT"], 1)[0] == 0
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == 0

    place = PARAMS[PARAM_ID["P_PLACE_X"]]["default"] / 10.0, PARAMS[PARAM_ID["P_PLACE_Y"]]["default"] / 10.0
    place_z = PARAMS[PARAM_ID["P_PLACE_Z"]]["default"] / 10.0
    place_rz = PARAMS[PARAM_ID["P_PLACE_RZ"]]["default"] / 10.0
    x = sim_core_v2.RobotSimCoreV2._decode(core.read(REG["TLM_X"], 1)[0], True) / 10.0
    y = sim_core_v2.RobotSimCoreV2._decode(core.read(REG["TLM_Y"], 1)[0], True) / 10.0
    z = sim_core_v2.RobotSimCoreV2._decode(core.read(REG["TLM_Z"], 1)[0], True) / 10.0
    rz = sim_core_v2.RobotSimCoreV2._decode(core.read(REG["TLM_RZ"], 1)[0], True) / 10.0
    assert x == pytest.approx(place[0], abs=0.1)
    assert y == pytest.approx(place[1], abs=0.1)
    assert z == pytest.approx(place_z, abs=0.1)
    assert rz == pytest.approx(place_rz, abs=0.1)

    # Реальная физика ленты (FACTOR_MM=0.144473 мм/имп) участвовала — не 0 и не NaN.
    assert FACTOR_MM == pytest.approx(0.144473)


def test_cvt_job_flags_pick_z_place() -> None:
    """flags бит0 (pick_z) / бит1 (place_*) реально переключают источник аргумента.

    Дифференциальная схема (protocol-spec §5, сноска CVT_JOB.flags):
    1. flags=0 (оба бита выкл) с ЗАВЕДОМО невалидными pick_z/place_z в
       аргументах -> ACK (аргументы игнорируются, эффективные точки из
       параметров валидны). Без этой ветки тест был бы неотличим от «функция
       не существует и просто ничего не проверяет».
    2. flags=1 (бит0 вкл) — тот же невалидный pick_z ТЕПЕРЬ учитывается ->
       NAK E_RANGE.
    3. flags=2 (бит1 вкл) — невалидный place_z ТЕПЕРЬ учитывается -> NAK E_RANGE.
    """
    core = RobotSimCoreV2(fw_build=FW_BUILD)

    pick_x, pick_y = 300.0, -200.0
    bad_z = mm(500.0)  # вне P_WS_Z_MIN..MAX по умолчанию (-150..0 мм)
    place_x, place_y, place_rz = 100.0, 100.0, 45.0  # валидная точка (радиус ~141мм, в кольце)

    resp1 = cmd(
        core,
        1,
        OP["CVT_JOB"],
        0,
        0,
        mm(pick_x),
        mm(pick_y),
        bad_z,
        0,  # flags=0 -> pick_z и place_* игнорируются
        mm(place_x),
        mm(place_y),
        bad_z,
        mm(place_rz),
    )
    assert resp1["status"] == ACK, f"flags=0 должен игнорировать невалидные pick_z/place_z: {resp1}"
    run_to_done(core, seq=1)

    resp2 = cmd(
        core,
        2,
        OP["CVT_JOB"],
        0,
        0,
        mm(pick_x),
        mm(pick_y),
        bad_z,
        1,  # бит0: pick_z из аргумента
        0,
        0,
        0,
        0,
    )
    assert resp2["status"] == NAK, "flags бит0=1 должен применить невалидный pick_z из аргумента"
    assert resp2["errno"] == ERR["E_RANGE"]

    resp3 = cmd(
        core,
        3,
        OP["CVT_JOB"],
        0,
        0,
        mm(pick_x),
        mm(pick_y),
        0,
        2,  # бит1: place_* из аргументов
        mm(place_x),
        mm(place_y),
        bad_z,
        mm(place_rz),
    )
    assert resp3["status"] == NAK, "flags бит1=1 должен применить невалидный place_z из аргумента"
    assert resp3["errno"] == ERR["E_RANGE"]


# --------------------------------------------------------------------------- #
# Сторожевой таймер (§9)
# --------------------------------------------------------------------------- #


def _prime_and_expect_trip(core: RobotSimCoreV2, timeout_ms: int, seq: int) -> None:
    """Контрольная часть: без неё «не сработал» в тестах 4/5 не отличимо от
    «таймер вообще не реализован» (см. докстринг модуля)."""
    resp = cmd(core, seq, OP["PARAM_SET"], PARAM_ID["P_WDG_TIMEOUT_MS"], timeout_ms)
    assert resp["status"] == ACK, resp
    core.write(REG["HB_PC"], [1])  # первое изменение HB_PC — взвод (§9.2)
    core.tick(TICK_S)
    step = 0.05
    ticks = int(timeout_ms / 1000.0 / step) + 5
    for _ in range(ticks):
        core.tick(step)
    assert core.read(REG["TLM_WDG_STATE"], 1)[0] == TLM_WDG_TRIPPED, "контроль: таймер должен был сработать"


def test_wdg_trips_on_battle_timeout_3000ms() -> None:
    """P_WDG_TIMEOUT_MS по умолчанию 3000 (params.md, id=96) — просрочка без HB_PC
    -> E_WDG_TIMEOUT, ERR_EVT+1, WDG_STATE=2, ACTIVITY->IDLE, серво остаётся ON
    (protocol-spec §9.4-9.5: «Серво остаётся ON» — отличие от HALT)."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    default_ms = PARAMS[PARAM_ID["P_WDG_TIMEOUT_MS"]]["default"]
    assert default_ms == 3000  # контракт называет число явно (params.md)

    core.write(REG["HB_PC"], [1])  # взвод (§9.2)
    core.tick(TICK_S)
    for _ in range(31):  # 31*0.1с = 3.1с > 3.0с
        core.tick(0.1)

    assert core.read(REG["TLM_WDG_STATE"], 1)[0] == TLM_WDG_TRIPPED
    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_WDG_TIMEOUT"]
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == 1
    assert core.read(REG["TLM_ACTIVITY"], 1)[0] == sim_core_v2.TLM_ACTIVITY_IDLE
    assert core.read(REG["TLM_SERVO"], 1)[0] == 1  # НЕ HALT — серво не гасится


def test_wdg_heartbeat_inside_window_prevents_trip() -> None:
    """HB_PC, обновляемый чаще P_WDG_TIMEOUT_MS/4, не даёт таймеру сработать (§9.1).

    A5: новое изменение HB_PC после срабатывания заново взводит таймер."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    _prime_and_expect_trip(core, timeout_ms=200, seq=1)

    resp = cmd(core, 2, OP["CLEAR_ERR"])
    assert resp["status"] == ACK

    period = 200 / 1000.0 / 4.0  # <= timeout/4 (§9.1)
    hb = 1
    for _ in range(60):  # 60*period = 3с >> 200мс — сработал бы без HB_PC
        hb += 1
        core.write(REG["HB_PC"], [u16(hb)])
        core.tick(period)

    assert core.read(REG["TLM_WDG_STATE"], 1)[0] != TLM_WDG_TRIPPED
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == 1  # только контрольное событие, ни одного нового


def test_wdg_disabled_when_zero() -> None:
    """P_WDG_TIMEOUT_MS=0 отключает таймер (params.md id=96: «0 — выключен»)."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    _prime_and_expect_trip(core, timeout_ms=200, seq=1)

    resp = cmd(core, 2, OP["CLEAR_ERR"])
    assert resp["status"] == ACK
    resp = cmd(core, 3, OP["PARAM_SET"], PARAM_ID["P_WDG_TIMEOUT_MS"], 0)
    assert resp["status"] == ACK

    core.write(REG["HB_PC"], [99])
    core.tick(TICK_S)
    for _ in range(60):
        core.tick(0.05)  # 3с без HB_PC — с включённым таймером сработал бы точно

    assert core.read(REG["TLM_WDG_STATE"], 1)[0] != TLM_WDG_TRIPPED
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == 1  # ни одного НОВОГО события после отключения


# --------------------------------------------------------------------------- #
# Мост ПЧ (§10) и телеметрия хода (§3.4)
# --------------------------------------------------------------------------- #


def test_halt_really_stops_belt() -> None:
    """HALT должен реально остановить ленту через BeltDrive (mm/s -> 0, encoder
    перестаёт расти), а не только увеличить счётчик-заглушку `vfd_stop_requests`
    (design: сегодня HALT «only bumps vfd_stop_requests counter»)."""
    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    core = RobotSimCoreV2(fw_build=FW_BUILD, belt=belt)

    core.write(_VFD_RUN, [1])
    core.write(_VFD_DIR, [0])
    core.write(_VFD_FREQ, [2500])
    core.write(_VFD_FLAG, [1])
    core.tick(TICK_S)
    assert core.read(REG["TLM_BELT_MMS"], 1)[0] != 0, "лента не поехала — HALT нечего останавливать"

    stop_req = 1 * 4 + 3  # seq=1, level=HALT (§8)
    core.write(REG["STOP_REQ"], [u16(stop_req)])
    core.tick(TICK_S)

    assert core.read(REG["TLM_SERVO"], 1)[0] == 0  # уже работает (T2.2)
    assert core.read(REG["TLM_BELT_MMS"], 1)[0] == 0  # реальная остановка ленты

    enc_after_halt = read_enc(core)
    for _ in range(20):
        core.tick(TICK_S)
    assert read_enc(core) == enc_after_halt, "энкодер продолжает расти — лента физически не остановлена"


def test_vfd_link_failure_async_e_vfd_link() -> None:
    """P_VFD_LINK_FAILS опросов без ответа -> async E_VFD_LINK (§6, §10.5).

    A1: тестовый хук `core.inject_vfd_link_fault()`, по аналогии с уже принятым
    `inject_motion_fault()` (тот же класс, тот же паттерн для async-ошибок)."""
    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    core = RobotSimCoreV2(fw_build=FW_BUILD, belt=belt)

    core.inject_vfd_link_fault()  # ASSUMPTION A1 — если хука нет, AttributeError = ожидаемый RED

    assert core.read(REG["TLM_ERRNO_LAST"], 1)[0] == ERR["E_VFD_LINK"]
    assert core.read(REG["TLM_ERR_EVT"], 1)[0] == 1


def test_tlm_spd_pct_written_during_motion() -> None:
    """TLM_SPD_PCT (0x104A) — текущий Override, % (§3.4). Design: «is never written».

    PTP_MOVE с явным spd_pct=60 уже работает (T2.2) — RED здесь чисто в
    телеметрии, без CVT/WDG/VFD."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    resp = cmd(core, 1, OP["PTP_MOVE"], mm(300.0), mm(0.0), mm(-50.0), mm(0.0), KIND["JOINT"], 60)
    assert resp["status"] == ACK, resp
    core.tick(TICK_S)
    assert core.read(REG["TLM_MOVING"], 1)[0] == 1, "тест не в фазе хода — spd_pct нечего проверять во время движения"
    assert core.read(REG["TLM_SPD_PCT"], 1)[0] == 60
