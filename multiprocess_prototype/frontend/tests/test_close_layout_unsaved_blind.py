# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.12 (C-30): закрытие главного окна при ``layout_unsaved``.

Раскладка узлов не сохранена (автосейв упёрся в устаревшую базу), правок графа нет (``dirty`` False):
закрытие окна обязано предупредить, иначе позиции узлов пропадают молча.

* E: диалог показан ровно один раз; текст содержит «Позиции узлов не сохранены»; кнопки «Сохранить» нет
  (``allow_save`` False даже при заданном save-callback: Save сверяется с той же устаревшей базой);
  «discard» -> закрытие разрешено;
* F: «cancel» -> ``event.ignore()``;
* H: регрессия — при ``dirty`` диалог прежний.

Диалог подменяется на уровне ``confirm_unsaved_changes`` (импортируется внутри метода окна), не QMessageBox.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtGui import QCloseEvent

from multiprocess_prototype.domain.topology_session import TopologySession
from multiprocess_prototype.frontend.windows.main_window import MainWindow

_DIALOG_TARGET = "multiprocess_prototype.frontend.widgets.dialogs.confirm_unsaved_changes"
_LAYOUT_TEXT = "Позиции узлов не сохранены"
_DIRTY_TEXT = "В редакторе топологии есть несохранённые правки"


def _spy_dialog(monkeypatch: pytest.MonkeyPatch, choice: str) -> list[dict[str, Any]]:
    """Подменить confirm_unsaved_changes: вернуть ``choice``, записать (allow_save, text) каждого вызова."""
    shown: list[dict[str, Any]] = []

    def _fake(
        parent: Any, *, allow_save: bool = True, text: str = "В редакторе топологии есть несохранённые правки."
    ) -> str:
        shown.append({"allow_save": allow_save, "text": text})
        return choice

    monkeypatch.setattr(_DIALOG_TARGET, _fake)
    return shown


def _window(qtbot: Any, session: TopologySession, save_fn: Any) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_topology_session(session, save_fn)
    return window


def _close(window: MainWindow) -> QCloseEvent:
    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    return event


def _save_ok() -> bool:
    return True


# ---------------------------------------------------------------------------
# E. layout_unsaved, dirty False, «не сохранять» -> диалог один раз, закрытие разрешено
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("save_fn", [None, _save_ok], ids=["no_save_fn", "with_save_fn"])
def test_close_with_layout_unsaved_discard_shows_dialog_and_accepts(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch, save_fn: Any
) -> None:
    session = TopologySession()
    session.mark_layout_unsaved()
    assert session.dirty is False
    window = _window(qtbot, session, save_fn)
    shown = _spy_dialog(monkeypatch, "discard")
    try:
        event = _close(window)

        assert len(shown) == 1
        assert _LAYOUT_TEXT in shown[0]["text"]
        assert shown[0]["allow_save"] is False
        assert event.isAccepted() is True
    finally:
        session.reset()  # иначе teardown qtbot закроет окно и встанет модальный диалог


def test_confirm_discard_with_layout_unsaved_discard_allows_proceed(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тот же диалог через confirm_discard_topology_changes (рестарт UI и пр.): discard -> True, диалог один раз."""
    session = TopologySession()
    session.mark_layout_unsaved()
    window = _window(qtbot, session, None)
    shown = _spy_dialog(monkeypatch, "discard")
    try:
        proceed = window.confirm_discard_topology_changes(reason="перед рестартом?")

        assert proceed is True
        assert len(shown) == 1
        assert _LAYOUT_TEXT in shown[0]["text"]
        assert shown[0]["allow_save"] is False
    finally:
        session.reset()


# ---------------------------------------------------------------------------
# F. layout_unsaved, «отмена» -> окно не закрывается
# ---------------------------------------------------------------------------


def test_close_with_layout_unsaved_cancel_ignores_event(qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    session = TopologySession()
    session.mark_layout_unsaved()
    window = _window(qtbot, session, None)
    shown = _spy_dialog(monkeypatch, "cancel")
    try:
        event = _close(window)

        assert len(shown) == 1
        assert event.isAccepted() is False, "Cancel должен отменить закрытие"
    finally:
        session.reset()


# ---------------------------------------------------------------------------
# H. Регрессия: dirty -> прежний диалог
# ---------------------------------------------------------------------------


def test_close_with_dirty_keeps_old_dialog(qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    session = TopologySession()
    session.mark_edited()
    assert session.dirty is True
    window = _window(qtbot, session, _save_ok)
    shown = _spy_dialog(monkeypatch, "discard")
    try:
        event = _close(window)

        assert len(shown) == 1
        assert _DIRTY_TEXT in shown[0]["text"]
        assert _LAYOUT_TEXT not in shown[0]["text"]
        assert shown[0]["allow_save"] is True
        assert event.isAccepted() is True
    finally:
        session.reset()
