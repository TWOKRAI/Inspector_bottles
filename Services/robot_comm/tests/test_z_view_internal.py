"""Тесты внутренних опасностей T2.W (автор — developer, роль по
``.claude/CLAUDE.md`` «Test authorship»): не приёмка по брифу (это тестер),
а то, что может сломаться в ЭТОМ механизме — вырожденные параметры зоны,
выход значения за границы, повторный запуск таймера после закрытия, утечка
буфера ленты через мутацию возвращённой копии, обратный ход часов.

``Services/robot_comm/gui/z_view.py`` и стрелка RZ в ``sim_view.py`` —
предмет теста; RED/GREEN тесты тестера (``test_sim_view_rz.py``,
``test_z_view.py``) не трогаются.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from PySide6.QtGui import QCloseEvent

from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.gui.sim_view import SimView
from Services.robot_comm.gui.z_view import TimeTape, ZScale
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

pytestmark = pytest.mark.timeout(30)

_POINTER_RGB = (0xFF, 0xB8, 0x6C)
_TOL = 8


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    return round(eng * 10)


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=7, **kw)


class FakeClock:
    """Инжектируемые часы — тик по требованию, время можно двигать и назад."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _close(pixel, target, tol: int = _TOL) -> bool:
    channels = (pixel.red(), pixel.green(), pixel.blue())
    return all(abs(c - t) <= tol for c, t in zip(channels, target))


def _degenerate_workspace(core: RobotSimCoreV2):
    """Копия реальной Workspace с вырожденными Z/RZ-диапазонами (z_min==z_max,
    rz_min==rz_max) — как при плохом PARAM_SET (min записан выше max)."""
    ws = core._workspace()
    return dataclasses.replace(ws, z_min=-50.0, z_max=-50.0, rz_min=10.0, rz_max=10.0)


def test_degenerate_span_does_not_raise_in_zscale_and_tape(qtbot):
    """P_WS_Z_MIN == P_WS_Z_MAX (и RZ) не должно ронять ни ZScale, ни TimeTape
    на refresh()/grab()/z_to_widget_y() — запасной размах в ``_span_or_fallback``
    обязан покрыть деление на ноль."""
    core = fresh_core()
    bad_ws = _degenerate_workspace(core)
    core._workspace = lambda: bad_ws  # ponytail: монки-патч приватного метода, тест внутренний

    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()
    scale.grab()  # не должно поднять исключение
    y = scale.z_to_widget_y(scale.z_value())
    assert math.isfinite(y)

    tape = TimeTape(core, clock=FakeClock())
    qtbot.addWidget(tape)
    tape.resize(300, 150)
    tape.refresh()
    tape.refresh()  # нужно >= 2 выборки, чтобы отрисовка кривой реально исполнилась
    tape.grab()  # не должно поднять исключение


def test_z_outside_limits_clamped_into_image(qtbot):
    """Значение Z далеко за пределами [z_min, z_max] не должно давать y за
    пределами картинки (контракт: «зажим на край», не рисовать за виджетом)."""
    core = fresh_core()
    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()

    z_min, z_max = scale.z_limits()
    y_above = scale.z_to_widget_y(z_max + 1000.0)
    y_below = scale.z_to_widget_y(z_min - 1000.0)

    assert 0.0 <= y_above <= scale.height()
    assert 0.0 <= y_below <= scale.height()


def test_close_event_stops_both_timers(qtbot):
    """closeEvent() должен остановить внутренний QTimer у ZScale и у TimeTape
    (переиспользование вида в T2.3 --view, тот же паттерн, что у SimView)."""
    core = fresh_core()
    scale = ZScale(core)
    tape = TimeTape(core)
    qtbot.addWidget(scale)
    qtbot.addWidget(tape)

    assert scale._timer.isActive()
    assert tape._timer.isActive()

    scale.closeEvent(QCloseEvent())
    tape.closeEvent(QCloseEvent())

    assert not scale._timer.isActive()
    assert not tape._timer.isActive()


def test_tape_samples_returns_copy(qtbot):
    """``samples()`` — копия: мутация возвращённого списка не должна менять
    то, что вернёт следующий вызов ``samples()``."""
    core = fresh_core()
    tape = TimeTape(core, clock=FakeClock())
    qtbot.addWidget(tape)
    tape.refresh()
    tape.refresh()

    first = tape.samples()
    before_len = len(first)
    first.append((999.0, 0.0, 0.0))
    first.clear()

    second = tape.samples()
    assert len(second) == before_len


def test_tape_clock_backwards_does_not_raise(qtbot):
    """Часы, идущие назад между вызовами refresh(), не должны поднимать
    исключение — окно ленты просто не подрезается в этом тике, а не падает."""
    core = fresh_core()
    clock = FakeClock(10.0)
    tape = TimeTape(core, clock=clock, window_s=5.0)
    qtbot.addWidget(tape)

    tape.refresh()
    clock.advance(2.0)
    tape.refresh()
    clock.advance(-100.0)  # часы прыгнули далеко назад
    tape.refresh()  # не должно поднять исключение
    clock.advance(1.0)
    tape.refresh()

    samples = tape.samples()
    assert len(samples) >= 1
    assert all(math.isfinite(t) for t, _z, _rz in samples)


def test_rz_pointer_at_180_points_left(qtbot):
    """RZ=180° -> экранный вектор (cos180, -sin180) = (-1, 0) = влево: пиксель
    в 20 px слева от TCP — цвет стрелки, симметричная точка справа — нет
    (проверяет знак ``cos``, не только сам факт отрисовки — A1 тестера уже
    покрывает 30°/120°, не покрывает ровно 180°, где sin=0 и правая/левая
    ветка неразличимы одним лишь «есть/нет узкого допуска»)."""
    core = fresh_core()
    core.write(REG["TLM_RZ"], [u16(mm(180.0))])

    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.refresh()

    img = view.grab().toImage()
    tcp = view._to_widget(*view._tool_xy())

    left = img.pixelColor(round(tcp.x() - 20), round(tcp.y()))
    right = img.pixelColor(round(tcp.x() + 20), round(tcp.y()))

    assert _close(left, _POINTER_RGB), "стрелка не найдена слева при RZ=180°"
    assert not _close(right, _POINTER_RGB), "стрелка найдена справа при RZ=180° (знак cos не учтён)"
