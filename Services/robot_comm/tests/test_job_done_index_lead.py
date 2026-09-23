"""Тест лида после break-injection Task 3.5: `index` события считает ПРИНЯТЫЕ задания.

Инъекция I4 (инкремент перенесён на завершение) проходила весь набор зелёным: ни один
тест не различал «принятые» и «выполненные». Различает их ровно один сценарий — задание
принято и отменено STOP, следующее выполнено: принятых 2, выполненных 1.
"""

from __future__ import annotations

from Services.modbus.sdk.datatypes import encode_int32
from Services.robot_comm.core.registers import REG_JOB_ECAP, REG_JOB_FLAG, REG_JOB_X, REG_JOB_Y, REG_STOP, STOP_IN_PLACE
from Services.robot_comm.server.sim_core import RobotSimCore


def _submit(core: RobotSimCore, ecap: int) -> None:
    core.write(REG_JOB_X, [100])
    core.write(REG_JOB_Y, [200])
    core.write(REG_JOB_ECAP, encode_int32(ecap, word_order="little"))
    core.write(REG_JOB_FLAG, [1])


def test_index_counts_accepted_jobs_including_stopped_one():
    events: list[dict] = []
    core = RobotSimCore(on_job_done=events.append)

    _submit(core, ecap=10)
    core.tick()  # принято (1-е)
    core.write(REG_STOP, [STOP_IN_PLACE])
    core.tick()  # отменено STOP — события нет

    _submit(core, ecap=20)
    for _ in range(3):
        core.tick()  # принято (2-е) и выполнено

    assert [e["index"] for e in events] == [2]
    assert events[0]["ecap"] == 20
