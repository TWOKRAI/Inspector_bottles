"""Тесты Фазы 5 конструктора — PluginManagerModel, PluginManagerPresenter,
PluginCatalogTable, PluginDetailPanel.

Разделены на:
1. PluginManagerModel — логика данных, фильтрация, enable/disable
2. PluginManagerPresenter — MVP-логика без Qt
3. PluginCatalogTable — Qt-таблица (требует pytest-qt)
4. PluginDetailPanel — Qt-панель деталей (требует pytest-qt)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub-модули для предотвращения circular import
#
# Цепочка проблемных импортов (аналогично test_constructor_phase3.py):
#   tabs_setting/__init__ → sources_tab → base/__init__ → recipe_panel_base
#     → recipes.settings_recipe_widget/__init__ → panel_widget → base.recipe_panel_base
#
# Решение: stub листовые модули до первого импорта тестируемого кода.
# ---------------------------------------------------------------------------
_STUB_MODULES = [
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.camera_panel",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_settings_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.display_tab",
    "multiprocess_prototype.frontend.widgets.base.recipe_panel_base",
    "multiprocess_prototype.frontend.widgets.base.navigation_panel_base",
    "multiprocess_prototype.frontend.widgets.base.cards_field_factory",
    "multiprocess_prototype.frontend.coordinators",
    "multiprocess_prototype.frontend.touch_keyboard_bind",
    "multiprocess_prototype.frontend.widgets.recipes",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget.panel_widget",
    "multiprocess_prototype.frontend.widgets.recipes.settings_recipe_widget.schemas",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget.auto_save",
    "multiprocess_prototype.frontend.widgets.recipes.recipes_widget.slot_combo_model",
]
for _mod in _STUB_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# ---------------------------------------------------------------------------
# Фикстура: изолированный PluginRegistry
# ---------------------------------------------------------------------------
# PluginRegistry — глобальный синглтон в модуле. Чтобы тесты не влияли друг
# на друга, используем фикстуру clean_registry: сохраняем и восстанавливаем
# внутренний словарь.


@pytest.fixture()
def clean_registry():
    """Очищает PluginRegistry до и после каждого теста."""
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    saved = dict(PluginRegistry._plugins)
    PluginRegistry.clear()
    yield PluginRegistry
    PluginRegistry._plugins.clear()
    PluginRegistry._plugins.update(saved)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики фейковых записей
# ---------------------------------------------------------------------------


def _make_fake_class(name: str, inputs=(), outputs=()):
    """Создать фейковый класс плагина с нужными портами."""

    class FakePort:
        def __init__(self, port_name: str):
            self.name = port_name
            self.dtype = "image/bgr"
            self.shape = "(H, W, 3)"
            self.optional = False
            self.description = ""

    fake_ports_in = [FakePort(f"in_{i}") for i in range(inputs)]
    fake_ports_out = [FakePort(f"out_{i}") for i in range(outputs)]

    FakeClass = type(name, (), {
        "inputs": fake_ports_in,
        "outputs": fake_ports_out,
    })
    FakeClass.__module__ = "tests.fake"
    FakeClass.__qualname__ = name
    return FakeClass


def _register_fake(registry, name: str, category: str, description: str = "",
                   inputs: int = 0, outputs: int = 0):
    """Зарегистрировать фейковый плагин в переданном registry."""
    fake_cls = _make_fake_class(name, inputs=inputs, outputs=outputs)
    registry.register(
        name=name,
        plugin_class=fake_cls,
        category=category,
        description=description,
    )
    return fake_cls


# =====================================================================
# 1. PluginManagerModel
# =====================================================================


class TestPluginManagerModel:
    """Тесты модели данных вкладки управления плагинами."""

    def test_get_all_plugins_empty_registry(self, clean_registry, qapp):
        """Пустой PluginRegistry → get_all_plugins() возвращает пустой список."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        model = PluginManagerModel()
        result = model.get_all_plugins()

        assert result == []

    def test_get_all_plugins_with_entries(self, clean_registry, qapp):
        """PluginRegistry с 3 плагинами → get_all_plugins() возвращает 3 dict с нужными полями."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "capture", "source", "Захват кадра", inputs=0, outputs=1)
        _register_fake(clean_registry, "color_mask", "processing", "Цветовая маска", inputs=1, outputs=1)
        _register_fake(clean_registry, "writer", "output", "Запись", inputs=1, outputs=0)

        model = PluginManagerModel()
        result = model.get_all_plugins()

        assert len(result) == 3
        # Проверяем набор обязательных полей
        required_fields = {"name", "category", "description", "class_path",
                           "inputs", "outputs", "enabled", "instances", "metrics"}
        for plugin_dict in result:
            assert required_fields.issubset(plugin_dict.keys()), (
                f"Не хватает полей: {required_fields - plugin_dict.keys()}"
            )

    def test_get_all_plugins_enabled_by_default(self, clean_registry, qapp):
        """Все новые плагины по умолчанию имеют enabled=True."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "plug_a", "source")
        model = PluginManagerModel()
        result = model.get_all_plugins()

        assert result[0]["enabled"] is True

    def test_get_plugin_detail_returns_ports(self, clean_registry, qapp):
        """get_plugin_detail() возвращает dict с полями input_ports и output_ports."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "color_mask", "processing", inputs=1, outputs=1)
        model = PluginManagerModel()
        detail = model.get_plugin_detail("color_mask")

        assert detail is not None
        assert "input_ports" in detail
        assert "output_ports" in detail
        assert len(detail["input_ports"]) == 1
        assert len(detail["output_ports"]) == 1

    def test_get_plugin_detail_port_fields(self, clean_registry, qapp):
        """Каждый элемент input_ports/output_ports содержит обязательные поля."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "color_mask", "processing", inputs=1, outputs=0)
        model = PluginManagerModel()
        detail = model.get_plugin_detail("color_mask")

        port = detail["input_ports"][0]
        assert "name" in port
        assert "dtype" in port
        assert "shape" in port
        assert "optional" in port
        assert "description" in port

    def test_get_plugin_detail_not_found(self, clean_registry, qapp):
        """get_plugin_detail() для несуществующего плагина → None."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        model = PluginManagerModel()
        result = model.get_plugin_detail("nonexistent_plugin")

        assert result is None

    def test_filter_by_category(self, clean_registry, qapp):
        """filter_plugins(category="source") возвращает только source-плагины."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "capture", "source")
        _register_fake(clean_registry, "color_mask", "processing")
        _register_fake(clean_registry, "writer", "output")

        model = PluginManagerModel()
        result = model.filter_plugins(category="source")

        assert len(result) == 1
        assert result[0]["name"] == "capture"
        assert result[0]["category"] == "source"

    def test_filter_by_search_name(self, clean_registry, qapp):
        """filter_plugins(search="mask") возвращает только плагины с "mask" в имени."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "color_mask", "processing", "Цветовая маска")
        _register_fake(clean_registry, "capture", "source", "Захват кадра")

        model = PluginManagerModel()
        result = model.filter_plugins(search="mask")

        assert len(result) == 1
        assert result[0]["name"] == "color_mask"

    def test_filter_by_search_description(self, clean_registry, qapp):
        """filter_plugins(search=...) ищет в description (case-insensitive)."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "plug_a", "processing", "Детектор границ Edge")
        _register_fake(clean_registry, "plug_b", "processing", "Цветовой фильтр")

        model = PluginManagerModel()
        result = model.filter_plugins(search="EDGE")

        assert len(result) == 1
        assert result[0]["name"] == "plug_a"

    def test_filter_no_category_no_search_returns_all(self, clean_registry, qapp):
        """filter_plugins() без аргументов возвращает все плагины."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "plug_a", "source")
        _register_fake(clean_registry, "plug_b", "processing")

        model = PluginManagerModel()
        result = model.filter_plugins()

        assert len(result) == 2

    def test_set_enabled_false(self, clean_registry, qapp):
        """set_enabled("plug", False) → enabled=False в get_all_plugins()."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "plug_a", "source")
        model = PluginManagerModel()
        model.set_enabled("plug_a", False)

        result = model.get_all_plugins()
        assert result[0]["enabled"] is False

    def test_set_enabled_true_restores(self, clean_registry, qapp):
        """set_enabled("plug", True) после False → enabled=True."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "plug_a", "source")
        model = PluginManagerModel()

        # Сначала отключаем
        model.set_enabled("plug_a", False)
        assert model.get_all_plugins()[0]["enabled"] is False

        # Потом включаем обратно
        model.set_enabled("plug_a", True)
        assert model.get_all_plugins()[0]["enabled"] is True

    def test_set_enabled_emits_signal(self, clean_registry, qapp, qtbot):
        """set_enabled() эмитирует сигнал plugins_updated."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        _register_fake(clean_registry, "plug_a", "source")
        model = PluginManagerModel()

        with qtbot.waitSignal(model.plugins_updated, timeout=1000):
            model.set_enabled("plug_a", False)

    def test_reload_without_manager(self, clean_registry, qapp):
        """reload_plugins() без PluginManager → возвращает None без ошибки."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        model = PluginManagerModel(plugin_manager=None)
        result = model.reload_plugins()

        assert result is None

    def test_reload_with_manager(self, clean_registry, qapp):
        """reload_plugins() с mock PluginManager → делегирует вызов reload()."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        mock_manager = MagicMock()
        fake_result = MagicMock()
        mock_manager.reload.return_value = fake_result

        model = PluginManagerModel(plugin_manager=mock_manager)
        result = model.reload_plugins()

        mock_manager.reload.assert_called_once()
        assert result is fake_result

    def test_reload_emits_signal(self, clean_registry, qapp, qtbot):
        """reload_plugins() всегда эмитирует plugins_updated."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        model = PluginManagerModel(plugin_manager=None)

        with qtbot.waitSignal(model.plugins_updated, timeout=1000):
            model.reload_plugins()

    def test_get_default_config_empty_by_default(self, clean_registry, qapp):
        """get_default_config() для нового плагина → пустой dict."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        model = PluginManagerModel()
        result = model.get_default_config("any_plugin")

        assert result == {}

    def test_set_default_config_roundtrip(self, clean_registry, qapp):
        """set_default_config + get_default_config → round-trip без потерь."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.models.plugin_manager_model import (
            PluginManagerModel,
        )

        model = PluginManagerModel()
        config = {"threshold": 0.5, "kernel_size": 3}
        model.set_default_config("color_mask", config)

        result = model.get_default_config("color_mask")
        assert result == config


# =====================================================================
# 2. PluginManagerPresenter (MVP — без Qt)
# =====================================================================


class TestPluginManagerPresenter:
    """Тесты presenter-логики вкладки плагинов.

    Используются только MagicMock — без Qt, без реального PluginRegistry.
    """

    @pytest.fixture()
    def mock_view(self):
        """Фейковая реализация PluginManagerViewProtocol."""
        view = MagicMock()
        view.get_current_filter.return_value = (None, "")
        return view

    @pytest.fixture()
    def mock_model(self):
        """Фейковая модель данных плагинов."""
        model = MagicMock()
        model.filter_plugins.return_value = [
            {"name": "plug_a", "category": "source", "description": "", "enabled": True,
             "inputs": 0, "outputs": 1, "class_path": "tests.fake.PlugA", "instances": 0, "metrics": None},
        ]
        model.get_plugin_detail.return_value = {
            "name": "plug_a", "category": "source", "description": "",
            "class_path": "tests.fake.PlugA", "inputs": 0, "outputs": 1,
            "enabled": True, "instances": 0, "metrics": None,
            "input_ports": [], "output_ports": [],
        }
        return model

    @pytest.fixture()
    def presenter(self, mock_view, mock_model):
        """Готовый presenter с mock view и mock model."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.presenter import (
            PluginManagerPresenter,
        )

        return PluginManagerPresenter(view=mock_view, model=mock_model)

    def test_on_init_calls_refresh(self, presenter, mock_view, mock_model):
        """on_init() → view.refresh_table вызван хотя бы один раз."""
        presenter.on_init()

        mock_view.refresh_table.assert_called()

    def test_on_init_reads_filter(self, presenter, mock_view):
        """on_init() → view.get_current_filter вызван для получения фильтра."""
        presenter.on_init()

        mock_view.get_current_filter.assert_called()

    def test_on_init_calls_filter_plugins(self, presenter, mock_model):
        """on_init() → model.filter_plugins вызван с параметрами из фильтра."""
        presenter.on_init()

        mock_model.filter_plugins.assert_called()

    def test_on_plugin_selected_shows_detail(self, presenter, mock_view, mock_model):
        """on_plugin_selected("plug_a") → model.get_plugin_detail + view.show_plugin_detail."""
        presenter.on_plugin_selected("plug_a")

        mock_model.get_plugin_detail.assert_called_once_with("plug_a")
        mock_view.show_plugin_detail.assert_called_once()

    def test_on_plugin_selected_not_found(self, presenter, mock_view, mock_model):
        """on_plugin_selected с несуществующим именем → view.clear_detail()."""
        mock_model.get_plugin_detail.return_value = None

        presenter.on_plugin_selected("nonexistent")

        mock_view.clear_detail.assert_called_once()
        mock_view.show_plugin_detail.assert_not_called()

    def test_on_plugin_enabled_changed_calls_set_enabled(self, presenter, mock_model):
        """on_plugin_enabled_changed() → model.set_enabled вызван с корректными аргументами."""
        presenter.on_plugin_enabled_changed("plug_a", False)

        mock_model.set_enabled.assert_called_once_with("plug_a", False)

    def test_on_plugin_enabled_changed_refreshes_table(self, presenter, mock_view):
        """on_plugin_enabled_changed() → view.refresh_table вызван после изменения."""
        presenter.on_plugin_enabled_changed("plug_a", False)

        mock_view.refresh_table.assert_called()

    def test_on_reload_calls_reload_plugins(self, presenter, mock_model):
        """on_reload_requested() → model.reload_plugins() вызван."""
        mock_model.reload_plugins.return_value = None

        presenter.on_reload_requested()

        mock_model.reload_plugins.assert_called_once()

    def test_on_reload_without_manager_sets_status(self, presenter, mock_view, mock_model):
        """on_reload_requested() без PluginManager → view.set_status_text с сообщением."""
        mock_model.reload_plugins.return_value = None

        presenter.on_reload_requested()

        # Должен быть вызов set_status_text хотя бы один раз
        mock_view.set_status_text.assert_called()
        # Финальный вызов — либо "PluginManager не подключён", либо счётчик плагинов
        all_calls = [str(c) for c in mock_view.set_status_text.call_args_list]
        assert any("PluginManager" in c or "Плагинов" in c for c in all_calls)

    def test_on_reload_with_discovery_result_sets_status(self, presenter, mock_view, mock_model):
        """on_reload_requested() с PluginDiscoveryResult → view.set_status_text с деталями."""
        # Фейковый PluginDiscoveryResult
        fake_result = MagicMock()
        fake_result.loaded = ["plug_a", "plug_b"]
        fake_result.failed = []
        fake_result.new_plugins = ["plug_b"]
        mock_model.reload_plugins.return_value = fake_result

        presenter.on_reload_requested()

        # Должен быть вызов с текстом о загруженных плагинах
        status_calls = [str(c) for c in mock_view.set_status_text.call_args_list]
        assert any("Загружено" in c for c in status_calls)

    def test_on_filter_changed_refreshes(self, presenter, mock_view, mock_model):
        """on_filter_changed() → view.get_current_filter + model.filter_plugins + view.refresh_table."""
        mock_view.get_current_filter.return_value = ("processing", "mask")
        mock_model.filter_plugins.return_value = []

        presenter.on_filter_changed()

        mock_view.get_current_filter.assert_called()
        mock_model.filter_plugins.assert_called_with("processing", "mask")
        mock_view.refresh_table.assert_called()

    def test_on_default_config_changed_saves_config(self, presenter, mock_model):
        """on_default_config_changed() → model.set_default_config вызван с нужными аргументами."""
        config = {"threshold": 0.7}

        presenter.on_default_config_changed("color_mask", config)

        mock_model.set_default_config.assert_called_once_with("color_mask", config)

    def test_on_default_config_changed_sets_status(self, presenter, mock_view):
        """on_default_config_changed() → view.set_status_text с именем плагина."""
        presenter.on_default_config_changed("color_mask", {})

        mock_view.set_status_text.assert_called()
        # Статусное сообщение содержит имя плагина
        call_args = str(mock_view.set_status_text.call_args_list)
        assert "color_mask" in call_args

    def test_on_model_updated_refreshes(self, presenter, mock_view):
        """on_model_updated() → view.refresh_table вызван."""
        presenter.on_model_updated()

        mock_view.refresh_table.assert_called()

    def test_refresh_passes_filter_to_model(self, presenter, mock_view, mock_model):
        """_refresh читает фильтр из view и передаёт его в model.filter_plugins."""
        mock_view.get_current_filter.return_value = ("output", "writer")

        presenter.on_filter_changed()

        mock_model.filter_plugins.assert_called_with("output", "writer")

    def test_refresh_sets_status_with_count(self, presenter, mock_view, mock_model):
        """_refresh устанавливает статус с количеством плагинов."""
        mock_model.filter_plugins.return_value = [
            {"name": "a"}, {"name": "b"}, {"name": "c"}
        ]

        presenter.on_filter_changed()

        # Статус должен содержать число 3
        call_args = str(mock_view.set_status_text.call_args_list)
        assert "3" in call_args


