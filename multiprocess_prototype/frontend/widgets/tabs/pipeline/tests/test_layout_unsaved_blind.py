# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.12 (C-30): автосохранение раскладки узлов и флаг ``layout_unsaved``.

Цепочка настоящая (обвязка ``test_save_conflict_rev.py``): ``PipelinePresenter`` -> ``LayoutController`` ->
``RecipeStoreFromManager`` -> ``RecipeManager`` -> файл в ``tmp_path``, настоящая ``TopologySession`` с базой.

* C: ручная правка файла после захвата базы, автосейв раскладки -> файл не тронут, ``layout_unsaved`` True,
  ``dirty`` False;
* D: правки файла не было, автосейв записал -> ``layout_unsaved`` False;
* G: сквозной — то же, что C, затем закрытие настоящего ``MainWindow`` с ТОЙ ЖЕ сессией: диалог показан.

Ожидаемые значения — литералы. Реальные рецепты только копируются (фикстура в ``recipes/tests/fixtures``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from PySide6.QtGui import QCloseEvent

from multiprocess_prototype.frontend.widgets.tabs.pipeline.tests.test_save_conflict_rev import (  # noqa: F401
    _SLUG,
    _build_store,
    _fixture_a_lf,
    _hand_edited,
    _pipeline_presenter,
    _put,
    _session_with_base,
    _within,
    boxes,  # фикстура: QMessageBox подменён, модального окна в прогоне не будет
)

_DIALOG_TARGET = "multiprocess_prototype.frontend.widgets.dialogs.confirm_unsaved_changes"


def _autosave_with_moved_node(presenter: Any) -> None:
    """Позиция узла заведомо отличается от записанной в файле; запустить автосохранение раскладки."""
    presenter._layout.gui_positions["camera_0"] = (987.0, 654.0)
    _within(60, presenter._layout._persist_layout_to_recipe)


# ---------------------------------------------------------------------------
# C. Автосохранение после ручной правки: файл цел, потеря видима в сессии
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_autosave_after_hand_edit_marks_layout_unsaved(tmp_path: Path) -> None:
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    hand_edited = _hand_edited(src)
    path.write_bytes(hand_edited)

    _autosave_with_moved_node(presenter)

    assert path.read_bytes() == hand_edited
    assert session.layout_unsaved is True
    assert session.dirty is False


# ---------------------------------------------------------------------------
# D. Автосохранение без ручной правки: запись прошла, флаг не поднят
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_autosave_without_hand_edit_keeps_layout_saved(tmp_path: Path) -> None:
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)

    _autosave_with_moved_node(presenter)

    assert path.read_bytes() != src, "запись должна была пройти: позиция узла изменилась"
    assert session.layout_unsaved is False


# ---------------------------------------------------------------------------
# G. Сквозной: перенос узла -> автосейв (конфликт) -> закрытие окна с той же сессией
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_moved_node_then_conflict_then_close_shows_dialog(tmp_path: Path, qtbot: Any, monkeypatch: Any) -> None:
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    shown: list[dict] = []

    def _spy(parent: Any, *, allow_save: bool = True, text: str = "") -> str:
        shown.append({"allow_save": allow_save, "text": text})
        return "discard"

    monkeypatch.setattr(_DIALOG_TARGET, _spy)

    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_topology_session(session, None)
    try:
        hand_edited = _hand_edited(src)
        path.write_bytes(hand_edited)

        # Перенос узла пользователем: позиция уходит в модель раскладки, затем срабатывает автосохранение.
        presenter._layout.on_node_moved("camera_0", 987.0, 654.0)
        presenter._layout.stop_persist_timer()
        _within(60, presenter._layout._persist_layout_to_recipe)
        assert path.read_bytes() == hand_edited, "конфликт: файл с ручной правкой не должен быть затёрт"

        event = QCloseEvent()
        event.accept()
        window.closeEvent(event)

        assert len(shown) == 1, "закрытие с несохранённой раскладкой должно показать диалог ровно один раз"
        assert "Позиции узлов не сохранены" in shown[0]["text"]
        assert shown[0]["allow_save"] is False
        assert event.isAccepted() is True
    finally:
        session.reset()  # иначе teardown qtbot закроет окно и встанет модальный диалог
