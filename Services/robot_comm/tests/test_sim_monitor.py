"""Тесты окна-монитора: строки попадают в СВОЮ колонку, шапка считает дубли.

Окно тянет журнал таймером; в тестах ``_pump`` зовём напрямую — иначе проверка
превращается в ожидание с таймаутом (а тест, который ждёт вместо того чтобы
краснеть, хуже отсутствующего).
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import pytest

pytest.importorskip("PySide6", reason="GUI-монитор требует PySide6")

from Services.robot_comm.core.registers import FACTOR_MM, REG_JOB_ECAP, REG_JOB_FLAG, REG_JOB_X, REG_JOB_Y
from Services.robot_comm.server.sim_journal import SimJournal
from Services.robot_comm.server.sim_monitor import SimMonitorWindow

FC_W, FC_W_MULTI = 6, 16


def _send_job(journal: SimJournal, x_mm: float, y_mm: float, ecap: int) -> None:
    journal.on_write(FC_W, REG_JOB_X, [int(x_mm * 10) & 0xFFFF])
    journal.on_write(FC_W, REG_JOB_Y, [int(y_mm * 10) & 0xFFFF])
    journal.on_write(FC_W_MULTI, REG_JOB_ECAP, [ecap & 0xFFFF, (ecap >> 16) & 0xFFFF])
    journal.on_write(FC_W, REG_JOB_FLAG, [1])


@pytest.fixture
def window(qtbot):
    journal = SimJournal()
    win = SimMonitorWindow(journal, poll_ms=10_000)  # таймер не нужен — качаем вручную
    qtbot.addWidget(win)
    return win, journal


def test_sides_go_to_their_own_columns(window) -> None:
    """Записи ПК — слева, события робота — справа; перепутать колонки нельзя."""
    win, journal = window
    journal.on_write(FC_W, REG_JOB_X, [1234])
    journal.on_event("[CVT]  выполнено -> робот свободен")
    win._pump()

    left, right = win._pane_in.toPlainText(), win._pane_out.toPlainText()
    assert "job_x = 123.4" in left
    assert "выполнено" not in left
    assert "выполнено" in right
    assert "job_x" not in right


def test_header_counts_duplicates(window) -> None:
    """Шапка показывает число дублей — ради него окно и открывают."""
    win, journal = window
    _send_job(journal, 300.0, -210.0, 100_000)
    _send_job(journal, 300.0, -210.0 + 1000 * FACTOR_MM, 101_000)
    win._pump()

    text = win._lbl_counters.text()
    assert "заданий: <b>2</b>" in text
    assert "ДУБЛЕЙ: <b>1</b>" in text
    assert "ДУБЛЬ" in win._pane_in.toPlainText()


def test_clear_resets_panes_and_counters(window) -> None:
    """«Очистить» гасит и колонки, и счётчики, и память о заданиях."""
    win, journal = window
    _send_job(journal, 300.0, -210.0, 100_000)
    win._pump()
    win._on_clear()

    assert win._pane_in.toPlainText() == ""
    assert "заданий: <b>0</b>" in win._lbl_counters.text()


def test_line_carries_time_and_delta_within_its_column(window) -> None:
    """У строки есть отметка времени и Δt, считанный ВНУТРИ своей колонки."""
    win, journal = window
    journal.on_write(FC_W, REG_JOB_X, [10])
    journal.on_write(FC_W, REG_JOB_Y, [20])
    win._pump()

    lines = [ln for ln in win._pane_in.toPlainText().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert lines[0].count(":") >= 2  # HH:MM:SS.mmm
    assert lines[1].lstrip().split()[1].startswith("+")  # у второй строки есть дельта


def _shown_minus_now_s(win: SimMonitorWindow, journal: SimJournal) -> float:
    """Показанное окном время строки журнала минус настенное «сейчас» (сек., с учётом полуночи)."""
    journal.on_event("[CVT]  выполнено -> робот свободен")
    (entry,) = journal.drain()
    match = re.search(r"(\d\d):(\d\d):(\d\d)\.(\d{3})", win._render(entry))
    assert match, "в строке нет отметки времени"
    hh, mm, ss, ms = (int(g) for g in match.groups())
    shown = hh * 3600 + mm * 60 + ss + ms / 1000
    now = datetime.now()
    diff = shown - (now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6)
    return (diff + 43200) % 86400 - 43200


def test_monitor_time_is_anchored_on_the_journal_clock(qtbot) -> None:
    """Часы журнала выданы с произвольным сдвигом от monotonic: якорь окна на своих часах
    показал бы время со сдвигом (здесь +5000 с), на часах журнала — текущее."""
    journal = SimJournal(clock=lambda: time.monotonic() + 5000.0)
    win = SimMonitorWindow(journal, poll_ms=10_000)
    qtbot.addWidget(win)

    assert abs(_shown_minus_now_s(win, journal)) < 0.05


def test_monitor_time_matches_wall_clock_with_default_journal_clock(qtbot) -> None:
    """Штатные часы журнала (perf_counter): расхождение с настенным временем — единицы мс, не десятки
    (на Windows perf_counter и monotonic расходятся на 28 мс и растут с аптаймом)."""
    journal = SimJournal()
    win = SimMonitorWindow(journal, poll_ms=10_000)
    qtbot.addWidget(win)

    assert abs(_shown_minus_now_s(win, journal)) < 0.015
