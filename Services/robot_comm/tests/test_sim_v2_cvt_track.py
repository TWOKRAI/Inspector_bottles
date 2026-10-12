"""Тесты автора (hazard) для части B T2.3: трекинг CVT_JOB, промах, обрыв связи
с ПЧ, сторож внутри сценария, сверка адресов моста с ``vfd_comm``.

Ожидаемые значения — литералы (protocol-spec §5/§9/§10, дефолты params.md:
P_BELT_FACTOR 14447 -> 0.14447 мм/имп, P_BELT_DIR 1 = +Y, кольцо P_ZONE
120..500 мм, P_PLACE (450, -300, -90, -100)), не из кода под тестом.
"""

from __future__ import annotations

from Services.robot_comm.core.protocol_v2 import ACT, CONSTANTS, ERR, KIND, OP, REG
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_core_v2 import VFD_CMD_ADDR, RobotSimCoreV2
from Services.vfd_comm.core import registers as vfd_regs

ACK = 1
TICK_S = 0.01


def mm(eng: float) -> int:
    return round(eng * 10) & 0xFFFF


def reg(core: RobotSimCoreV2, name: str) -> int:
    return core.read(REG[name])[0]


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> int:
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick(TICK_S)
    return core.read(REG["RES_STATUS"])[0]


def cvt_job(core: RobotSimCoreV2, seq: int, ecap: int, pick_x: float, pick_y: float) -> int:
    ecap &= 0xFFFFFFFF
    return cmd(core, seq, OP["CVT_JOB"], ecap & 0xFFFF, ecap >> 16, mm(pick_x), mm(pick_y), 0, 0, 0, 0, 0, 0)


def run_idle(core: RobotSimCoreV2, cap: int = 3000) -> None:
    for _ in range(cap):
        if reg(core, "TLM_ACTIVITY") == 0:
            return
        core.tick(TICK_S)
    raise AssertionError("активность не закончилась")


def stopped_belt_core(**kw) -> RobotSimCoreV2:
    # Лента без команды ПЧ стоит: энкодер = 0 всё время, трекинг задаёт только ecap.
    return RobotSimCoreV2(fw_build=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0), **kw)


def test_pick_carried_out_of_ring_trips_miss():
    jobs: list[dict] = []
    core = stopped_belt_core(on_job_done=jobs.append)
    assert core.encoder == 0

    # Контроль: ecap = текущий энкодер -> проезда нет, pick (300,-200) r=360.6 в кольце -> DONE.
    assert cvt_job(core, 5, 0, 300.0, -200.0) == ACK
    run_idle(core)
    assert reg(core, "TLM_DONE_SEQ") == 5
    assert reg(core, "TLM_MISS_COUNT") == 0
    assert len(jobs) == 1

    # ecap на 5000 имп. в прошлом: проезд 5000 × 0.14447 = 722.35 мм по +Y ->
    # следимая точка (300, 522.35), r = 602.3 > P_ZONE_MAX 500 -> промах.
    assert cvt_job(core, 6, -5000, 300.0, -200.0) == ACK
    run_idle(core)
    assert reg(core, "TLM_ERRNO_LAST") == ERR["E_ZONE_TRIP"]
    assert reg(core, "TLM_ERR_SEQ") == 6
    assert reg(core, "TLM_MISS_COUNT") == 1
    assert reg(core, "TLM_ERR_EVT") == 1
    assert reg(core, "TLM_DONE_SEQ") == 5, "промах не пишет DONE_SEQ"
    assert len(jobs) == 1, "промах не вызывает on_job_done"


def test_job_done_index_counts_accepted_jobs_not_seq():
    jobs: list[dict] = []
    core = stopped_belt_core(on_job_done=jobs.append)
    assert cvt_job(core, 41, 0, 300.0, -200.0) == ACK
    run_idle(core)
    assert cvt_job(core, 97, 0, 320.0, -180.0) == ACK
    run_idle(core)
    assert [j["index"] for j in jobs] == [1, 2]
    assert (jobs[1]["x_mm"], jobs[1]["y_mm"], jobs[1]["ecap"]) == (320.0, -180.0, 0)
    assert 0.0 < jobs[0]["t"] < jobs[1]["t"] < 30.0, "t — время sim (сумма dt), не monotonic"


