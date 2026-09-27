"""Независимые приёмочные тесты стрелки поворота инструмента (T2.W,
plans/robot-protocol-v2/tasks.md «Окно-вид симулятора v2»), написанные ДО
реализации — по брифу лида, а не по коду.

``SimView`` (T2.V) уже существует в этом ворктри (commit 1491dbe3) — новое
поведение (стрелка по ``TLM_RZ``) добавляется В НЕГО ЖЕ, класс не меняет имя.
Ожидаемый КРАСНЫЙ = ``AssertionError`` на пиксельной проверке (стрелки ещё
нет, метод рисования не существует), а не исключение — существующий API
``SimView`` не менялся.

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать): основное
дерево репозитория (``Services/...`` вне этого ворктри), любой другой
``.claude/worktrees/*`` и файл ``z_view.py`` (его ещё нет — не мой файл).
Ничего из перечисленного в ходе работы не открывалось.

Мейлбокс-хелперы (``cmd``/``read_res``/``u16``/``mm``/``s16``/``pose``,
``run_until_idle``, ``fresh_core``) — паттерн, скопированный из
``test_sim_view.py`` (та же директория, тест T2.V), а не импорт — этот файл
вне FILES того таска.

Геометрия направления стрелки (бриф лида, DESIGN п.1): RZ=0° -> робот +X
(экран вправо), рост RZ -> против часовой на экране (робот +Y = экран
вверх). Экранное направление единичного вектора для угла ``theta`` (°):
``(cos(theta), -sin(theta))`` — минус у sin потому что экранная ось Y растёт
ВНИЗ, а требование «CCW на экране при +Y=вверх» уже учитывает это (проверено
на theta=90°: направление (0,-1) = экран вверх, что и есть робот +Y).
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG, REG_COUNT
from Services.robot_comm.gui.sim_view import SimView
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

pytestmark = pytest.mark.timeout(30)

ACK = 1
NAK = 2
FW_BUILD = 7

# цвет стрелки RZ по брифу лида: #ffb86c
_POINTER_RGB = (0xFF, 0xB8, 0x6C)
# допуск на канал (акцептанс A1: "≤ 8 per channel")
_TOL = 8

# --------------------------------------------------------------------------- #
# Мейлбокс-хелперы — паттерн из test_sim_view.py, скопирован (не импорт).
# --------------------------------------------------------------------------- #


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    """Инженерное значение (мм или °) -> сырой регистр ×0.1, округление до целого."""
    return round(eng * 10)


def s16(raw: int) -> int:
    """u16 регистра -> знаковое значение (two's complement)."""
    return raw - 65536 if raw >= 0x8000 else raw


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int, argc: int | None = None) -> dict:
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    n = len(args) if argc is None else argc
    core.write(REG["CMD_ARGC"], [n])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])  # CMD_FLAG — последним (TRAPS)
    core.tick()
    return read_res(core)


def read_res(core: RobotSimCoreV2) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def run_until_idle(core: RobotSimCoreV2, max_ticks: int = 3000) -> None:
    """Тикает, пока активная команда не завершится (TLM_MOVING == 0). Ограничено
    потолком тиков — висящий тест хуже отсутствующего (project-rules)."""
    for _ in range(max_ticks):
        core.tick()
        if core.regs[REG["TLM_MOVING"]] == 0:
            return
    pytest.fail(f"ход не завершился за {max_ticks} тиков")


def _pointer_pixel(img, tcp, theta_deg: float, radius: float = 20.0):
    rad = math.radians(theta_deg)
    x = round(tcp.x() + radius * math.cos(rad))
    y = round(tcp.y() - radius * math.sin(rad))
    return img.pixelColor(x, y)


def _close_to_pointer(pixel) -> bool:
    channels = (pixel.red(), pixel.green(), pixel.blue())
    return all(abs(c - t) <= _TOL for c, t in zip(channels, _POINTER_RGB))


def _move_to_rz(core: RobotSimCoreV2, seq: int, rz_deg: float) -> None:
    """PTP_MOVE в (200, 100, -40, rz_deg) — та же безопасная зона, что и
    test_sim_view.py::test_view_follows_pose_after_move (r=223.6 в кольце
    [100,600], угол 26.6° в [-165,165]), только RZ переменный."""
    r = cmd(core, seq, OP["PTP_MOVE"], mm(200.0), mm(100.0), mm(-40.0), mm(rz_deg), KIND["JOINT"], 0)
    assert r["status"] == ACK, r
    run_until_idle(core)


# --------------------------------------------------------------------------- #
# Тесты
# --------------------------------------------------------------------------- #


def test_rz_pointer_follows_rz_at_two_angles(qtbot):
    """На двух значениях RZ (30° и 120°, реальный PTP_MOVE через mailbox,
    тик до idle) пиксель в 20 px от TCP вдоль направления RZ — цвет стрелки
    (допуск 8 на канал); в ±15° от него — не цвет стрелки; после смены RZ
    стрелка стоит на новом угле и отсутствует на старом."""
    core = fresh_core()
    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(400, 400)

    _move_to_rz(core, 1, 30.0)
    view.refresh()
    img = view.grab().toImage()
    tcp = view._to_widget(*view._tool_xy())

    assert _close_to_pointer(_pointer_pixel(img, tcp, 30.0)), "стрелка не найдена под RZ=30°"
    assert not _close_to_pointer(_pointer_pixel(img, tcp, 45.0)), "стрелка найдена в +15° от RZ=30°"
    assert not _close_to_pointer(_pointer_pixel(img, tcp, 15.0)), "стрелка найдена в -15° от RZ=30°"

    _move_to_rz(core, 2, 120.0)
    view.refresh()
    img2 = view.grab().toImage()
    tcp2 = view._to_widget(*view._tool_xy())

    assert _close_to_pointer(_pointer_pixel(img2, tcp2, 120.0)), "стрелка не найдена под RZ=120°"
    assert not _close_to_pointer(_pointer_pixel(img2, tcp2, 30.0)), "стрелка осталась на старом угле RZ=30°"


def test_rz_pointer_drawn_when_joints_none(qtbot):
    """Сценарий test_sim_view.py::test_unreachable_pose_no_chains_and_warning
    (P_WS_R_MAX раздвинут за пределы модели, ход на (650,0,0,0) -> ACK, но
    joints() = None): стрелка RZ всё равно рисуется по TLM_RZ."""
    core = fresh_core()

    r = cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_WS_R_MAX"], 7000)  # eng 700.0 мм (scale=10)
    assert r["status"] == ACK, r

    r = cmd(core, 2, OP["PTP_MOVE"], mm(650), mm(0), mm(0), mm(0), KIND["JOINT"], 0)
    assert r["status"] == ACK, r

    run_until_idle(core)
    assert core.joints() is None  # предпосылка теста, не сам SUT

    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(300, 300)
    view.refresh()

    assert view.scene_chains() == []  # предпосылка: цепи не строятся

    img = view.grab().toImage()
    tcp = view._to_widget(*view._tool_xy())

    assert _close_to_pointer(_pointer_pixel(img, tcp, 0.0)), "стрелка не рисуется при joints() is None"
