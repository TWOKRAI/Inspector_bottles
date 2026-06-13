"""test_displays_tab.py -- Unit-тесты DisplaysPresenter + DisplaysTab.create (MVP pattern).

Phase F.3: тесты переписаны на DisplaySpec + DisplayCatalog Protocol (writable store).
Phase F.9: create() принимает (AppServices, RuntimeDeps) — Q-F1=B.
Task 5.2 (displays-in-recipe): render-секция формы, scale spinbox, CRUD с render-полями,
persist в рецепт через recipe-scoped catalog.

Покрытие:
1. DisplaysTab.create(services) — без исключений
2. isinstance(tab, IDisplaysView) -> True
3. DisplaysTab получает store=services.displays (нет bridge _registry)
4. presenter.load() -> view.refresh_list вызван
5. presenter.on_create() -> store.register вызван, refresh_list вызван
6. presenter.on_delete() -> store.unregister вызван, refresh_list вызван
7. presenter.on_duplicate('main') -> 'main_copy' в store (с render-полями)
8. on_create с уже существующим id -> view.show_error вызван
9. Форма содержит секцию «Параметры отображения» (QGroupBox)
10. scale QSpinBox: minimum=10, maximum=1000, singleStep=10, default=100
11. on_create с render-полями -> store содержит render-параметры
12. get_form_data возвращает render-поля (crop=None при выключенной галочке)
13. show_entry заполняет render-поля формы
14. Список пуст при отсутствии дисплеев (recipe-scoped)

Refs: plans/displays-in-recipe/plan.md Task 5.2
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
# Тест 1: DisplaysTab.create(services) — без исключений
# ---------------------------------------------------------------------------


def test_create_with_app_services(qtbot):
    """DisplaysTab.create(services) с AppServices DI — без исключений."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    assert tab is not None


# ---------------------------------------------------------------------------
# Тест 2: isinstance(tab, IDisplaysView) -> True
# ---------------------------------------------------------------------------


def test_is_idisplaysview(qtbot):
    """isinstance(tab, IDisplaysView) -> True (structural subtyping)."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    assert isinstance(tab, IDisplaysView)


# ---------------------------------------------------------------------------
# Тест 3: DisplaysTab использует services.displays напрямую (нет bridge)
# ---------------------------------------------------------------------------


def test_create_wires_store_from_services(qtbot):
    """DisplaysTab использует services.displays как store (без bridge _registry)."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    spec = _make_spec("cam1")
    tab = DisplaysTab.create(make_displays_services(specs={"cam1": spec}))
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
    """on_create() -> id генерируется автоматически (display_1), store.register + refresh_list.

    Мульти-дисплей: id больше НЕ берётся из формы (поле read-only/auto).
    """
    mock_view.get_form_data.return_value = {
        "id": "",  # форма не задаёт id (read-only)
        "name": "Новый дисплей",
        "enabled": True,
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
    }

    presenter.on_create()

    # Запись появилась в store под auto-id display_1
    assert store.resolve("display_1") is not None
    assert store.resolve("display_1").display_name == "Новый дисплей"
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


