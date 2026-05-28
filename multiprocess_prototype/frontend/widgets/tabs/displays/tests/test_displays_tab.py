"""test_displays_tab.py -- Unit-тесты DisplaysPresenter + DisplaysTab.create (MVP pattern).

Phase F.3: тесты переписаны на DisplaySpec + DisplayCatalog Protocol (writable store).
Паттерн: FakeDisplayCatalog из domain/tests/_fakes.py (не MagicMock).

Покрытие:
1. DisplaysTab.create(ctx) с AppServices — без исключений
2. isinstance(tab, IDisplaysView) -> True
3. DisplaysTab получает store=services.displays (нет bridge _registry)
4. presenter.load() -> view.refresh_list вызван
5. presenter.on_create() -> store.register вызван, refresh_list вызван
6. presenter.on_delete() -> store.unregister вызван, refresh_list вызван
7. presenter.on_duplicate('main') -> в store появился 'main_copy'
8. on_create с уже существующим id -> view.show_error вызван

Refs: plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md Task F.3
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.domain.tests._fakes import FakeDisplayCatalog
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import (
    DisplaysPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.displays.view import IDisplaysView


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_spec(display_id: str = "main") -> DisplaySpec:
    """Создать DisplaySpec-заглушку."""
    return DisplaySpec(
        display_id=display_id,
        display_name=f"Дисплей {display_id}",
        width=1280,
        height=720,
        format="BGR",
        fps_limit=30.0,
        ring_buffer_blocks=3,
    )


def _make_mock_view() -> MagicMock:
    """Создать mock, совместимый с IDisplaysView."""
    view = MagicMock()
    view.get_form_data.return_value = {
        "id": "new_display",
        "name": "Новый дисплей",
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
    }
    return view


def _make_store(*specs: DisplaySpec) -> FakeDisplayCatalog:
    """Создать FakeDisplayCatalog с заданными DisplaySpec."""
    store = FakeDisplayCatalog()
    for spec in specs:
        store.register(spec)
    return store


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> FakeDisplayCatalog:
    return FakeDisplayCatalog()


@pytest.fixture()
def mock_view() -> MagicMock:
    return _make_mock_view()


@pytest.fixture()
def presenter(store: FakeDisplayCatalog, mock_view: MagicMock) -> DisplaysPresenter:
    return DisplaysPresenter(
        store=store,
        view=mock_view,
    )


# ---------------------------------------------------------------------------
# Тест 1: DisplaysTab.create(ctx) с AppServices — без исключений
# ---------------------------------------------------------------------------


def test_create_with_app_services(qtbot):
    """DisplaysTab.create(ctx) с AppServices DI — без исключений."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import _StubDisplaysCtx, make_displays_services

    ctx = _StubDisplaysCtx(make_displays_services())
    tab = DisplaysTab.create(ctx)
    qtbot.addWidget(tab)

    assert tab is not None


# ---------------------------------------------------------------------------
# Тест 2: isinstance(tab, IDisplaysView) -> True
# ---------------------------------------------------------------------------


def test_is_idisplaysview(qtbot):
    """isinstance(tab, IDisplaysView) -> True (structural subtyping)."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import _StubDisplaysCtx, make_displays_services

    ctx = _StubDisplaysCtx(make_displays_services())
    tab = DisplaysTab.create(ctx)
    qtbot.addWidget(tab)

    assert isinstance(tab, IDisplaysView)


# ---------------------------------------------------------------------------
# Тест 3: DisplaysTab использует services.displays напрямую (нет bridge)
# ---------------------------------------------------------------------------


def test_create_wires_store_from_services(qtbot):
    """DisplaysTab использует services.displays как store (без bridge _registry)."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import _StubDisplaysCtx, make_displays_services

    spec = _make_spec("cam1")
    ctx = _StubDisplaysCtx(make_displays_services(specs={"cam1": spec}))
    tab = DisplaysTab.create(ctx)
    qtbot.addWidget(tab)

    # presenter.load() при init заполнил nav-список из services.displays
    assert "cam1" in tab._key_to_item


# ---------------------------------------------------------------------------
# Тест 4: presenter.load() -> view.refresh_list вызван
# ---------------------------------------------------------------------------


def test_presenter_load_calls_refresh(
    presenter: DisplaysPresenter,
    mock_view: MagicMock,
):
    """presenter.load() -> view.refresh_list вызван."""
    presenter.load()
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 5: presenter.on_create() -> store.register вызван, refresh_list вызван
# ---------------------------------------------------------------------------


def test_presenter_create_calls_register(
    presenter: DisplaysPresenter,
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """mock view.get_form_data returns dict -> on_create() -> store.register + refresh_list."""
    mock_view.get_form_data.return_value = {
        "id": "new_display",
        "name": "Новый дисплей",
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
    }

    presenter.on_create()

    # Запись появилась в store
    assert store.resolve("new_display") is not None
    # refresh_list был вызван
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 6: presenter.on_delete() -> store.unregister вызван, refresh_list вызван
# ---------------------------------------------------------------------------


def test_presenter_delete_calls_unregister(
    presenter: DisplaysPresenter,
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """presenter.on_delete('main') -> store.unregister('main'), refresh_list вызван."""
    store.register(_make_spec("main"))

    presenter.on_delete("main")

    assert store.resolve("main") is None
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 7: presenter.on_duplicate('main') -> 'main_copy' в store
# ---------------------------------------------------------------------------


def test_presenter_duplicate_creates_copy(
    presenter: DisplaysPresenter,
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """store с 'main' -> on_duplicate('main') -> 'main_copy' появился в store."""
    store.register(_make_spec("main"))

    presenter.on_duplicate("main")

    copy_spec = store.resolve("main_copy")
    assert copy_spec is not None
    assert copy_spec.display_id == "main_copy"
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 8: on_create с уже существующим id -> view.show_error вызван
# ---------------------------------------------------------------------------


def test_presenter_create_duplicate_shows_error(
    presenter: DisplaysPresenter,
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """on_create с уже существующим id -> view.show_error вызван."""
    store.register(_make_spec("existing"))

    mock_view.get_form_data.return_value = {
        "id": "existing",
        "name": "Дубликат",
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
    }

    presenter.on_create()

    mock_view.show_error.assert_called_once()
