"""Тесты окна-монитора: строки попадают в СВОЮ колонку, шапка считает дубли.

Окно тянет журнал таймером; в тестах ``_pump`` зовём напрямую — иначе проверка
превращается в ожидание с таймаутом (а тест, который ждёт вместо того чтобы
краснеть, хуже отсутствующего).
"""

from __future__ import annotations

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
