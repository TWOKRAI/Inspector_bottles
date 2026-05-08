"""Тесты для PluginsTab."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype_2.frontend.widgets.tabs.plugins.tab import PluginsTab
from multiprocess_prototype_2.frontend.widgets.tabs.plugins.presenter import PluginsPresenter
from multiprocess_prototype_2.frontend.widgets.tabs.plugins.detail_panels import PluginInfoCard


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


def _make_mock_ctx(entries: list[_MockEntry] | None = None) -> MagicMock:
    if entries is None:
        entries = [
            _MockEntry("color_mask", "processing", "Цветовая маска", register_classes=["FakeReg"]),
            _MockEntry("grayscale", "processing", "Чёрно-белое"),
            _MockEntry("capture", "source", "Захват камеры"),
        ]

    registry = _MockRegistry(entries)

    ctx = MagicMock()
    ctx.plugin_registry.return_value = registry
    ctx.registers_manager.return_value = None  # нет RegistersManager в тестах
    ctx.config = {}
    ctx.extras = {}
    ctx.bindings.return_value = None
    return ctx


class TestPluginsPresenter:
    def test_list_plugins(self) -> None:
        ctx = _make_mock_ctx()
        p = PluginsPresenter(ctx)
        items = p.list_plugins()
        assert len(items) == 3
        names = [item[0] for item in items]
        assert "color_mask" in names

    def test_get_categories(self) -> None:
        ctx = _make_mock_ctx()
        p = PluginsPresenter(ctx)
        cats = p.get_categories()
        assert "processing" in cats
        assert "source" in cats

    def test_get_plugin_info_with_registers(self) -> None:
        ctx = _make_mock_ctx()
        p = PluginsPresenter(ctx)
        info = p.get_plugin_info("color_mask")
        assert info["name"] == "color_mask"
        assert info["has_registers"] is True

    def test_get_plugin_info_without_registers(self) -> None:
        ctx = _make_mock_ctx()
        p = PluginsPresenter(ctx)
        info = p.get_plugin_info("grayscale")
        assert info["has_registers"] is False

    def test_get_plugin_info_unknown(self) -> None:
        ctx = _make_mock_ctx()
        p = PluginsPresenter(ctx)
        info = p.get_plugin_info("nonexistent")
        assert info["name"] == "nonexistent"
        assert info["has_registers"] is False

    def test_no_registry(self) -> None:
        ctx = MagicMock()
        ctx.plugin_registry.return_value = None
        p = PluginsPresenter(ctx)
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


class TestPluginsTab:
    def test_create(self, qtbot: pytest.fixture) -> None:
        ctx = _make_mock_ctx()
        tab = PluginsTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_plugins_listed(self, qtbot: pytest.fixture) -> None:
        ctx = _make_mock_ctx()
        tab = PluginsTab(ctx)
        qtbot.addWidget(tab)
        # MasterDetailLayout должен содержать 3 item'а
        assert tab._master_detail._item_list.count() == 3

    def test_empty_registry(self, qtbot: pytest.fixture) -> None:
        ctx = _make_mock_ctx(entries=[])
        tab = PluginsTab(ctx)
        qtbot.addWidget(tab)

    def test_on_plugin_selected_no_registers(self, qtbot: pytest.fixture) -> None:
        ctx = _make_mock_ctx()
        tab = PluginsTab(ctx)
        qtbot.addWidget(tab)
        tab._on_plugin_selected("grayscale")
        assert "grayscale" in tab._detail_cache

    def test_on_plugin_selected_with_registers_no_manager(self, qtbot: pytest.fixture) -> None:
        ctx = _make_mock_ctx()
        tab = PluginsTab(ctx)
        qtbot.addWidget(tab)
        tab._on_plugin_selected("color_mask")
        # Без RegistersManager — fallback на PluginInfoCard
        assert "color_mask" in tab._detail_cache
        assert isinstance(tab._detail_cache["color_mask"], PluginInfoCard)

    def test_detail_cache(self, qtbot: pytest.fixture) -> None:
        ctx = _make_mock_ctx()
        tab = PluginsTab(ctx)
        qtbot.addWidget(tab)
        tab._on_plugin_selected("capture")
        tab._on_plugin_selected("capture")  # второй раз не должен пересоздавать
        assert len(tab._detail_cache) == 1