def test_presenter_create_auto_id_skips_taken(
    presenter: DisplaysPresenter,
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """auto-id пропускает занятый display_1 → создаёт display_2 (без ошибки).

    Мульти-дисплей: id генерируется автоматически и всегда уникален —
    коллизия по id из формы больше невозможна.
    """
    store.register(_make_spec("display_1"))

    mock_view.get_form_data.return_value = {
        "id": "",
        "name": "Второй",
        "enabled": True,
        "width": 1280,
        "height": 720,
        "format": "BGR",
        "fps_limit": 30.0,
        "ring_buffer_blocks": 3,
    }

    presenter.on_create()

    assert store.resolve("display_2") is not None
    mock_view.show_error.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 9: Форма содержит секцию «Параметры отображения» (QGroupBox)
# ---------------------------------------------------------------------------


def test_form_has_render_section(qtbot):
    """Форма содержит QGroupBox 'Параметры отображения'."""
    from PySide6.QtWidgets import QGroupBox

    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    # Ищем QGroupBox с objectName "DisplaysFormRenderSection"
    render_section = tab._form_widget.findChild(QGroupBox, "DisplaysFormRenderSection")
    assert render_section is not None, "Секция 'Параметры отображения' не найдена"
    assert render_section.title() == "Параметры отображения"


# ---------------------------------------------------------------------------
# Тест 10: scale QSpinBox — minimum=10, maximum=1000, singleStep=10, default=100
# ---------------------------------------------------------------------------


def test_scale_spinbox_constraints(qtbot):
    """scale QSpinBox: minimum=10, maximum=1000, singleStep=10, default=100."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    spin = tab._scale_spin
    assert spin.minimum() == 10
    assert spin.maximum() == 1000
    assert spin.singleStep() == 10
    assert spin.value() == 100


# ---------------------------------------------------------------------------
# Тест 11: on_create с render-полями → store содержит render-параметры
# ---------------------------------------------------------------------------


def test_presenter_create_with_render_fields(
    presenter: DisplaysPresenter,
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """on_create с render-полями -> store содержит scale/fit/crop (id = auto display_1)."""
    mock_view.get_form_data.return_value = {
        "id": "",  # auto-id
        "name": "Render Test",
        "enabled": True,
        "width": 1920,
        "height": 1080,
        "format": "BGR",
        "fps_limit": 60.0,
        "ring_buffer_blocks": 4,
        "position": {"x": 100, "y": 50},
        "fit": "cover",
        "scale": 150,
        "rotate": 90,
        "flip": "horizontal",
        "crop": {"x": 10, "y": 20, "w": 640, "h": 480},
    }

    presenter.on_create()

    spec = store.resolve("display_1")
    assert spec is not None
    assert spec.scale == 150
    assert spec.fit == "cover"
    assert spec.rotate == 90
    assert spec.flip == "horizontal"
    assert spec.position == {"x": 100, "y": 50}
    assert spec.crop == {"x": 10, "y": 20, "w": 640, "h": 480}


# ---------------------------------------------------------------------------
# Тест 12: get_form_data возвращает render-поля (crop=None при выключенной галочке)
# ---------------------------------------------------------------------------


def test_get_form_data_includes_render_fields(qtbot):
    """get_form_data возвращает render-поля; crop=None при выключенной галочке."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    # Дефолтные значения формы
    data = tab.get_form_data()

    assert "position" in data
    assert data["position"] == {"x": 0, "y": 0}
    assert data["fit"] == "contain"
    assert data["scale"] == 100
    assert data["rotate"] == 0
    assert data["flip"] == "none"
    assert data["crop"] is None  # Галочка по умолчанию выключена


# ---------------------------------------------------------------------------
# Тест 13: show_entry заполняет render-поля формы
# ---------------------------------------------------------------------------


def test_show_entry_fills_render_fields(qtbot):
    """show_entry(spec) заполняет render-поля формы."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    spec_with_render = DisplaySpec(
        display_id="test_render",
        display_name="Test Render",
        width=1920,
        height=1080,
        position={"x": 200, "y": 100},
        fit="stretch",
        scale=75,
        rotate=180,
        flip="both",
        crop={"x": 50, "y": 60, "w": 800, "h": 600},
    )
    tab = DisplaysTab.create(make_displays_services(specs={"test_render": spec_with_render}))
    qtbot.addWidget(tab)

    # Показать запись
    tab.show_entry(spec_with_render)

    assert tab._pos_x_spin.value() == 200
    assert tab._pos_y_spin.value() == 100
    assert tab._fit_combo.currentText() == "stretch"
    assert tab._scale_spin.value() == 75
    assert tab._rotate_combo.currentText() == "180"
    assert tab._flip_combo.currentText() == "both"
    assert tab._crop_enabled_cb.isChecked() is True
    assert tab._crop_x_spin.value() == 50
    assert tab._crop_y_spin.value() == 60
    assert tab._crop_w_spin.value() == 800
    assert tab._crop_h_spin.value() == 600


# ---------------------------------------------------------------------------
# Тест 14: Список пуст при отсутствии дисплеев (recipe-scoped)
# ---------------------------------------------------------------------------


def test_empty_list_no_displays(qtbot):
    """Список пуст при пустом store (нет дисплеев в рецепте)."""
    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    # nav-список пуст
    assert len(tab._key_to_item) == 0


# ---------------------------------------------------------------------------
# Тест 15: Форма содержит обе секции (Базовые + Параметры отображения)
# ---------------------------------------------------------------------------


def test_form_has_both_sections(qtbot):
    """Форма содержит QGroupBox 'Базовые' и 'Параметры отображения'."""
    from PySide6.QtWidgets import QGroupBox

    from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

    from ._helpers import make_displays_services

    tab = DisplaysTab.create(make_displays_services())
    qtbot.addWidget(tab)

    base_section = tab._form_widget.findChild(QGroupBox, "DisplaysFormBaseSection")
    render_section = tab._form_widget.findChild(QGroupBox, "DisplaysFormRenderSection")

    assert base_section is not None, "Секция 'Базовые' не найдена"
    assert base_section.title() == "Базовые"
    assert render_section is not None, "Секция 'Параметры отображения' не найдена"
    assert render_section.title() == "Параметры отображения"


# ---------------------------------------------------------------------------
# Тест 16: on_duplicate копирует render-поля
# ---------------------------------------------------------------------------


def test_duplicate_copies_render_fields(
    store: FakeDisplayCatalog,
    mock_view: MagicMock,
):
    """on_duplicate копирует render-поля из source."""
    source_spec = DisplaySpec(
        display_id="src",
        display_name="Source",
        scale=200,
        fit="cover",
        rotate=90,
        flip="vertical",
        crop={"x": 10, "y": 20, "w": 100, "h": 200},
    )
    store.register(source_spec)

    presenter = DisplaysPresenter(store=store, view=mock_view)
    presenter.on_duplicate("src")

    copy = store.resolve("src_copy")
    assert copy is not None
    assert copy.scale == 200
    assert copy.fit == "cover"
    assert copy.rotate == 90
    assert copy.flip == "vertical"
    assert copy.crop == {"x": 10, "y": 20, "w": 100, "h": 200}
