# -*- coding: utf-8 -*-
"""Task 1.11, ревью находка 2: при конфликте записи on_set_enabled возвращает UI к состоянию рецепта.

``store.update`` бросает ``ValueError`` -> презентер показывает ошибку один раз и один раз
перерисовывает форму исходным spec дисплея (в рецепте старое ``enabled``), иначе чекбокс
остаётся в новом состоянии, которого в файле нет.
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.domain.tests._fakes import FakeDisplayCatalog
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import DisplaysPresenter

_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"


class _ConflictStore(FakeDisplayCatalog):
    def __init__(self) -> None:
        super().__init__(specs={"d1": DisplaySpec(display_id="d1", display_name="D1", enabled=True)})

    def update(self, spec: DisplaySpec) -> bool:
        raise ValueError(_CONFLICT_TEXT)


class _FakeView:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.shown: list[Any] = []

    def refresh_list(self, specs: Any) -> None:
        pass

    def show_entry(self, spec: Any) -> None:
        self.shown.append(spec)

    def set_buttons_state(self, has_selection: bool) -> None:
        pass

    def get_form_data(self) -> dict:
        return {}

    def show_error(self, message: str) -> None:
        self.errors.append(message)


class _FakeEventBus:
    def publish(self, event: Any) -> None:
        pass


def test_set_enabled_conflict_restores_entry_with_original_spec() -> None:
    """Конфликт: show_error один раз; show_entry один раз с исходным spec (enabled=True)."""
    store = _ConflictStore()
    view = _FakeView()
    presenter = DisplaysPresenter(store=store, view=view, event_bus=_FakeEventBus())

    presenter.on_set_enabled("d1", False)

    assert view.errors == [_CONFLICT_TEXT]
    assert len(view.shown) == 1
    assert view.shown[0].display_id == "d1"
    assert view.shown[0].enabled is True