# =====================================================================
# 3. PluginCatalogTable (Qt-тесты, требуют pytest-qt)
# =====================================================================


class TestPluginCatalogTable:
    """Тесты Qt-таблицы каталога плагинов."""

    def test_set_data_correct_row_count(self, qapp):
        """set_data([3 плагина]) → 3 строки в таблице."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable,
        )

        table = PluginCatalogTable()
        plugins = [
            {"name": "plug_a", "category": "source", "description": "a",
             "inputs": 0, "outputs": 1, "enabled": True},
            {"name": "plug_b", "category": "processing", "description": "b",
             "inputs": 1, "outputs": 1, "enabled": True},
            {"name": "plug_c", "category": "output", "description": "c",
             "inputs": 1, "outputs": 0, "enabled": False},
        ]

        table.set_data(plugins)

        assert table._table.rowCount() == 3

    def test_set_data_empty_list(self, qapp):
        """set_data([]) → 0 строк в таблице."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable,
        )

        table = PluginCatalogTable()
        table.set_data([])

        assert table._table.rowCount() == 0

    def test_set_data_row_names_match(self, qapp):
        """set_data → _row_plugin_names соответствует порядку плагинов."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable,
        )

        table = PluginCatalogTable()
        plugins = [
            {"name": "first", "category": "source", "description": "",
             "inputs": 0, "outputs": 0, "enabled": True},
            {"name": "second", "category": "processing", "description": "",
             "inputs": 0, "outputs": 0, "enabled": True},
        ]

        table.set_data(plugins)

        assert table._row_plugin_names == ["first", "second"]

    def test_set_data_replaces_existing(self, qapp):
        """Повторный set_data заменяет предыдущие данные."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable,
        )

        table = PluginCatalogTable()
        table.set_data([
            {"name": "old", "category": "source", "description": "",
             "inputs": 0, "outputs": 0, "enabled": True},
        ])
        assert table._table.rowCount() == 1

        table.set_data([])
        assert table._table.rowCount() == 0

    def test_current_filter_default(self, qapp):
        """current_filter() по умолчанию → (None, "")."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable,
        )

        table = PluginCatalogTable()
        category, search = table.current_filter()

        assert category is None
        assert search == ""

    def test_plugin_selected_signal_on_row_click(self, qapp, qtbot):
        """Клик по строке (не чекбокс) → plugin_selected(name) эмитируется."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable, _COL_NAME,
        )

        table = PluginCatalogTable()
        table.set_data([
            {"name": "my_plugin", "category": "source", "description": "",
             "inputs": 0, "outputs": 0, "enabled": True},
        ])

        with qtbot.waitSignal(table.plugin_selected, timeout=1000) as blocker:
            table._table.cellClicked.emit(0, _COL_NAME)

        assert blocker.args[0] == "my_plugin"

    def test_reload_requested_signal_on_button(self, qapp, qtbot):
        """Нажатие кнопки 'Обновить' → reload_requested эмитируется."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_catalog_table import (
            PluginCatalogTable,
        )

        table = PluginCatalogTable()

        with qtbot.waitSignal(table.reload_requested, timeout=1000):
            table._reload_btn.click()


# =====================================================================
# 4. PluginDetailPanel (Qt-тесты, требуют pytest-qt)
# =====================================================================


class TestPluginDetailPanel:
    """Тесты панели детальной информации о плагине."""

    def _make_detail(self, **overrides) -> dict:
        """Собрать типичный dict детальных данных плагина."""
        base = {
            "name": "color_mask",
            "category": "processing",
            "class_path": "tests.fake.ColorMaskPlugin",
            "description": "Цветовая маска",
            "enabled": True,
            "inputs": 1,
            "outputs": 1,
            "instances": 0,
            "metrics": None,
            "input_ports": [
                {"name": "frame", "dtype": "image/bgr", "shape": "(H,W,3)",
                 "optional": False, "description": ""},
            ],
            "output_ports": [
                {"name": "mask", "dtype": "image/gray", "shape": "(H,W,1)",
                 "optional": False, "description": ""},
            ],
        }
        base.update(overrides)
        return base

    def test_show_plugin_fills_name(self, qapp):
        """show_plugin(dict) → _lbl_name заполнен именем."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())

        assert panel._lbl_name.text() == "color_mask"

    def test_show_plugin_fills_category(self, qapp):
        """show_plugin(dict) → _lbl_category заполнен категорией."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())

        assert panel._lbl_category.text() == "processing"

    def test_show_plugin_fills_class_path(self, qapp):
        """show_plugin(dict) → _lbl_class_path заполнен путём к классу."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())

        assert panel._lbl_class_path.text() == "tests.fake.ColorMaskPlugin"

    def test_show_plugin_enabled_text(self, qapp):
        """show_plugin с enabled=True → _lbl_enabled показывает 'включён'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail(enabled=True))

        assert "включ" in panel._lbl_enabled.text().lower()

    def test_show_plugin_disabled_text(self, qapp):
        """show_plugin с enabled=False → _lbl_enabled показывает 'выключен'."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail(enabled=False))

        assert "выключ" in panel._lbl_enabled.text().lower()

    def test_show_plugin_sets_current_name(self, qapp):
        """show_plugin(dict) → _current_plugin_name установлен."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())

        assert panel._current_plugin_name == "color_mask"

    def test_clear_resets_name_label(self, qapp):
        """clear() → _lbl_name пустой."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())
        panel.clear()

        assert panel._lbl_name.text() == ""

    def test_clear_resets_current_plugin_name(self, qapp):
        """clear() → _current_plugin_name = None."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())
        panel.clear()

        assert panel._current_plugin_name is None

    def test_clear_resets_category_label(self, qapp):
        """clear() → _lbl_category пустой."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())
        panel.clear()

        assert panel._lbl_category.text() == ""

    def test_default_config_changed_signal_on_save(self, qapp, qtbot):
        """Нажатие 'Сохранить дефолты' с корректным JSON → default_config_changed эмитируется."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())
        panel._config_editor.setPlainText('{"threshold": 0.5}')

        with qtbot.waitSignal(panel.default_config_changed, timeout=1000) as blocker:
            panel._save_config_btn.click()

        plugin_name, config = blocker.args
        assert plugin_name == "color_mask"
        assert config == {"threshold": 0.5}

    def test_no_signal_on_invalid_json(self, qapp, qtbot):
        """Нажатие 'Сохранить дефолты' с невалидным JSON → сигнал НЕ эмитируется."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        panel.show_plugin(self._make_detail())
        panel._config_editor.setPlainText("{invalid json}")

        signals_received = []
        panel.default_config_changed.connect(lambda n, c: signals_received.append((n, c)))

        panel._save_config_btn.click()

        assert len(signals_received) == 0

    def test_no_signal_when_no_plugin_selected(self, qapp, qtbot):
        """Нажатие 'Сохранить дефолты' без выбранного плагина → сигнал НЕ эмитируется."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.plugin_detail_panel import (
            PluginDetailPanel,
        )

        panel = PluginDetailPanel()
        # Не вызываем show_plugin — _current_plugin_name = None
        panel._config_editor.setPlainText('{"k": "v"}')

        signals_received = []
        panel.default_config_changed.connect(lambda n, c: signals_received.append((n, c)))

        panel._save_config_btn.click()

        assert len(signals_received) == 0
