"""test_displays_tab.py -- Unit-тесты DisplaysPresenter + DisplaysTab.create (MVP pattern).

Покрытие:
1. DisplaysTab.create(ctx) с AppServices (Task E.6) — без исключений
2. isinstance(tab, IDisplaysView) → True
3. presenter.load() → view.refresh_list вызван
4. presenter.on_create() → registry.register вызван, refresh_list вызван
5. presenter.on_delete() → registry.unregister вызван, refresh_list вызван
6. presenter.on_duplicate('main') → в registry появился 'main_copy'
7. on_create с уже существующим id → view.show_error вызван

Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md Task 4.8,
      plans/2026-05-27_cross-tab-architecture/phase-e-per-tab-migration.md Task E.6
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import (
    DisplaysPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.displays.view import IDisplaysView


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_entry(display_id: str = "main") -> DisplayEntry:
    """Создать DisplayEntry-заглушку."""
    return DisplayEntry(
        id=display_id,
        name=f"Дисплей {display_id}",
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


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очистить singleton DisplayRegistry перед/после каждого теста."""
    DisplayRegistry().clear()
    yield
    DisplayRegistry().clear()


@pytest.fixture()
def registry() -> DisplayRegistry:
    return DisplayRegistry()


@pytest.fixture()
def mock_view() -> MagicMock:
    return _make_mock_view()


@pytest.fixture()
def tmp_yaml(tmp_path: Path) -> Path:
    return tmp_path / "displays.yaml"


@pytest.fixture()
def presenter(registry: DisplayRegistry, mock_view: MagicMock, tmp_yaml: Path) -> DisplaysPresenter:
    return DisplaysPresenter(
        registry=registry,
        view=mock_view,
        yaml_path=tmp_yaml,
    )


# ---------------------------------------------------------------------------
# Тест 1: DisplaysTab.create(ctx) с AppServices (Task E.6) — без исключений
# ---------------------------------------------------------------------------


def test_create_with_app_services(qtbot):
    """DisplaysTab.create(ctx) с AppServices DI — без исключений."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import _StubDisplaysCtx, make_displays_services

    ctx = _StubDisplaysCtx(make_displays_services(registry=DisplayRegistry()))
    tab = DisplaysTab.create(ctx)
    qtbot.addWidget(tab)

    assert tab is not None


# ---------------------------------------------------------------------------
# Тест 2: isinstance(tab, IDisplaysView) → True
# ---------------------------------------------------------------------------


def test_is_idisplaysview(qtbot):
    """isinstance(tab, IDisplaysView) → True (structural subtyping)."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import _StubDisplaysCtx, make_displays_services

    ctx = _StubDisplaysCtx(make_displays_services(registry=DisplayRegistry()))
    tab = DisplaysTab.create(ctx)
    qtbot.addWidget(tab)

    assert isinstance(tab, IDisplaysView)


# ---------------------------------------------------------------------------
# Тест 2b: bridge — DisplaysTab берёт registry из services.displays._registry
# ---------------------------------------------------------------------------


def test_create_wires_bridge_registry(qtbot):
    """DisplaysTab резолвит реальный DisplayRegistry через services.displays._registry."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import _StubDisplaysCtx, make_displays_services

    reg = DisplayRegistry()
    reg.register(_make_entry("cam1"))

    ctx = _StubDisplaysCtx(make_displays_services(registry=reg))
    tab = DisplaysTab.create(ctx)
    qtbot.addWidget(tab)

    # Bridge подключил тот же экземпляр реестра, что и в AppServices
    assert tab._registry is reg
    # presenter.load() при init заполнил nav-список из bridge-реестра
    assert "cam1" in tab._key_to_item


# ---------------------------------------------------------------------------
# Тест 3: presenter.load() → view.refresh_list вызван
# ---------------------------------------------------------------------------


def test_presenter_load_calls_refresh(
    presenter: DisplaysPresenter,
    mock_view: MagicMock,
):
    """presenter.load() → view.refresh_list вызван."""
    presenter.load()
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 4: presenter.on_create() → registry.register вызван, refresh_list вызван
# ---------------------------------------------------------------------------


def test_presenter_create_calls_register(
    presenter: DisplaysPresenter,
    registry: DisplayRegistry,
    mock_view: MagicMock,
):
    """mock view.get_form_data returns dict → on_create() → registry.register + refresh_list."""
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

    # Запись появилась в registry
    assert registry.get("new_display") is not None
    # refresh_list был вызван
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 5: presenter.on_delete() → registry.unregister вызван, refresh_list вызван
# ---------------------------------------------------------------------------


def test_presenter_delete_calls_unregister(
    presenter: DisplaysPresenter,
    registry: DisplayRegistry,
    mock_view: MagicMock,
):
    """presenter.on_delete('main') → registry.unregister('main'), refresh_list вызван."""
    registry.register(_make_entry("main"))

    presenter.on_delete("main")

    assert registry.get("main") is None
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 6: presenter.on_duplicate('main') → 'main_copy' в registry
# ---------------------------------------------------------------------------


def test_presenter_duplicate_creates_copy(
    presenter: DisplaysPresenter,
    registry: DisplayRegistry,
    mock_view: MagicMock,
):
    """registry с 'main' → on_duplicate('main') → 'main_copy' появился в registry."""
    registry.register(_make_entry("main"))

    presenter.on_duplicate("main")

    copy_entry = registry.get("main_copy")
    assert copy_entry is not None
    assert copy_entry.id == "main_copy"
    mock_view.refresh_list.assert_called()


# ---------------------------------------------------------------------------
# Тест 7: on_create с уже существующим id → view.show_error вызван
# ---------------------------------------------------------------------------


def test_presenter_create_duplicate_shows_error(
    presenter: DisplaysPresenter,
    registry: DisplayRegistry,
    mock_view: MagicMock,
):
    """on_create с уже существующим id → view.show_error вызван."""
    registry.register(_make_entry("existing"))

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
