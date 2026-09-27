"""Хазард-тесты автора (T2.V, DESIGN лида) — на механизм ``gui/sim_view.py``,
не на его публичный контракт (тот уже покрыт слепым ``test_sim_view.py``).

Что здесь проверяется и почему именно это:

- ``widget_to_robot`` — точная обратная функция координатного преобразования
  окна, при НЕСКОЛЬКИХ размерах виджета (resize меняет масштаб — трансформация
  не статична, кэш на ``__init__`` дал бы неверную обратную после ресайза).
- ``refresh()`` не падает на двух пограничных состояниях core (``joints() is
  None`` и активный FAULT) — оба READ-only пути окна трогают ``core.model``/
  ``core.joints()``/регистры телеметрии, у которых на этих состояниях особая
  форма данных.
- ``DemoDriver`` — единственный писатель, и ровно два его инварианта не
  проверены слепым тестом (тот бьёт по одному конкретному ``goto``/``stop``):
  seq никогда не совпадает с уже лежащим в регистре ``RES_SEQ`` (даже если
  core создан с непустым ``RES_SEQ`` — "рестарт" сценарий), и raw-значение
  ``STOP_REQ`` меняется на КАЖДЫЙ вызов ``stop()`` подряд (плоскость стопа
  реагирует только на изменение регистра — повтор того же значения не обрывал
  бы ход).

Пакет ``Services/robot_comm/gui/`` уже существует в этом ворктри (реализация
T2.V сделана до этого файла, как и предписывает бриф лида: автор пишет
хазард-тесты ПОСЛЕ green по слепому файлу).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from PySide6.QtCore import QPointF

from Services.robot_comm.core.protocol_v2 import REG, STOP_LEVEL
from Services.robot_comm.gui.sim_view import DemoDriver, SimView
from Services.robot_comm.server.sim_core_v2 import REG_SPACE_SIZE_V2, RobotSimCoreV2

pytestmark = pytest.mark.timeout(30)

FW_BUILD = 7


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


# --------------------------------------------------------------------------- #
# widget_to_robot — точная обратная преобразования отрисовки
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "size",
    [(200, 200), (400, 300), (900, 250), (201, 777)],
    ids=["square", "wide-ish", "wide", "tall"],
)
def test_widget_to_robot_is_inverse_of_paint_transform(qtbot, size):
    """`_to_widget` (использует paintEvent) и `widget_to_robot` — взаимно обратные
    при разных размерах виджета (resize меняет масштаб _paint_transform)."""
    core = fresh_core()
    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(*size)
    view.refresh()

    probes = [(0.0, 0.0), (123.4, -56.7), (-300.0, 300.0), (10.0, -10.0)]
    for x, y in probes:
        widget_pt = view._to_widget(x, y)
        x2, y2 = view.widget_to_robot(widget_pt)
        assert x2 == pytest.approx(x, abs=1e-6)
        assert y2 == pytest.approx(y, abs=1e-6)

    # и в обратную сторону: пиксель -> робот -> пиксель
    for px, py in [(0.0, 0.0), (50.0, 80.0), (float(size[0]), float(size[1]))]:
        rx, ry = view.widget_to_robot(QPointF(px, py))
        back = view._to_widget(rx, ry)
        assert back.x() == pytest.approx(px, abs=1e-6)
        assert back.y() == pytest.approx(py, abs=1e-6)


# --------------------------------------------------------------------------- #
# refresh() не падает на пограничных состояниях core
# --------------------------------------------------------------------------- #


def test_refresh_survives_unreachable_pose(qtbot):
    """joints() is None (модель не достаёт до зоны прошивки, см. docstring
    RobotSimCoreV2.joints()) — refresh() не бросает исключение несколько раз подряд."""
    from Services.robot_comm.core.params_v2 import PARAM_ID
    from Services.robot_comm.core.protocol_v2 import KIND, OP

    core = fresh_core()
    core.write(REG["CMD_SEQ"], [1])
    core.write(REG["CMD_OPCODE"], [OP["PARAM_SET"]])
    core.write(REG["CMD_ARGC"], [2])
    core.write(REG["CMD_ARGS"], [PARAM_ID["P_WS_R_MAX"], 7000])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()

    core.write(REG["CMD_SEQ"], [2])
    core.write(REG["CMD_OPCODE"], [OP["PTP_MOVE"]])
    core.write(REG["CMD_ARGC"], [6])
    core.write(REG["CMD_ARGS"], [6500, 0, 0, 0, KIND["JOINT"], 0])
    core.write(REG["CMD_FLAG"], [1])
    for _ in range(3000):
        core.tick()
        if core.regs[REG["TLM_MOVING"]] == 0:
            break
    assert core.joints() is None  # предпосылка

    view = SimView(core)
    qtbot.addWidget(view)
    for _ in range(3):
        view.refresh()
        view.grab()
    assert view.scene_chains() == []


def test_refresh_survives_fault(qtbot):
    """FAULT (inject_motion_fault) — refresh() не бросает, статус содержит текст ошибки."""
    core = fresh_core()
    core.inject_motion_fault()

    view = SimView(core)
    qtbot.addWidget(view)
    for _ in range(3):
        view.refresh()
        view.grab()
    assert "ошибка" in view.status_text().lower()


# --------------------------------------------------------------------------- #
# DemoDriver — seq никогда не повторяет то, что уже лежит в RES_SEQ
# --------------------------------------------------------------------------- #


def test_demo_driver_seq_never_repeats_stale_res_seq_after_boot():
    """core создан с УЖЕ непустым RES_SEQ (симуляция рестарта программы) —
    первая же команда DemoDriver.goto() не должна писать CMD_SEQ, равный
    этому старому RES_SEQ (иначе core счёл бы её повтором и не исполнил)."""
    stale_seq = 42
    regs = [0] * REG_SPACE_SIZE_V2
    regs[REG["RES_SEQ"]] = stale_seq
    core = RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)
    assert core.read(REG["RES_SEQ"], 1)[0] == stale_seq  # предпосылка

    driver = DemoDriver(core)
    driver.goto(200.0, 100.0)
    written_seq = core.read(REG["CMD_SEQ"], 1)[0]
    assert written_seq != stale_seq

    core.tick()
    # seq реально исполнился (не проглочен как повтор) -> RES_SEQ сменился на written_seq
    assert core.read(REG["RES_SEQ"], 1)[0] == written_seq


def test_demo_driver_seq_increments_across_calls():
    core = fresh_core()
    driver = DemoDriver(core)
    driver.home()
    seq1 = core.read(REG["CMD_SEQ"], 1)[0]
    driver.servo(True)
    seq2 = core.read(REG["CMD_SEQ"], 1)[0]
    assert seq2 != seq1


# --------------------------------------------------------------------------- #
# DemoDriver.stop() — raw-значение STOP_REQ меняется на каждый вызов
# --------------------------------------------------------------------------- #


def test_demo_driver_stop_value_changes_every_call():
    core = fresh_core()
    driver = DemoDriver(core)

    seen = set()
    for _ in range(5):
        driver.stop()
        value = core.read(REG["STOP_REQ"], 1)[0]
        assert value not in seen  # каждый вызов -> новое значение, не только новый уровень
        assert value % 4 == STOP_LEVEL["HARD"]
        seen.add(value)


def test_demo_driver_stop_value_differs_from_stale_register_content():
    """STOP_REQ уже содержит значение уровня HARD с рестарта (например, от
    предыдущего процесса) — первый же driver.stop() обязан отличаться от него,
    иначе плоскость стопа (contract §"Stop plane": реагирует на ИЗМЕНЕНИЕ
    регистра) не увидит вызов вообще."""
    regs = [0] * REG_SPACE_SIZE_V2
    regs[REG["STOP_REQ"]] = STOP_LEVEL["HARD"]  # raw=2, тот самый уровень с которым пишет stop()
    core = RobotSimCoreV2(regs=regs, fw_build=FW_BUILD)

    driver = DemoDriver(core)
    driver.stop()
    assert core.read(REG["STOP_REQ"], 1)[0] != STOP_LEVEL["HARD"]
