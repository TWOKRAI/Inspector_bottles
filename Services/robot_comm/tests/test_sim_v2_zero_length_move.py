"""Регрессия sim-zero-path: ход нулевой длины (цель == текущая поза) не роняет тик.

Живой отчёт владельца: `python -m Services.robot_comm.gui.sim_view`, кнопка «Домой»
при роботе уже в HOME -> каждый тик `ZeroDivisionError` (`frac = travelled /
active["path_len"]`, `path_len == 0`). Тесты гонят `RobotSimCoreV2` напрямую
(без Qt и TCP) ограниченным циклом тиков: исключения нет, ход завершается как
обычный (TLM_DONE_SEQ == seq, ACTIVITY/MOVING == 0), поза не изменилась.
Ожидаемые значения — литералы регистров (0.1 мм), не производные от кода.
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.protocol_v2 import KIND, OP, REG
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

ACK = 1
FW_BUILD = 7
MAX_TICKS = 2000

# Поза HOME по умолчанию в регистрах (u16, 0.1 мм / 0.1 град): X=300.0, Y=-210.0, Z=-40.0, RZ=-100.0 (замер).
HOME_RAW = (3000, 63436, 65136, 64536)


def u16(value: int) -> int:
    return value & 0xFFFF


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> dict:
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    return {"status": status, "errno": errno}


def pose_raw(core: RobotSimCoreV2) -> tuple[int, int, int, int]:
    return tuple(core.regs[REG[k]] for k in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ"))


def run_until_done(core: RobotSimCoreV2, seq: int) -> int:
    """Тикает до TLM_DONE_SEQ == seq; возвращает число тиков. Ограничен MAX_TICKS."""
    for i in range(MAX_TICKS):
        if core.regs[REG["TLM_DONE_SEQ"]] == seq:
            return i
        core.tick()
    pytest.fail(f"seq={seq} не завершился за {MAX_TICKS} тиков")


def servo_on(core: RobotSimCoreV2) -> None:
    res = cmd(core, 1, OP["SERVO"], 1)
    assert res["status"] == ACK, f"предусловие: серво должно включаться: {res}"


def test_fresh_core_starts_at_home_literal():
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    assert pose_raw(core) == HOME_RAW


def test_move_to_current_pose_completes():
    """PTP_MOVE (JOINT) в точку, где робот уже стоит: ACK, ход завершается, поза прежняя."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    servo_on(core)
    before = pose_raw(core)
    res = cmd(core, 2, OP["PTP_MOVE"], *before, KIND["JOINT"], 100)
    assert res["status"] == ACK
    run_until_done(core, 2)
    assert core.regs[REG["TLM_ACTIVITY"]] == 0
    assert core.regs[REG["TLM_MOVING"]] == 0
    assert pose_raw(core) == HOME_RAW


def test_home_twice_does_not_raise():
    """«Домой» дважды подряд (второй раз робот уже дома): исключения нет, оба хода завершены."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    servo_on(core)
    for seq in (2, 3):
        res = cmd(core, seq, OP["HOME"], 100)
        assert res["status"] == ACK
        run_until_done(core, seq)
        assert core.regs[REG["TLM_ACTIVITY"]] == 0
        assert core.regs[REG["TLM_MOVING"]] == 0
        assert pose_raw(core) == HOME_RAW


def test_nonempty_joint_move_still_takes_many_ticks():
    """Контроль: ненулевой ход идёт замеренное число тиков (тайминг не тронут)."""
    core = RobotSimCoreV2(fw_build=FW_BUILD)
    servo_on(core)
    x, y, z, rz = pose_raw(core)
    res = cmd(core, 2, OP["PTP_MOVE"], x + 1000, y, z, rz, KIND["JOINT"], 100)
    assert res["status"] == ACK
    assert run_until_done(core, 2) == 6  # замер на коде ДО фикса: 100 мм JOINT при 100% -> 6 тиков
    assert pose_raw(core) == (x + 1000, y, z, rz)
