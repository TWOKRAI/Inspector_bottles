"""Тесты Task 2.7: PathsSubtabWidget — подвкладка «Пути» в PluginsTab."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend.widgets.tabs.plugins.paths_subtab import PathsSubtabWidget
from multiprocess_prototype.frontend.widgets.tabs.plugins.presenter import PluginsPresenter


# ------------------------------------------------------------------ #
#  Вспомогательные утилиты                                            #
# ------------------------------------------------------------------ #


def _make_mock_ctx() -> MagicMock:
    """Создать минимальный mock AppContext для тестов PathsSubtabWidget."""
    ctx = MagicMock()
    ctx.plugin_registry.return_value = None
    ctx.registers_manager.return_value = None
    ctx.config = {}
    ctx.extras = {}
    ctx.bindings.return_value = None
    ctx.action_bus.return_value = None
    ctx.form_context.return_value = None
    # По умолчанию plugin_manager возвращает None
    ctx.plugin_manager.return_value = None
    return ctx


def _make_mock_plugin_manager(plugin_paths: list[Path] | None = None) -> MagicMock:
    """Создать mock PluginManager с заданными plugin_paths."""
    pm = MagicMock()
    pm.plugin_paths = plugin_paths or []
    return pm


# ------------------------------------------------------------------ #
#  Тесты                                                              #
# ------------------------------------------------------------------ #


def test_paths_subtab_creates_without_plugin_manager(qtbot: pytest.fixture) -> None:
    """Виджет создаётся без ошибок, список пустой, если PluginManager == None."""
    ctx = _make_mock_ctx()
    # plugin_manager() явно возвращает None
    ctx.plugin_manager.return_value = None

    widget = PathsSubtabWidget(PluginsPresenter(ctx))
    qtbot.addWidget(widget)

    # Виджет создан, список путей пустой
    assert widget._list.count() == 0


def test_paths_subtab_shows_paths_from_manager(qtbot: pytest.fixture) -> None:
    """Список заполняется путями из PluginManager.plugin_paths."""
    ctx = _make_mock_ctx()
    pm = _make_mock_plugin_manager(plugin_paths=[Path("/test/Plugins")])
    ctx.plugin_manager.return_value = pm

    widget = PathsSubtabWidget(PluginsPresenter(ctx))
    qtbot.addWidget(widget)

    # Ровно один элемент
    assert widget._list.count() == 1
    # Текст содержит путь (независимо от OS-разделителей — проверяем подстроку)
    item_text = widget._list.item(0).text()
    # Путь должен содержать "test" и "Plugins" независимо от разделителей
    assert "test" in item_text.replace("\\", "/")
    assert "Plugins" in item_text


def test_rescan_updates_status(qtbot: pytest.fixture) -> None:
    """После _on_rescan() статус-строка содержит количество загруженных плагинов."""
    ctx = _make_mock_ctx()

    # Создаём mock результата rescan
    rescan_result = MagicMock()
    rescan_result.loaded = ["p1"]
    rescan_result.failed = []
    rescan_result.new_plugins = ["p1"]

    pm = _make_mock_plugin_manager()
    pm.rescan.return_value = rescan_result
    pm.plugin_paths = []
    ctx.plugin_manager.return_value = pm

    widget = PathsSubtabWidget(PluginsPresenter(ctx))
    qtbot.addWidget(widget)

    # Вызываем rescan программно
    widget._on_rescan()

    # Статус-строка должна содержать "1" (загружено: 1)
    status_text = widget._status.text()
    assert "1" in status_text


def test_catalog_updated_emitted_on_rescan(qtbot: pytest.fixture) -> None:
    """После _on_rescan() сигнал catalog_updated emit'ится."""
    ctx = _make_mock_ctx()

    # Настраиваем mock rescan — возвращает корректный объект
    rescan_result = MagicMock()
    rescan_result.loaded = []
    rescan_result.failed = []
    rescan_result.new_plugins = []

    pm = _make_mock_plugin_manager()
    pm.rescan.return_value = rescan_result
    pm.plugin_paths = []
    ctx.plugin_manager.return_value = pm

    widget = PathsSubtabWidget(PluginsPresenter(ctx))
    qtbot.addWidget(widget)

    # Ожидаем сигнал catalog_updated при вызове _on_rescan()
    with qtbot.waitSignal(widget.catalog_updated, timeout=1000):
        widget._on_rescan()
