"""Тесты для PluginsTab (Task E.5: AppServices DI, F.5: PluginCatalog Protocol).

Task F.5: presenter полностью на PluginCatalog Protocol. Тесты используют
FakePluginCatalog с PluginSpec (включая ports и has_registers) вместо
raw _MockRegistry bridge.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.domain.protocols.plugin_catalog import (
    PluginSpec,
    PortSpec,
)
from multiprocess_prototype.domain.tests._fakes import FakePluginCatalog
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode
from multiprocess_prototype.frontend.widgets.tabs.plugins.tab import PluginsTab
from multiprocess_prototype.frontend.widgets.tabs.plugins.presenter import PluginsPresenter
from multiprocess_prototype.frontend.widgets.tabs.plugins.detail_panels import PluginInfoCard

from ._helpers import _StubPluginsCtx


# ---------------------------------------------------------------------------
# Фабрики тестовых данных
# ---------------------------------------------------------------------------


def _default_specs() -> dict[str, PluginSpec]:
    """Тестовый набор PluginSpec (3 плагина, 2 категории)."""
    return {
        "color_mask": PluginSpec(
            name="color_mask",
            category="processing",
            description="Цветовая маска",
            has_registers=True,
            ports=(
                PortSpec(name="frame", dtype="image/bgr", direction="input"),
                PortSpec(name="mask", dtype="image/bgr", direction="output"),
            ),
        ),
        "grayscale": PluginSpec(
            name="grayscale",
            category="processing",
            description="Чёрно-белое",
            ports=(
                PortSpec(name="frame", dtype="image/bgr", direction="input"),
                PortSpec(name="frame", dtype="image/gray", direction="output"),
            ),
        ),
        "capture": PluginSpec(
            name="capture",
            category="source",
            description="Захват камеры",
            ports=(PortSpec(name="frame", dtype="image/bgr", direction="output"),),
        ),
    }


def _make_services(specs: dict[str, PluginSpec] | None = None):
    """AppServices с FakePluginCatalog (PluginSpec-based)."""
    if specs is None:
        specs = _default_specs()
    plugins = FakePluginCatalog(specs=specs)
    return make_test_app_services(plugins=plugins)


class TestPluginsPresenter:
    def test_list_plugins(self) -> None:
        p = PluginsPresenter(_make_services())
        items = p.list_plugins()
        assert len(items) == 3
        names = [item[0] for item in items]
        assert "color_mask" in names

    def test_get_categories(self) -> None:
        p = PluginsPresenter(_make_services())
        cats = p.get_categories()
        assert "processing" in cats
        assert "source" in cats

    def test_get_plugin_info_with_registers(self) -> None:
        p = PluginsPresenter(_make_services())
        info = p.get_plugin_info("color_mask")
        assert info["name"] == "color_mask"
        assert info["has_registers"] is True

    def test_get_plugin_info_without_registers(self) -> None:
        p = PluginsPresenter(_make_services())
        info = p.get_plugin_info("grayscale")
        assert info["has_registers"] is False

    def test_get_plugin_info_unknown(self) -> None:
        p = PluginsPresenter(_make_services())
        info = p.get_plugin_info("nonexistent")
        assert info["name"] == "nonexistent"
        assert info["has_registers"] is False

    def test_empty_catalog(self) -> None:
        """Пустой FakePluginCatalog -> presenter возвращает пустые списки."""
        p = PluginsPresenter(_make_services(specs={}))
        assert p.list_plugins() == []
        # Пустой каталог -> categories() вернёт ["default"] (fallback FakePluginCatalog)
        cats = p.get_categories()
        assert isinstance(cats, list)

    def test_get_plugin_info_ports_from_spec(self) -> None:
        """Ports отображаются из PluginSpec.ports (direction-фильтр)."""
        p = PluginsPresenter(_make_services())
        info = p.get_plugin_info("color_mask")
        assert "frame: image/bgr" in info["inputs"]
        assert "mask: image/bgr" in info["outputs"]


class TestPluginInfoCard:
    def test_create(self, qtbot: pytest.fixture) -> None:
        info = {
            "name": "test_plugin",
            "category": "processing",
            "description": "A test plugin",
            "inputs": ["frame: image/bgr"],
            "outputs": ["result: image/bgr"],
        }
        card = PluginInfoCard(info)
        qtbot.addWidget(card)

    def test_create_minimal(self, qtbot: pytest.fixture) -> None:
        card = PluginInfoCard({"name": "x"})
        qtbot.addWidget(card)


def _leaf_keys(tab: PluginsTab) -> list[str]:
    """Вернуть ключи плагин-листов в дереве."""
    tree = tab._tree_nav
    assert tree is not None
    keys: list[str] = []
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        if cat is None:
            continue
        for j in range(cat.childCount()):
            child = cat.child(j)
            if child is None:
                continue
            key = child.data(0, 0x0100)  # Qt.UserRole = 256
            if isinstance(key, str):
                keys.append(key)
    return keys


def _visible_leaf_keys(tab: PluginsTab) -> list[str]:
    """Вернуть ключи плагин-листов, которые сейчас видимы (не isHidden)."""
    tree = tab._tree_nav
    assert tree is not None
    keys: list[str] = []
    for i in range(tree.topLevelItemCount()):
        cat = tree.topLevelItem(i)
        if cat is None or cat.isHidden():
            continue
        for j in range(cat.childCount()):
            child = cat.child(j)
            if child is None or child.isHidden():
                continue
            key = child.data(0, 0x0100)
            if isinstance(key, str):
                keys.append(key)
    return keys


class TestPluginsTab:
    def test_create(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab.create(_StubPluginsCtx(_make_services()))
        qtbot.addWidget(tab)
        assert tab is not None

    def test_plugins_listed_in_tree(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        # В дереве должны быть 3 плагина (под их категориями).
        assert sorted(_leaf_keys(tab)) == ["capture", "color_mask", "grayscale"]
        # Корневых элементов: 1 секция «Пути» (Phase 2) + 2 категории плагинов
        # (processing + source).
        assert tab._tree_nav.topLevelItemCount() == 3

    def test_empty_catalog(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab(_make_services(specs={}))
        qtbot.addWidget(tab)
        # Нет плагинов -- остаётся только секция «Пути» (корневая, Phase 2).
        assert tab._tree_nav.topLevelItemCount() == 1

    def test_lazy_section_created_on_select(self, qtbot: pytest.fixture) -> None:
        # При программном выборе плагина презентер строит секцию через factory.
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        # До выбора плагина -- секция color_mask ещё не создана (lazy).
        tab.select_tree_key("color_mask")
        # Секция color_mask должна быть зарегистрирована в content_stack.
        assert "color_mask" in tab.presenter._page_index  # type: ignore[attr-defined]

    def test_no_register_manager_fallback_to_info_card(self, qtbot: pytest.fixture) -> None:
        # color_mask имеет has_registers=True, но registers_manager=None ->
        # fields пусты, должен сработать fallback на PluginInfoCard.
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        tab.select_tree_key("color_mask")
        idx = tab.presenter._page_index["color_mask"]  # type: ignore[attr-defined]
        widget = tab._content_stack.widget(idx)
        assert isinstance(widget, PluginInfoCard)

    def test_search_filter(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        # До фильтра все плагины видимы.
        assert sorted(_visible_leaf_keys(tab)) == ["capture", "color_mask", "grayscale"]
        # «color» матчит только color_mask; пустая категория «Источники» скрывается.
        tab._search.setText("color")
        visible = _visible_leaf_keys(tab)
        assert "color_mask" in visible
        assert "grayscale" not in visible
        assert "capture" not in visible
        # Очистка -- все снова видимы.
        tab._search.setText("")
        assert sorted(_visible_leaf_keys(tab)) == ["capture", "color_mask", "grayscale"]

    def test_view_mode_toggle_switches_to_table(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        # По умолчанию -- Cards (content_stack показывает страницу плагина/категории).
        cards_idx = tab._content_stack.currentIndex()
        # Переключение на Table -- content_stack показывает _table_widget.
        tab._on_view_mode_changed(ViewMode.TABLE.value)
        assert tab._content_stack.currentIndex() == tab._table_idx
        # Таблица заполнена 3 строками.
        assert tab._table_widget.rowCount() == 3
        # Возврат в Cards -- содержимое не на table_idx.
        tab._on_view_mode_changed(ViewMode.CARDS.value)
        assert tab._content_stack.currentIndex() != tab._table_idx
        _ = cards_idx
