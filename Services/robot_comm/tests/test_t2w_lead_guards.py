"""Сторожевые тесты ведущего T2.W — по одному на свойство, которое матрица
инъекций пробила при зелёных тестах тестера и автора
(docs/reviews/2026-09-27_robot-v2-task-T2.W-injections.md, I3/I6/I11/I13).
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG
from Services.robot_comm.gui.sim_view import SimView, build_window
from Services.robot_comm.gui.z_view import TimeTape, ZScale
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

pytestmark = pytest.mark.timeout(30)

ACK = 1
_POINTER_RGB = (0xFF, 0xB8, 0x6C)
_CURRENT_RGB = (0x5A, 0xF7, 0x8E)
_TOL = 8


def _close(pixel, target) -> bool:
    return all(abs(c - t) <= _TOL for c, t in zip((pixel.red(), pixel.green(), pixel.blue()), target))


def _move(core: RobotSimCoreV2, seq: int, x: float, y: float, z: float, rz: float) -> None:
    args = [round(v * 10) & 0xFFFF for v in (x, y, z, rz)] + [KIND["JOINT"], 0]
    core.write(REG["CMD_SEQ"], [seq])
    core.write(REG["CMD_OPCODE"], [OP["PTP_MOVE"]])
    core.write(REG["CMD_ARGC"], [len(args)])
    core.write(REG["CMD_ARGS"], args)
    core.write(REG["CMD_FLAG"], [1])  # последним
    core.tick()
    assert core.read(REG["RES_STATUS"], 1)[0] == ACK
    for _ in range(3000):
        core.tick()
        if core.regs[REG["TLM_MOVING"]] == 0:
            return
    pytest.fail("ход не завершился за 3000 тиков")


def test_rz_pointer_drawn_over_last_link(qtbot):
    """I3: стрелка поверх звеньев. RZ направлен вдоль последнего звена (от TCP к
    локтю) — пиксель в 20 px по этому направлению обязан быть цветом стрелки,
    а не цветом звена."""
    core = RobotSimCoreV2()
    _move(core, 1, 200.0, 100.0, -40.0, 0.0)
    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.refresh()
    *_, elbow, tcp = view.scene_chains()[0]
    along_link = math.degrees(math.atan2(elbow[1] - tcp[1], elbow[0] - tcp[0]))
    _move(core, 2, 200.0, 100.0, -40.0, round(along_link, 1))
    view.refresh()
    p = view._to_widget(*view._tool_xy())
    rad = math.radians(along_link)
    pixel = view.grab().toImage().pixelColor(round(p.x() + 20 * math.cos(rad)), round(p.y() - 20 * math.sin(rad)))
    assert _close(pixel, _POINTER_RGB), (pixel.red(), pixel.green(), pixel.blue())


def test_zscale_current_drawn_over_equal_mark(qtbot):
    """I6: текущий Z поверх отметки. На старте Z = -40.0 = отметка «home»: в её
    строке — цвет текущего Z, а не отметки."""
    core = RobotSimCoreV2()
    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()
    assert scale.z_value() == pytest.approx(-40.0, abs=0.05)
    assert scale.marks()["home"] == pytest.approx(-40.0, abs=0.05)  # предпосылка
    row = round(scale.z_to_widget_y(-40.0))
    assert _close(scale.grab().toImage().pixelColor(4, row), _CURRENT_RGB)


def test_tape_draws_rz_curve(qtbot):
    """I13: кривая RZ(t) нарисована — её цвет есть в ленте (указатель RZ живёт в
    другом виджете, спутать не с чем)."""
    core = RobotSimCoreV2()
    now = [0.0]
    tape = TimeTape(core, clock=lambda: now[0])
    qtbot.addWidget(tape)
    tape.resize(300, 150)
    for _ in range(5):
        now[0] += 0.5
        tape.refresh()
    img = tape.grab().toImage()
    assert any(_close(img.pixelColor(x, y), _POINTER_RGB) for y in range(img.height()) for x in range(img.width()))


def test_build_window_composes_three_views(qtbot):
    """I11: окно отладки содержит ровно по одному SimView, ZScale и TimeTape
    (смоук `python -m` проверяет только код выхода, не состав)."""
    window = build_window(RobotSimCoreV2())
    qtbot.addWidget(window)
    assert [len(window.findChildren(cls)) for cls in (SimView, ZScale, TimeTape)] == [1, 1, 1]


class _RegistersOnly:
    """Источник данных без ядра: только ``read`` и ``regs`` — как у будущего
    клиента настоящего робота. Любое обращение к ``_workspace``/``_values``
    даст AttributeError."""

    def __init__(self, core: RobotSimCoreV2) -> None:
        self.read = core.read
        self.regs = core.regs


def test_z_views_read_registers_only(qtbot):
    """J4 (ревью 1, F5): ZScale и TimeTape работают поверх одних регистров
    (TLM_* + PMIR), без приватного состояния ядра."""
    source = _RegistersOnly(RobotSimCoreV2())
    scale = ZScale(source)
    tape = TimeTape(source, clock=lambda: 0.0)
    for widget in (scale, tape):
        qtbot.addWidget(widget)
        widget.refresh()
        widget.grab()
    assert scale.z_limits() == pytest.approx((-150.0, 0.0), abs=0.05)
    assert scale.marks() == pytest.approx({"pick": -100.0, "place": -90.0, "home": -40.0}, abs=0.05)


def test_tape_rz_outside_zone_not_flattened(qtbot):
    """J5 (ревью 1, F1): RZ вне зоны не прижимается к краю ленты. Зона RZ
    сужена до [-360, 0], выборки RZ = 60 и 120 (регистр пишет тест, не вид):
    кривая RZ обязана занимать заметную высоту, а не лечь в одну строку."""
    core = RobotSimCoreV2()
    core.write(REG["CMD_SEQ"], [1])
    core.write(REG["CMD_OPCODE"], [OP["PARAM_SET"]])
    core.write(REG["CMD_ARGC"], [2])
    core.write(REG["CMD_ARGS"], [PARAM_ID["P_WS_RZ_MAX"], 0])
    core.write(REG["CMD_FLAG"], [1])
    core.tick()
    assert core.read(REG["RES_STATUS"], 1)[0] == ACK
    now = [0.0]
    tape = TimeTape(core, clock=lambda: now[0])
    qtbot.addWidget(tape)
    tape.resize(300, 150)
    for rz in (60.0, 120.0):
        core.regs[REG["TLM_RZ"]] = round(rz * 10) & 0xFFFF
        now[0] += 1.0
        tape.refresh()
    img = tape.grab().toImage()
    rows = {y for y in range(img.height()) for x in range(img.width()) if _close(img.pixelColor(x, y), _POINTER_RGB)}
    assert rows and max(rows) - min(rows) > 10, sorted(rows)