def test_vfd_link_second_inject_gives_no_second_event():
    core = stopped_belt_core()
    core.inject_vfd_link_fault()
    assert reg(core, "TLM_ERRNO_LAST") == ERR["E_VFD_LINK"]
    assert reg(core, "TLM_ERR_EVT") == 1
    core.inject_vfd_link_fault()
    core.tick(TICK_S)
    assert reg(core, "TLM_ERR_EVT") == 1, "один обрыв — одно событие (§10.5)"
    core.clear_vfd_link_fault()
    core.inject_vfd_link_fault()
    assert reg(core, "TLM_ERR_EVT") == 2, "после восстановления новый обрыв — новое событие"


def test_watchdog_trips_inside_scenario_between_exact_points():
    """Сторож — каждый тик, и внутри сценария (ADR-RC-016), не только на EXACT."""
    core = stopped_belt_core()
    assert cmd(core, 1, OP["SERVO"], 1) == ACK
    assert cmd(core, 2, OP["PARAM_SET"], 96, 200) == ACK  # P_WDG_TIMEOUT_MS = 200 мс
    core.command_vfd(run=True, freq_hz=50.0)
    core.write(REG["HB_PC"], [1])
    core.tick(TICK_S)
    assert reg(core, "TLM_WDG_STATE") == 1
    assert core.belt_mm_s == 100.0
    # Длинный отрезок на SPEED_PCT 1 (15 мм/с): 1 с хода без EXACT-точки.
    for i, x in enumerate((310.0, 330.0)):
        addr = REG["SC_BUF"] + i * CONSTANTS["SC_STRIDE"]
        op = KIND["LINE"] + 256 * (ACT["SPEED_PCT"] if i == 0 else ACT["NONE"])
        core.write(addr, [mm(x), mm(-210.0), mm(-40.0), mm(-100.0), op, 1 if i == 0 else 0])
    core.write(REG["HB_PC"], [2])
    assert cmd(core, 3, OP["SC_RUN"], 2, 1, 0) == ACK
    for _ in range(30):  # 0.3 с без HB_PC > 0.2 с
        core.tick(TICK_S)
    assert reg(core, "TLM_WDG_STATE") == 2
    assert reg(core, "TLM_ERRNO_LAST") == ERR["E_WDG_TIMEOUT"]
    assert reg(core, "TLM_ERR_SEQ") == 3
    assert reg(core, "TLM_ACTIVITY") == 0
    assert reg(core, "TLM_SERVO") == 1, "сторож серво не гасит (§9.4)"
    assert core.belt_mm_s == 0.0, "сторож останавливает ленту"


def test_bridge_addresses_match_vfd_comm():
    """Сторож: адреса и масштаб моста в sim — те же, что у клиента vfd_comm."""
    assert VFD_CMD_ADDR == vfd_regs.REG_CMD_RUN == 0x1200 == CONSTANTS["VFD_BASE"]
    core = stopped_belt_core()
    core.command_vfd(run=True, freq_hz=25.0, reverse=True)
    assert core.read(vfd_regs.REG_CMD_RUN, 3) == [1, 1, 2500]
    assert core.read(vfd_regs.REG_VFD_FLAG)[0] == 1
    core.tick(TICK_S)
    assert core.read(vfd_regs.REG_VFD_FLAG)[0] == 0
    status = core.read(vfd_regs.REG_ST_BASE, 6)
    assert (status[0], status[1], status[5]) == (1, 2500, 2), "RUN, OUT_FREQ, STATUSW=REV"
    assert core.belt_mm_s == -50.0
    assert reg(core, "TLM_BELT_MMS") == (-50) & 0xFFFF
