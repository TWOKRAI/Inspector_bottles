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

import math

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from PySide6.QtGui import QCloseEvent

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG
from Services.robot_comm.gui.sim_view import SimView, build_window
from Services.robot_comm.gui.z_view import TimeTape, ZScale
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2


_POINTER_RGB = (0xFF, 0xB8, 0x6C)
_TOL = 8


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    return round(eng * 10)


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=7, **kw)


def mm_arg(eng: float) -> int:
    """Инженерное значение (мм/°) -> сырой аргумент команды ×10, округление до целого."""
    return round(eng * 10)


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int) -> dict:
    """Мейлбокс-хелпер, паттерн скопирован из test_z_view.py (та же директория)."""
    core.write(REG["CMD_SEQ"], [seq & 0xFFFF])
    core.write(REG["CMD_OPCODE"], [opcode])
    core.write(REG["CMD_ARGC"], [len(args)])
    if args:
        core.write(REG["CMD_ARGS"], [a & 0xFFFF for a in args])
    core.write(REG["CMD_FLAG"], [1])  # CMD_FLAG — последним (TRAPS)
    core.tick()
    return {
        "status": core.read(REG["RES_STATUS"], 1)[0],
        "errno": core.read(REG["RES_ERRNO"], 1)[0],
    }


def run_until_idle(core: RobotSimCoreV2, max_ticks: int = 3000) -> None:
    """Тикает, пока активная команда не завершится (TLM_MOVING == 0). Ограничено
    потолком тиков — висящий тест хуже отсутствующего (project-rules)."""
    for _ in range(max_ticks):
        core.tick()
        if core.regs[REG["TLM_MOVING"]] == 0:
            return
    pytest.fail(f"ход не завершился за {max_ticks} тиков")


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


# Раньше здесь стоял test_degenerate_span_does_not_raise_in_zscale_and_tape,
# создававший вырожденный домен монки-патчем ``core._workspace()``. После F5
# (ревью T2.W) ZScale/TimeTape вообще не вызывают ``core._workspace()`` —
# границы зоны идут через зеркало PMIR (``_param_eng``), так что тот
# монки-патч больше не достигает кода под тестом (пинил путь, которого нет).
# Удалён, а не обновлён. Гарантию «не падать на вырожденном домене» держит
# сторож ведущего test_t2w_lead_guards.py::test_degenerate_domain_via_param_set_does_not_raise
# (реальные PARAM_SET, все значения равны). Два теста ниже ловят слияние строк,
# а не деление на ноль — ревью T2.W итерация 2 показало, что они зелёные при
# выключенном запасе `_widen_domain`.


def test_window_close_stops_all_three_timers(qtbot):
    """F4, ревью T2.W: Qt доставляет ``closeEvent`` только окну верхнего
    уровня — без ``hideEvent`` каждый из трёх виджетов, встроенных
    ``build_window()`` в общее окно, продолжал бы тикать после
    ``window.close()`` (живой снимок ведущего: лента набрала 1 -> 17 выборок
    за 0.5 с после закрытия). Реальные объекты через ``build_window()`` +
    ``show()``/``close()``, ``closeEvent`` не вызывается напрямую."""
    core = RobotSimCoreV2()
    window = build_window(core)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.close()

    view = window.findChildren(SimView)[0]
    zscale = window.findChildren(ZScale)[0]
    tape = window.findChildren(TimeTape)[0]

    assert not view._timer.isActive(), "таймер SimView тикает после закрытия окна"
    assert not zscale._timer.isActive(), "таймер ZScale тикает после закрытия окна"
    assert not tape._timer.isActive(), "таймер TimeTape тикает после закрытия окна"


def test_z_outside_zone_gets_distinct_row_from_bound(qtbot):
    """F1, ревью T2.W: Z вне зоны (после ACKed хода на Z=-130, PARAM_SET сузил
    z_min до -120, выше текущего Z) получает строку, отличную от границы
    z_min — без домена по факту (min/max над границами + текущим Z + метками,
    не голые границы) значение вне зоны зажалось бы на край и слилось со
    строкой границы в один пиксель."""
    core = fresh_core()
    r = cmd(core, 1, OP["PTP_MOVE"], mm_arg(300.0), mm_arg(-210.0), mm_arg(-130.0), mm_arg(-100.0), KIND["JOINT"], 0)
    assert r["status"] == 1, r  # ACK
    run_until_idle(core)

    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()
    assert scale.z_value() == pytest.approx(-130.0, abs=0.05)  # предпосылка

    r = cmd(core, 2, OP["PARAM_SET"], PARAM_ID["P_WS_Z_MIN"], -1200 & 0xFFFF)  # eng -120.0, выше Z=-130
    assert r["status"] == 1, r  # ACK

    scale.refresh()
    scale.grab()  # не должно поднять исключение

    z_row = round(scale.z_to_widget_y(scale.z_value()))
    bound_row = round(scale.z_to_widget_y(scale.z_limits()[0]))
    assert z_row != bound_row, "Z вне зоны слился со строкой границы z_min"


def test_inverted_zone_bounds_get_distinct_rows_and_no_raise(qtbot):
    """F1, ревью T2.W: P_WS_Z_MIN выставлен ВЫШЕ P_WS_Z_MAX (инверсия,
    ошибочный PARAM_SET, ничем не проверяется на границе параметра) —
    refresh()/grab() не должны поднимать исключение, а строки двух границ
    остаются разными (домен строится через min/max по значениям, не по
    декларированному порядку min < max)."""
    core = fresh_core()
    scale = ZScale(core)
    qtbot.addWidget(scale)
    scale.resize(120, 300)
    scale.refresh()

    r = cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_WS_Z_MIN"], 100)  # eng +10.0, выше z_max=0.0
    assert r["status"] == 1, r  # ACK

    scale.refresh()
    scale.grab()  # не должно поднять исключение

    z_min, z_max = scale.z_limits()
    assert z_min > z_max  # предпосылка: зона инвертирована
    row_min = round(scale.z_to_widget_y(z_min))
    row_max = round(scale.z_to_widget_y(z_max))
    assert row_min != row_max, "границы инвертированной зоны слились в одну строку"

    y = scale.z_to_widget_y(scale.z_value())
    assert math.isfinite(y)


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
