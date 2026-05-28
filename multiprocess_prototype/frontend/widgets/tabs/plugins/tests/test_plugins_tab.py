"""Тесты для PluginsTab (Task E.5: AppServices DI)."""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode
from multiprocess_prototype.frontend.widgets.tabs.plugins.tab import PluginsTab
from multiprocess_prototype.frontend.widgets.tabs.plugins.presenter import PluginsPresenter
from multiprocess_prototype.frontend.widgets.tabs.plugins.detail_panels import PluginInfoCard

from ._helpers import _StubPluginsCtx, make_plugins_services


class _MockEntry:
    """Mock для PluginEntry."""

    def __init__(
        self,
        name: str,
        category: str,
        description: str = "",
        register_classes: list | None = None,
        inputs: list | None = None,
        outputs: list | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.description = description
        self.register_classes = register_classes or []
        self.inputs = inputs or []
        self.outputs = outputs or []


class _MockRegistry:
    """Mock для PluginRegistry."""

    def __init__(self, entries: list[_MockEntry]) -> None:
        self._entries = entries

    def list(self) -> list[_MockEntry]:
        return self._entries

    def get(self, name: str) -> _MockEntry | None:
        return next((e for e in self._entries if e.name == name), None)

    def filter(self, category: str | None = None) -> list[_MockEntry]:
        if category:
            return [e for e in self._entries if e.category == category]
        return self._entries


def _default_entries() -> list[_MockEntry]:
    return [
        _MockEntry("color_mask", "processing", "Цветовая маска", register_classes=["FakeReg"]),
        _MockEntry("grayscale", "processing", "Чёрно-белое"),
        _MockEntry("capture", "source", "Захват камеры"),
    ]


def _make_services(entries: list[_MockEntry] | None = None):
    """AppServices с raw PluginRegistry через bridge."""
    if entries is None:
        entries = _default_entries()
    return make_plugins_services(registry=_MockRegistry(entries))


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

    def test_no_registry(self) -> None:
        # registry=None → services.plugins без _registry bridge → presenter._registry=None
        p = PluginsPresenter(make_plugins_services(registry=None))
        assert p.list_plugins() == []
        assert p.get_categories() == []


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

    def test_empty_registry(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab(_make_services(entries=[]))
        qtbot.addWidget(tab)
        # Нет плагинов — остаётся только секция «Пути» (корневая, Phase 2).
        assert tab._tree_nav.topLevelItemCount() == 1

    def test_lazy_section_created_on_select(self, qtbot: pytest.fixture) -> None:
        # При программном выборе плагина презентер строит секцию через factory.
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        # До выбора плагина — секция color_mask ещё не создана (lazy).
        tab.select_tree_key("color_mask")
        # Секция color_mask должна быть зарегистрирована в content_stack.
        assert "color_mask" in tab.presenter._page_index  # type: ignore[attr-defined]

    def test_no_register_manager_fallback_to_info_card(self, qtbot: pytest.fixture) -> None:
        # color_mask имеет has_registers=True, но registers_manager=None →
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
        # Очистка — все снова видимы.
        tab._search.setText("")
        assert sorted(_visible_leaf_keys(tab)) == ["capture", "color_mask", "grayscale"]

    def test_view_mode_toggle_switches_to_table(self, qtbot: pytest.fixture) -> None:
        tab = PluginsTab(_make_services())
        qtbot.addWidget(tab)
        # По умолчанию — Cards (content_stack показывает страницу плагина/категории).
        cards_idx = tab._content_stack.currentIndex()
        # Переключение на Table — content_stack показывает _table_widget.
        tab._on_view_mode_changed(ViewMode.TABLE.value)
        assert tab._content_stack.currentIndex() == tab._table_idx
        # Таблица заполнена 3 строками.
        assert tab._table_widget.rowCount() == 3
        # Возврат в Cards — содержимое не на table_idx.
        tab._on_view_mode_changed(ViewMode.CARDS.value)
        assert tab._content_stack.currentIndex() != tab._table_idx
        _ = cards_idx
