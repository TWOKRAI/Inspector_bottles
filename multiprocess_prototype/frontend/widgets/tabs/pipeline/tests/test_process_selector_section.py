# -*- coding: utf-8 -*-
"""Тесты ProcessSelectorSection — селекторы процесса/воркера/display (F.6).

Покрытие:
- configure_plugin_mode подавляет свои сигналы на время наполнения (Н-6);
- выбор процесса/воркера/display/lock/bypass эмитит «сырые» сигналы секции;
- смена процесса-приёмника перезаполняет воркер-combo под локальным suppress;
- configure_display_mode показывает только Display-форму;
- clear скрывает все формы.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.process_selector_section import (
    ProcessSelectorSection,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.selectors_data import (
    DisplayEntry,
)


def _make_section(qtbot, *, process_names=None, workers=None, displays=None):
    section = ProcessSelectorSection()
    qtbot.addWidget(section)
    section.set_providers(
        lambda: list(process_names or []),
        lambda _p: list(workers or []),
        lambda: list(displays or []),
    )
    return section


def test_configure_plugin_mode_suppresses_signals(qtbot):
    section = _make_section(qtbot, process_names=["a", "b"], workers=["grabber"])
    captured: list = []
    section.sig_worker_selected.connect(lambda w: captured.append(w))
    section.sig_target_selected.connect(lambda p: captured.append(p))

    section.configure_plugin_mode("proc", target_process="a", available_processes=["x"], assigned_worker="grabber")

    # Наполнение combo не эмитит сигналов (локальный suppress).
    assert captured == []
    assert section._move_process_form.isVisibleTo(section)


def test_target_selected_emits(qtbot):
    section = _make_section(qtbot, process_names=["a", "b"])
    section.configure_plugin_mode("proc", "a", [], "")
    got: list = []
    section.sig_target_selected.connect(got.append)
    idx = section._target_process_combo.findText("b")
    section._target_process_combo.setCurrentIndex(idx)
    assert got == ["b"]


def test_worker_selected_emits(qtbot):
    section = _make_section(qtbot, workers=["message_processor", "grabber"])
    section.configure_plugin_mode("proc", "", [], "")
    got: list = []
    section.sig_worker_selected.connect(got.append)
    idx = section._move_worker_combo.findData("grabber")
    section._move_worker_combo.setCurrentIndex(idx)
    assert got == ["grabber"]


def test_move_requested_emits_and_repopulates_worker(qtbot):
    workers_seen: list = []

    def workers_fn(p):
        workers_seen.append(p)
        return ["message_processor"]

    section = ProcessSelectorSection()
    qtbot.addWidget(section)
    section.set_providers(lambda: [], workers_fn, lambda: [])
    section.configure_plugin_mode("proc", "", ["other"], "")

    got: list = []
    section.sig_move_requested.connect(lambda f, t: got.append((f, t)))
    idx = section._move_process_combo.findData("other")
    section._move_process_combo.setCurrentIndex(idx)

    assert got == [("proc", "other")]
    # Воркер-combo перезаполнен воркерами процесса-приёмника.
    assert "other" in workers_seen


def test_lock_and_bypass_emit(qtbot):
    section = _make_section(qtbot)
    section.configure_plugin_mode("proc", "", [], "")
    locks: list = []
    bypasses: list = []
    section.sig_lock_set.connect(locks.append)
    section.sig_bypass_toggled.connect(bypasses.append)

    section._lock_btn.click()
    section._unlock_btn.click()
    assert locks == [True, False]

    section._bypass_check.setChecked(False)
    assert bypasses == [False]


def test_configure_display_mode(qtbot):
    displays = [DisplayEntry("main", "Основной"), DisplayEntry("dbg", "Отладка")]
    section = _make_section(qtbot, displays=displays)
    section.configure_display_mode("dbg")

    assert section._display_id_form.isVisibleTo(section)
    assert not section._move_process_form.isVisibleTo(section)
    assert not section._target_process_form.isVisibleTo(section)
    assert section._display_id_combo.currentData() == "dbg"


def test_display_selected_emits(qtbot):
    displays = [DisplayEntry("main", "Основной"), DisplayEntry("dbg", "Отладка")]
    section = _make_section(qtbot, displays=displays)
    section.configure_display_mode("main")
    got: list = []
    section.sig_display_selected.connect(got.append)
    for i in range(section._display_id_combo.count()):
        if section._display_id_combo.itemData(i) == "dbg":
            section._display_id_combo.setCurrentIndex(i)
            break
    assert got == ["dbg"]


def test_clear_hides_all_forms(qtbot):
    section = _make_section(qtbot, process_names=["a"])
    section.configure_plugin_mode("proc", "a", [], "")
    section.clear()
    assert not section._move_process_form.isVisibleTo(section)
    assert not section._target_process_form.isVisibleTo(section)
    assert not section._display_id_form.isVisibleTo(section)


def test_target_form_hidden_when_no_processes(qtbot):
    section = _make_section(qtbot, process_names=[])
    section.configure_plugin_mode("proc", "", [], "")
    # Пустой список процессов → combo disabled → форма IPC-таргета скрыта.
    assert not section._target_process_form.isVisibleTo(section)
    assert not section._target_process_combo.isEnabled()
