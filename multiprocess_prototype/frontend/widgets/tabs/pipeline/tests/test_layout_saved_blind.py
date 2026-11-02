# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.15 (C-30): успешный автосейв раскладки снимает ``layout_unsaved``.

Цепочка настоящая (обвязка ``test_save_conflict_rev.py``): ``PipelinePresenter`` -> ``LayoutController`` ->
``RecipeStoreFromManager`` -> ``RecipeManager`` -> файл в ``tmp_path``, настоящая ``TopologySession`` с базой.

* ACC 4: конфликт (флаг поднят) -> ручную правку откатили -> перенос узла -> автосейв записал: флаг False;
* ACC 5: автосейв при конфликте поднимает флаг и не трогает файл (поведение 1.12 цело);
* ACC 6: автосейв без активного рецепта флаг не трогает;
* ACC 7: ``save_layout`` бросил OSError -> автосейв не падает, флаг остаётся поднятым.

Ожидаемые значения — литералы. Реальные рецепты только копируются (фикстура в ``recipes/tests/fixtures``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_prototype.frontend.widgets.tabs.pipeline.tests.test_save_conflict_rev import (  # noqa: F401
    _OLD_MTIME_NS,
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


def _move_node_and_autosave(presenter: Any, x: float, y: float) -> None:
    """Позиция узла camera_0 -> (x, y); запустить автосохранение раскладки (в daemon-потоке с дедлайном)."""
    presenter._layout.gui_positions["camera_0"] = (x, y)
    _within(60, presenter._layout._persist_layout_to_recipe)


def _camera_0_position(path: Path) -> list[float]:
    """Позиция camera_0 в ``blueprint.metadata.gui_positions`` файла."""
    return yaml.safe_load(path.read_bytes().decode("utf-8"))["blueprint"]["metadata"]["gui_positions"]["camera_0"]


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_autosave_after_reverted_hand_edit_clears_layout_unsaved(tmp_path: Path) -> None:
    """ACC 4: конфликт поднял флаг; правку откатили (байты == база); перенос узла + автосейв -> запись, флаг False."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    path.write_bytes(_hand_edited(src))

    _move_node_and_autosave(presenter, 987.0, 654.0)  # конфликт: файл правлен после захвата базы
    assert session.layout_unsaved is True  # парная проверка: флаг мог измениться и действительно поднят

    path.write_bytes(src)  # правку откатили: rev (хеш содержимого) снова равен базе
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    assert path.read_bytes() == src
    assert b"111.0" not in path.read_bytes(), "до автосейва позиции 111.0 в файле быть не должно"

    _move_node_and_autosave(presenter, 111.0, 222.0)

    assert b"111.0" in path.read_bytes()
    assert _camera_0_position(path) == [111.0, 222.0]
    assert session.layout_unsaved is False


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_autosave_conflict_keeps_layout_unsaved_and_file(tmp_path: Path) -> None:
    """ACC 5: автосейв при конфликте (файл правлен, не откатан) -> флаг True, байты файла == ручной правке."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    hand_edited = _hand_edited(src)
    path.write_bytes(hand_edited)
    assert session.layout_unsaved is False  # до автосейва флаг не поднят: True ниже придёт только из конфликта

    _move_node_and_autosave(presenter, 111.0, 222.0)

    assert session.layout_unsaved is True
    assert path.read_bytes() == hand_edited


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_autosave_without_active_recipe_leaves_layout_unsaved(tmp_path: Path) -> None:
    """ACC 6: нет активного рецепта -> автосейв выходит раньше, флаг (был True) остаётся True, файл не тронут."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    session.mark_layout_unsaved()
    store.deactivate()
    assert store.get_active() is None  # рецепт действительно не активен

    _move_node_and_autosave(presenter, 111.0, 222.0)

    assert session.layout_unsaved is True
    assert path.read_bytes() == src


@pytest.mark.usefixtures("boxes")  # QMessageBox подменён: модального окна в прогоне не будет
def test_autosave_save_layout_oserror_keeps_layout_unsaved(tmp_path: Path, monkeypatch: Any) -> None:
    """ACC 7: флаг True, store.save_layout бросает OSError -> автосейв не падает наружу, флаг остаётся True."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    session.mark_layout_unsaved()
    calls: list[str] = []

    def _broken_save_layout(*args: Any, **kwargs: Any) -> None:
        calls.append("save_layout")
        raise OSError("диск недоступен")

    monkeypatch.setattr(store, "save_layout", _broken_save_layout)

    _move_node_and_autosave(presenter, 111.0, 222.0)  # исключение наружу не вышло: _within пробросил бы его

    assert calls == ["save_layout"], "автосейв должен был дойти до записи, а не выйти раньше"
    assert session.layout_unsaved is True
    assert path.read_bytes() == src
