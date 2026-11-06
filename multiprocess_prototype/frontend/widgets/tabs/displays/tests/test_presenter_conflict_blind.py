# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.11 (C-30), строка H: конфликт записи в презентере дисплеев.

Если ``store.update`` (``on_set_enabled``) или ``store.unregister`` (``on_delete``) бросает
``ValueError("Рецепт изменён снаружи — перезагрузите его")``, презентер показывает ровно одну ошибку
с этим текстом; ``store.persist`` не вызывается, событие ``DisplaysChanged`` не публикуется.
Fake-store и fake-view — по образцу ``test_presenter_multidisplay.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.domain.tests._fakes import FakeDisplayCatalog
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import DisplaysPresenter

_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"


class _ConflictStore(FakeDisplayCatalog):
    """Fake-каталог: update/unregister бросают конфликт; persist считается."""

    def __init__(self) -> None:
        super().__init__(specs={"d1": DisplaySpec(display_id="d1", display_name="D1", enabled=True)})
        self.persist_calls = 0

    def update(self, spec: DisplaySpec) -> bool:
        raise ValueError(_CONFLICT_TEXT)

    def unregister(self, display_id: str) -> bool:
        raise ValueError(_CONFLICT_TEXT)

    def persist(self) -> None:
        self.persist_calls += 1


class _FakeView:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def refresh_list(self, specs: Any) -> None:
        pass

    def show_entry(self, spec: Any) -> None:
        pass

    def set_buttons_state(self, has_selection: bool) -> None:
        pass

    def get_form_data(self) -> dict:
        return {}

    def show_error(self, message: str) -> None:
        self.errors.append(message)


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, event: Any) -> None:
        self.published.append(event)


def _make() -> tuple[_ConflictStore, _FakeView, _FakeEventBus, DisplaysPresenter]:
    store = _ConflictStore()
    view = _FakeView()
    bus = _FakeEventBus()
    return store, view, bus, DisplaysPresenter(store=store, view=view, event_bus=bus)


def test_set_enabled_conflict_shows_single_error_with_text() -> None:
    """on_set_enabled: update бросил конфликт -> show_error ровно один раз с текстом."""
    store, view, bus, presenter = _make()

    presenter.on_set_enabled("d1", False)

    assert view.errors == [_CONFLICT_TEXT]


def test_set_enabled_conflict_no_persist_no_event() -> None:
    """on_set_enabled: при конфликте persist не вызван, DisplaysChanged не опубликован."""
    store, view, bus, presenter = _make()

    presenter.on_set_enabled("d1", False)

    assert store.persist_calls == 0
    assert bus.published == []


def test_delete_conflict_shows_single_error_with_text() -> None:
    """on_delete: unregister бросил конфликт -> show_error ровно один раз с текстом."""
    store, view, bus, presenter = _make()

    presenter.on_delete("d1")

    assert view.errors == [_CONFLICT_TEXT]


def test_delete_conflict_no_persist_no_event() -> None:
    """on_delete: при конфликте persist не вызван, DisplaysChanged не опубликован."""
    store, view, bus, presenter = _make()

    presenter.on_delete("d1")

    assert store.persist_calls == 0
    assert bus.published == []


def test_non_conflict_value_error_not_swallowed_as_conflict_text() -> None:
    """Контроль фейка: без конфликта (обычный store) on_set_enabled ошибок не показывает и публикует событие."""
    from multiprocess_prototype.domain.events import DisplaysChanged

    store = FakeDisplayCatalog(specs={"d1": DisplaySpec(display_id="d1", display_name="D1", enabled=True)})
    view = _FakeView()
    bus = _FakeEventBus()

    DisplaysPresenter(store=store, view=view, event_bus=bus).on_set_enabled("d1", False)

    assert view.errors == []
    assert [type(e) for e in bus.published] == [DisplaysChanged]


@pytest.mark.parametrize("method", ["on_set_enabled", "on_delete"])
def test_conflict_does_not_raise_out_of_presenter(method: str) -> None:
    """Конфликт не вылетает из презентера в слот Qt: вызов возвращается без исключения."""
    store, view, bus, presenter = _make()

    if method == "on_set_enabled":
        presenter.on_set_enabled("d1", False)
    else:
        presenter.on_delete("d1")
