"""Журнал sim: разбор строк ``on_event`` ядра v2 (T2.3, часть B).

Формат строк — докстринг ``sim_core_v2``; один тест подаёт строки вручную
(литералы), второй — живые строки ядра (реальные объекты, не подделка).
"""

from __future__ import annotations

from Services.robot_comm.core.protocol_v2 import OP, REG
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.server.sim_journal import SimJournal


def test_v2_lines_tagged_and_counted():
    j = SimJournal(clock=lambda: 1.0)
    for line in (
        "[v2] CMD seq=3 op=CVT_JOB",
        "[v2] CMD seq=4 op=PING",
        "[v2] CVT grip seq=3 x=300.0 y=-200.0",
        "[v2] DONE seq=3 op=CVT_JOB",
        "[v2] CMD seq=5 op=PTP_MOVE",
        "[v2] DONE seq=5 op=PTP_MOVE",
        "[v2] ERR seq=0 errno=16 E_VFD_LINK",
    ):
        j.on_event(line)
    tags = [(e.side, e.tag) for e in j.drain()]
    assert tags == [
        ("out", "job"),
        ("out", ""),
        ("out", ""),
        ("out", "done"),
        ("out", ""),
        ("out", "done"),
        ("out", ""),
    ]
    c = j.counters()
    assert (c["jobs"], c["done"]) == (1, 1), "счётчики — только CVT_JOB v2"


def test_v1_line_still_counts_done():
    j = SimJournal(clock=lambda: 1.0)
    j.on_event("[CVT]  выполнено -> робот свободен")
    assert j.counters()["done"] == 1
    assert j.drain()[0].tag == "done"


def test_live_core_events_feed_journal():
    j = SimJournal(clock=lambda: 1.0)
    core = RobotSimCoreV2(belt=BeltDrive(), on_event=j.on_event)
    for seq, opcode, args in ((1, OP["SERVO"], [1]), (2, OP["CVT_JOB"], [0, 0, 3000, 63536, 0, 0, 0, 0, 0, 0])):
        core.write(REG["CMD_SEQ"], [seq])
        core.write(REG["CMD_OPCODE"], [opcode])
        core.write(REG["CMD_ARGC"], [len(args)])
        core.write(REG["CMD_ARGS"], args)
        core.write(REG["CMD_FLAG"], [1])
        core.tick(0.01)
    for _ in range(3000):
        if core.read(REG["TLM_ACTIVITY"])[0] == 0:
            break
        core.tick(0.01)
    texts = [e.text for e in j.drain()]
    assert texts[0] == "[v2] CMD seq=1 op=SERVO"
    assert "[v2] CMD seq=2 op=CVT_JOB" in texts
    assert texts[-1] == "[v2] DONE seq=2 op=CVT_JOB"
    assert (j.counters()["jobs"], j.counters()["done"]) == (1, 1)
