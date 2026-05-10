"""Тесты для PluginCatalogWidget.

Используется mocking PluginRegistry — реальный реестр не требуется.
Модуль загружается через importlib.util напрямую — минуя circular imports
в tabs_setting/__init__.py пакетной иерархии.

Тесты работают без pytest-qt: QApplication создаётся вручную через фикстуру.

Запуск: python -m pytest multiprocess_prototype/tests/unit/test_plugin_catalog_widget.py -v
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Фикстура QApplication (создаётся один раз на сессию)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Создать или вернуть существующий QApplication для тестов."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Загрузка модуля виджета напрямую (обход circular imports через __init__.py)
# ---------------------------------------------------------------------------

def _load_widget_module():
    """Загрузить plugin_catalog_widget.py напрямую через importlib.util.

    Обходит цепочку circular imports, которая возникает при стандартном
    импорте через пакетный __init__.py tabs_setting.
    """
    module_name = "_plugin_catalog_widget_direct"
    if module_name in sys.modules:
        return sys.modules[module_name]

    module_path = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "widgets"
        / "tabs_setting"
        / "processes_tab"
        / "plugin_catalog_widget.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Загружаем модуль один раз при импорте тестового файла
_catalog_module = _load_widget_module()
PluginCatalogWidget = _catalog_module.PluginCatalogWidget


# ---------------------------------------------------------------------------
# Имя модуля реестра для подстановки через sys.modules
# ---------------------------------------------------------------------------

# Виджет делает ленивый import внутри refresh():
#   from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
# Патчим весь модуль в sys.modules, подставляя fake_registry как атрибут.

_REGISTRY_MODULE_PATH = (
    "multiprocess_framework.modules.process_module.plugins.registry"
)


class _FakeRegistryModule(types.ModuleType):
    """Минимальный fake-модуль реестра для подстановки в sys.modules."""

    def __init__(self, registry_instance) -> None:
        super().__init__(_REGISTRY_MODULE_PATH)
        self.PluginRegistry = registry_instance


class _RegistryPatch:
    """Контекст-менеджер: подставляет fake PluginRegistry в sys.modules."""

    def __init__(self, registry_instance) -> None:
        self._fake_module = _FakeRegistryModule(registry_instance)
        self._orig = None

    def __enter__(self):
        self._orig = sys.modules.get(_REGISTRY_MODULE_PATH)
        sys.modules[_REGISTRY_MODULE_PATH] = self._fake_module
        return self

    def __exit__(self, *args):
        if self._orig is None:
            sys.modules.pop(_REGISTRY_MODULE_PATH, None)
        else:
            sys.modules[_REGISTRY_MODULE_PATH] = self._orig


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_port(name: str, dtype: str) -> MagicMock:
    """Создать mock-объект Port с нужными атрибутами."""
    port = MagicMock()
    port.name = name
    port.dtype = dtype
    return port


def _make_entry(
    name: str,
    category: str = "processing",
    description: str = "Тестовый плагин",
    inputs: list | None = None,
    outputs: list | None = None,
) -> MagicMock:
    """Создать mock-объект PluginEntry.

    Args:
        name:        Имя плагина.
        category:    Категория (source / processing / output).
        description: Описание плагина.
        inputs:      Входные порты (list[Port]).
        outputs:     Выходные порты (list[Port]).

    Returns:
        MagicMock, имитирующий PluginEntry.
    """
    entry = MagicMock()
    entry.name = name
    entry.category = category
    entry.description = description
    entry.inputs = inputs or []
    entry.outputs = outputs or []
    entry.class_path = f"fake.module.{name}Plugin"
    return entry


def _make_fake_registry(
    entries: list | None = None,
    filter_side_effect=None,
) -> MagicMock:
    """Создать mock PluginRegistry с заданными данными.

    Args:
        entries:            Список PluginEntry для list().
        filter_side_effect: Callable для filter().

    Returns:
        MagicMock объект, имитирующий PluginRegistry.
    """
    registry = MagicMock()
    registry.list.return_value = list(entries or [])
    if filter_side_effect is not None:
        registry.filter.side_effect = filter_side_effect
    else:
        registry.filter.return_value = []
    return registry


# Набор тестовых плагинов
_FAKE_ENTRIES: list = [
    _make_entry(
        "color_mask",
        category="processing",
        description="Цветовая маска",
        inputs=[_make_port("frame", "image/bgr")],
        outputs=[_make_port("mask", "image/gray")],
    ),
    _make_entry(
        "camera_source",
        category="source",
        description="Источник камеры",
        inputs=[],
        outputs=[_make_port("frame", "image/bgr")],
    ),
    _make_entry(
        "stats_output",
        category="output",
        description="Вывод статистики",
        inputs=[_make_port("stats", "dict")],
        outputs=[],
    ),
]


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestPluginCatalogWidgetShowsAllPlugins:
    """Проверка: виджет показывает все плагины из реестра."""

    def test_shows_all_plugins(self, qapp):
        """Количество items в списке == количество плагинов в реестре."""
        registry = _make_fake_registry(entries=_FAKE_ENTRIES)

        with _RegistryPatch(registry):
            widget = PluginCatalogWidget()

        # По умолчанию загружены все плагины (3 штуки)
        assert widget._list_widget.count() == len(_FAKE_ENTRIES)
        widget.close()


class TestPluginCatalogFilterByCategory:
    """Проверка: фильтрация по категории работает корректно."""

    def test_filter_by_category(self, qapp):
        """После фильтра по 'processing' остаётся только 1 плагин."""
        registry = _make_fake_registry(
            entries=_FAKE_ENTRIES,
            filter_side_effect=lambda cat: [
                e for e in _FAKE_ENTRIES if e.category == cat
            ],
        )

        with _RegistryPatch(registry):
            widget = PluginCatalogWidget()
            # Вызываем refresh с фильтром по категории напрямую
            widget.refresh("processing")

        assert widget._list_widget.count() == 1
        assert widget._list_widget.item(0).text() == "color_mask"
        widget.close()


class TestPluginCatalogEmptyRegistry:
    """Проверка: пустой реестр → заглушка 'Нет доступных плагинов'."""

    def test_empty_registry(self, qapp):
        """При пустом реестре список содержит один disabled-item с текстом заглушки."""
        registry = _make_fake_registry(entries=[])

        with _RegistryPatch(registry):
            widget = PluginCatalogWidget()

        assert widget._list_widget.count() == 1
        item = widget._list_widget.item(0)
        assert item.text() == "Нет доступных плагинов"
        # Заглушка должна быть недоступна для выбора
        assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
        widget.close()


class TestPluginCatalogPluginSelectedSignal:
    """Проверка: двойной клик эмитит сигнал plugin_selected."""

    def test_plugin_selected_signal(self, qapp):
        """Двойной клик по item эмитирует plugin_selected с именем плагина."""
        registry = _make_fake_registry(entries=_FAKE_ENTRIES)

        with _RegistryPatch(registry):
            widget = PluginCatalogWidget()

        received_names: list[str] = []
        widget.plugin_selected.connect(received_names.append)

        # Эмулируем двойной клик по первому item
        first_item = widget._list_widget.item(0)
        widget._list_widget.itemDoubleClicked.emit(first_item)

        assert len(received_names) == 1
        assert received_names[0] == _FAKE_ENTRIES[0].name
        widget.close()


class TestPluginCatalogPluginActivatedSignal:
    """Проверка: кнопка 'Добавить' эмитит plugin_activated с нужным dict."""

    def test_plugin_activated_signal(self, qapp):
        """Нажатие 'Добавить' при выбранном плагине эмитирует plugin_activated."""
        registry = _make_fake_registry(entries=_FAKE_ENTRIES)

        with _RegistryPatch(registry):
            widget = PluginCatalogWidget()

        received_payloads: list[dict] = []
        widget.plugin_activated.connect(received_payloads.append)

        # Выбираем первый плагин и нажимаем "Добавить"
        widget._list_widget.setCurrentRow(0)
        widget._btn_add.click()

        assert len(received_payloads) == 1
        payload = received_payloads[0]
        entry = _FAKE_ENTRIES[0]

        assert payload["plugin_name"] == entry.name
        assert payload["plugin_class"] == entry.class_path
        assert payload["category"] == entry.category
        # Проверяем наличие всех ключей
        assert set(payload.keys()) == {"plugin_class", "plugin_name", "category"}
        widget.close()
