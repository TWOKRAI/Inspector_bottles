"""Независимые приёмочные тесты для НОВОГО модуля ``z_view.py`` (T2.W,
plans/robot-protocol-v2/tasks.md «Окно-вид симулятора v2»), написанные ДО
реализации — по брифу лида, а не по коду.

Модуль ``Services/robot_comm/gui/z_view.py`` ещё не существует в этом
ворктри (commit 1491dbe3) -> ожидаемый КРАСНЫЙ для ВСЕГО файла =
``ImportError`` на ``Services.robot_comm.gui.z_view``.

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать): основное
дерево репозитория (``Services/...`` вне этого ворктри), любой другой
``.claude/worktrees/*`` и сам файл ``z_view.py`` (его ещё нет — не мой файл,
только имя класса/сигнатуры из брифа лида). Ничего из перечисленного в ходе
работы не открывалось.

Мейлбокс-хелперы — паттерн, скопированный из ``test_sim_view.py`` (та же
директория, тест T2.V), а не импорт — этот файл вне FILES того таска.

Литералы (бриф лида, DESIGN п. «Verified facts», сверено grep'ом по
``Services/robot_comm/protocols/delta_v2.yaml`` и ``params_v2.py`` — оба
файла протокольных констант, не реализация под тестом):
``P_WS_Z_MIN`` default -1500 raw (scale 10) = -150.0 мм, ``P_WS_Z_MAX`` 0 raw
= 0.0 мм, ``P_PICK_Z`` -1000 raw = -100.0 мм, ``P_PLACE_Z`` -900 raw =
-90.0 мм, ``P_HOME_Z`` -400 raw = -40.0 мм. Свежий ``RobotSimCoreV2()``
стартует в позе (300.0, -210.0, -40.0, -100.0) — Z дома совпадает с меткой
"home" (-40.0), поэтому пиксельный тест A3 (нужен ТЕКУЩИЙ Z, отличный от
меток/границ) двигает робота на Z=-70.0 отдельной командой.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG, REG_COUNT
from Services.robot_comm.gui.sim_view import DemoDriver, SimView
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

# модуль ещё не существует -> ImportError (ожидаемый КРАСНЫЙ для всего файла)
from Services.robot_comm.gui.z_view import TimeTape, ZScale

pytestmark = pytest.mark.timeout(30)

ACK = 1
NAK = 2
FW_BUILD = 7

_CURRENT_RGB = (0x5A, 0xF7, 0x8E)
_BOUND_RGB = (0xFF, 0x5C, 0x57)
_MARK_RGB = (0x8B, 0xE9, 0xFD)
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


class FakeClock:
    """Инжектируемые часы для TimeTape — тик по требованию, без time.monotonic."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _close(pixel, target, tol: int = _TOL) -> bool:
    channels = (pixel.red(), pixel.green(), pixel.blue())
    return all(abs(c - t) <= tol for c, t in zip(channels, target))


def _scan_for_color(img, target, tol: int = _TOL) -> bool:
    """Есть ли хоть один пиксель цвета ``target`` (допуск ``tol``) во всём
    изображении — «кривая где-то нарисована», а не в конкретной точке
    (бриф не называет геометрию кривой Z(t))."""
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            if _close(img.pixelColor(x, y), target, tol):
                return True
    return False


# --------------------------------------------------------------------------- #
# A3/A4 — ZScale
# --------------------------------------------------------------------------- #


def test_zscale_reads_current_z_limits_and_marks(qtbot):
    """z_value() == TLM_Z, z_limits() == (P_WS_Z_MIN, P_WS_Z_MAX) боевых
    дефолтов, marks() == {"pick": P_PICK_Z, "place": P_PLACE_Z,
    "home": P_HOME_Z} — литералы, не выведены из кода под тестом."""
    core = fresh_core()
    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.refresh()

    assert scale.z_value() == pytest.approx(-40.0, abs=0.05)  # боевой дефолт TLM_Z (дом)
    assert scale.z_limits() == pytest.approx((-150.0, 0.0), abs=0.05)
    assert scale.marks() == pytest.approx({"pick": -100.0, "place": -90.0, "home": -40.0}, abs=0.05)
    assert set(scale.marks().keys()) == {"pick", "place", "home"}  # ровно три ключа, без "travel"


def test_zscale_pixels_current_and_bound(qtbot):
    """Пиксель x=4 в строке текущего Z — цвет current (#5af78e); в строке
    z_min — цвет bound (#ff5c57). Z сдвинут на -70.0 мм (не метка, не
    граница) отдельным ходом, чтобы не совпасть ни с одной меткой."""
    core = fresh_core()
    r = cmd(core, 1, OP["PTP_MOVE"], mm(300.0), mm(-210.0), mm(-70.0), mm(-100.0), KIND["JOINT"], 0)
    assert r["status"] == ACK, r
    run_until_idle(core)

    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()

    assert scale.z_value() == pytest.approx(-70.0, abs=0.05)  # предпосылка: Z сдвинут
    z_min, _z_max = scale.z_limits()
    cur_row = round(scale.z_to_widget_y(scale.z_value()))
    bound_row = round(scale.z_to_widget_y(z_min))

    img = scale.grab().toImage()
    assert _close(img.pixelColor(4, cur_row), _CURRENT_RGB), "нет цвета текущего Z в строке current"
    assert _close(img.pixelColor(4, bound_row), _BOUND_RGB), "нет цвета границы в строке z_min"


def test_zscale_redraws_after_param_set_z_min(qtbot):
    """PARAM_SET P_WS_Z_MIN -> после refresh() z_limits()[0] новый и домен
    развёртки (F1, ревью T2.W: min/max по границам + текущему Z + отметкам,
    не голые границы) сузился -> та же точка -40.0 (текущий Z в момент
    старта, боевой дефолт) рисуется в ДРУГОЙ строке, цветом текущего Z; строка
    новой границы z_min — по-прежнему цветом границы."""
    core = fresh_core()
    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()

    old_min, _old_max = scale.z_limits()
    old_row = round(scale.z_to_widget_y(-40.0))

    r = cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_WS_Z_MIN"], -1200)  # eng -120.0 мм
    assert r["status"] == ACK, r

    scale.refresh()
    new_min, _new_max = scale.z_limits()
    new_row = round(scale.z_to_widget_y(-40.0))

    assert new_min == pytest.approx(-120.0, abs=0.05)
    assert new_min != pytest.approx(old_min, abs=0.05)
    assert new_row != old_row

    img = scale.grab().toImage()
    assert _close(img.pixelColor(4, new_row), _CURRENT_RGB), "текущий Z не перерисован на новой строке"

    bound_row = round(scale.z_to_widget_y(new_min))
    assert _close(img.pixelColor(4, bound_row), _BOUND_RGB), "граница не перерисована на новой строке"


def test_zscale_mark_moves_after_param_set_pick_z(qtbot):
    """PARAM_SET P_PICK_Z -> после refresh() marks()["pick"] новый, в новой
    строке — цвет метки."""
    core = fresh_core()
    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()

    old_pick = scale.marks()["pick"]

    r = cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_PICK_Z"], -800)  # eng -80.0 мм
    assert r["status"] == ACK, r

    scale.refresh()
    new_pick = scale.marks()["pick"]
    new_row = round(scale.z_to_widget_y(new_pick))

    assert new_pick == pytest.approx(-80.0, abs=0.05)
    assert new_pick != pytest.approx(old_pick, abs=0.05)

    img = scale.grab().toImage()
    assert _close(img.pixelColor(4, new_row), _MARK_RGB), "метка pick не перерисована на новой строке"


# --------------------------------------------------------------------------- #
# A5/A6 — TimeTape
# --------------------------------------------------------------------------- #


def test_tape_records_z_minimum_of_down_up_move(qtbot):
    """Ход Z вниз-вверх (-40 -> -120 -> -40, та же XY/RZ), фиксированный dt,
    tape.refresh() после каждого тика, поддельные часы, тикающие вместе с
    симуляцией: минимум выборок = нижняя цель ±0.1, первая и последняя
    выборки — на верхнем Z ±0.1, цвет кривой Z присутствует в grab()."""
    core = fresh_core()
    clock = FakeClock()
    tape = TimeTape(core, clock=clock, window_s=10.0)
    qtbot.addWidget(tape)
    tape.resize(300, 150)

    tape.refresh()  # начальная выборка на боевом дефолте (Z=-40.0)

    dt = 0.02

    def _run_move(seq: int, z_target: float) -> None:
        r = cmd(core, seq, OP["PTP_MOVE"], mm(300.0), mm(-210.0), mm(z_target), mm(-100.0), KIND["JOINT"], 0)
        assert r["status"] == ACK, r
        ticks = 0
        while core.regs[REG["TLM_MOVING"]] == 1 and ticks < 3000:
            core.tick(dt)
            clock.advance(dt)
            tape.refresh()
            ticks += 1
        assert ticks < 3000, f"ход к Z={z_target} не завершился за 3000 тиков"

    _run_move(1, -120.0)
    _run_move(2, -40.0)

    samples = tape.samples()
    assert len(samples) >= 3
    zs = [z for _t, z, _rz in samples]

    assert min(zs) == pytest.approx(-120.0, abs=0.1)
    assert samples[0][1] == pytest.approx(-40.0, abs=0.1)
    assert samples[-1][1] == pytest.approx(-40.0, abs=0.1)

    img = tape.grab().toImage()
    assert _scan_for_color(img, _CURRENT_RGB), "цвет кривой Z(t) нигде не найден в grab()"


def test_tape_window_drops_old_samples(qtbot):
    """После > 10 с поддельного времени выборок самая старая выборка — не
    старше 10 с относительно текущего значения часов; выборки по возрастанию t."""
    core = fresh_core()
    clock = FakeClock()
    tape = TimeTape(core, clock=clock, window_s=10.0)
    qtbot.addWidget(tape)

    dt = 0.5
    n_steps = 40  # 20 с выборок — вдвое больше окна 10 с
    for _ in range(n_steps):
        core.tick(dt)
        clock.advance(dt)
        tape.refresh()

    samples = tape.samples()
    ts = [t for t, _z, _rz in samples]

    assert ts == sorted(ts)
    assert len(ts) >= 2
    assert clock() - ts[0] <= 10.0 + dt  # допуск в один шаг на границу окна


# --------------------------------------------------------------------------- #
# A7 — ни один из трёх виджетов не пишет регистры
# --------------------------------------------------------------------------- #


class _RecordingRegs(list):
    """Список регистров, фиксирующий каждую запись (``__setitem__``) — снимок
    ДО/ПОСЛЕ (``list(core.regs) == list(core.regs)``) не различает «не
    записали» от «записали и откатили в исходное значение»; список-шпион
    ловит сам ФАКТ записи, а не только итоговое состояние."""

    def __init__(self, initial):
        super().__init__(initial)
        self.writes: list[object] = []

    def __setitem__(self, index, value):
        self.writes.append(index)
        super().__setitem__(index, value)


def test_widgets_never_write_registers(qtbot):
    """SimView (со стрелкой RZ), ZScale и TimeTape — read-only: конструктор +
    refresh() + grab() каждого из трёх виджетов не порождают НИ ОДНОЙ записи
    в регистры core — ни через ``core.write()``, ни напрямую в ``core.regs``
    (снимок сделан ДО создания виджетов, список-шпион ставится ДО них же).
    Ядро не тикает между виджетами (contract: только refresh()/grab() под
    наблюдением, тик core — не часть read-only контракта виджетов)."""
    core = fresh_core()
    driver = DemoDriver(core)
    driver.goto(200.0, 50.0)
    for _ in range(5):
        core.tick()

    core.regs = _RecordingRegs(core.regs)
    write_calls: list[tuple[int, list[int]]] = []
    original_write = core.write

    def _recording_write(address: int, values: list[int]) -> None:
        write_calls.append((address, list(values)))
        original_write(address, values)

    core.write = _recording_write

    view = SimView(core)
    zscale = ZScale(core)
    tape = TimeTape(core, clock=lambda: 0.0)
    qtbot.addWidget(view)
    qtbot.addWidget(zscale)
    qtbot.addWidget(tape)
    view.resize(300, 300)
    zscale.resize(120, 300)
    tape.resize(300, 150)

    for widget in (view, zscale, tape):
        widget.refresh()
        widget.grab()  # форсирует paintEvent синхронно, без show()/event loop

    assert write_calls == [], f"core.write() вызван виджетом: {write_calls}"
    assert core.regs.writes == [], f"прямая запись в core.regs по индексам: {core.regs.writes}"


# --------------------------------------------------------------------------- #
# A8 — смоук python -m
# --------------------------------------------------------------------------- #


def test_main_smoke_subprocess():
    """``python -m Services.robot_comm.gui.sim_view --quit-after 0.5`` строит
    окно с тремя виджетами (SimView+стрелка, ZScale, TimeTape) и выходит с
    кодом 0, без traceback в stderr."""
    worktree_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = worktree_root

    result = subprocess.run(
        [sys.executable, "-m", "Services.robot_comm.gui.sim_view", "--quit-after", "0.5"],
        cwd=worktree_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
