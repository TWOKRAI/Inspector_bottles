"""Тесты для PluginConfigPanel.

Проверяют:
  - Отображение полей для известного plugin_class (CapturePluginConfig)
  - Fallback при неизвестном plugin_class (без краша)
  - clear() → пустое состояние
  - Изменение поля → сигнал config_changed

Модули загружаются через importlib.util напрямую — минуя circular imports
в tabs_setting/__init__.py пакетной иерархии.

Тесты работают без pytest-qt: QApplication создаётся вручную через фикстуру.

Запуск:
    python -m pytest multiprocess_prototype/tests/unit/test_plugin_config_panel.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QSpinBox


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
# Загрузка модулей напрямую (обход circular imports)
# ---------------------------------------------------------------------------

def _load_module_direct(module_name: str, file_path: Path):
    """Загрузить Python-модуль напрямую по файловому пути.

    Обходит цепочку circular imports, которая возникает при стандартном
    импорте через пакетный __init__.py.

    Args:
        module_name: Уникальное имя для регистрации в sys.modules.
        file_path:   Абсолютный путь к .py файлу.

    Returns:
        Загруженный модуль.
    """
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Базовая директория проекта (Inspector_bottles/)
_BASE = Path(__file__).resolve().parents[3]

# 1. Загружаем ParamsForm напрямую (зависимость PluginConfigPanel)
_params_form_path = (
    _BASE / "multiprocess_prototype" / "frontend" / "widgets"
    / "base" / "editor" / "params_form.py"
)
_params_form_module = _load_module_direct("_params_form_direct", _params_form_path)

# 2. Регистрируем ParamsForm под стандартным именем пакета,
#    чтобы PluginConfigPanel нашёл его при from ... import ParamsForm
_PARAMS_FORM_PKG = "multiprocess_prototype.frontend.widgets.base.editor.params_form"
if _PARAMS_FORM_PKG not in sys.modules:
    sys.modules[_PARAMS_FORM_PKG] = _params_form_module

# 3. Загружаем PluginConfigPanel напрямую
_panel_path = (
    _BASE / "multiprocess_prototype" / "frontend" / "widgets"
    / "tabs_setting" / "processes_tab" / "plugin_config_panel.py"
)
_panel_module = _load_module_direct("_plugin_config_panel_direct", _panel_path)

PluginConfigPanel = _panel_module.PluginConfigPanel


# ---------------------------------------------------------------------------
# Фикстура panel
# ---------------------------------------------------------------------------

@pytest.fixture
def panel(qapp):
    """Создать PluginConfigPanel для каждого теста."""
    # Очистить кэш config-классов перед каждым тестом
    PluginConfigPanel._config_cache.clear()

    widget = PluginConfigPanel()
    yield widget
    widget.deleteLater()


# ---------------------------------------------------------------------------
# Словари конфигов плагинов для тестов
# ---------------------------------------------------------------------------

_CAPTURE_DICT: dict = {
    "plugin_class": "multiprocess_prototype.backend.plugins.capture.plugin.CapturePlugin",
    "plugin_name": "capture",
    "category": "source",
    "camera_id": 0,
    "device_id": 0,
    "fps": 25,
    "resolution_width": 640,
    "resolution_height": 480,
    "ring_buffer_size": 3,
}

_COLOR_MASK_DICT: dict = {
    "plugin_class": "multiprocess_prototype.backend.plugins.color_mask.plugin.ColorMaskPlugin",
    "plugin_name": "color_mask",
    "category": "processing",
    "camera_id": 0,
    "h_min": 0,
    "h_max": 180,
    "s_min": 50,
    "s_max": 255,
    "v_min": 50,
    "v_max": 255,
    "resolution_width": 640,
    "resolution_height": 480,
}

_UNKNOWN_DICT: dict = {
    "plugin_class": "nonexistent.module.SomePlugin",
    "plugin_name": "unknown",
    "category": "source",
    "some_param": 42,
}


# ---------------------------------------------------------------------------
# test_show_plugin_with_known_config
# ---------------------------------------------------------------------------

class TestShowPluginWithKnownConfig:
    """Тесты отображения полей для известного plugin_class."""

    def test_capture_config_shows_specific_fields(self, panel):
        """CapturePluginConfig: форма показывает plugin-specific поля."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        form = panel._form
        assert "fps" in form._field_widgets, "Поле fps должно быть в форме"
        assert "resolution_width" in form._field_widgets, "Поле resolution_width должно быть в форме"
        assert "resolution_height" in form._field_widgets, "Поле resolution_height должно быть в форме"
        assert "ring_buffer_size" in form._field_widgets, "Поле ring_buffer_size должно быть в форме"

    def test_capture_system_fields_not_shown(self, panel):
        """Системные поля (plugin_class, plugin_name, category) не попадают в форму."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        form = panel._form
        assert "plugin_class" not in form._field_widgets, "plugin_class не должен быть в форме"
        assert "plugin_name" not in form._field_widgets, "plugin_name не должен быть в форме"
        assert "category" not in form._field_widgets, "category не должен быть в форме"

    def test_capture_field_values_loaded(self, panel):
        """Значения полей соответствуют переданному plugin_dict."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        form = panel._form
        fps_widget = form._field_widgets.get("fps")
        assert fps_widget is not None, "fps виджет должен существовать"
        assert isinstance(fps_widget, QSpinBox), "fps должен быть QSpinBox"
        assert fps_widget.value() == 25, f"fps должен быть 25, получен {fps_widget.value()}"

    def test_color_mask_config_shows_hsv_fields(self, panel):
        """ColorMaskPluginConfig: форма показывает HSV-поля."""
        panel.show_plugin("proc_2", 1, _COLOR_MASK_DICT)

        form = panel._form
        for field in ("h_min", "h_max", "s_min", "s_max", "v_min", "v_max"):
            assert field in form._field_widgets, f"HSV поле {field} должно быть в форме"

    def test_scroll_visible_after_show_plugin(self, panel):
        """После show_plugin scroll area не скрыта, placeholder скрыт."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        assert not panel._scroll.isHidden(), "Scroll area не должна быть скрыта"
        assert panel._placeholder.isHidden(), "Placeholder должен быть скрыт"

    def test_header_shows_plugin_name(self, panel):
        """Заголовок показывает имя плагина."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        assert panel._header.text() == "capture", (
            f"Заголовок должен быть 'capture', получен '{panel._header.text()}'"
        )

    def test_config_class_found(self, panel):
        """Config-класс найден для известного пути."""
        from multiprocess_prototype.backend.plugins.capture.config import CapturePluginConfig

        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)
        assert panel._config_class is CapturePluginConfig, (
            f"Ожидался CapturePluginConfig, получен {panel._config_class}"
        )


# ---------------------------------------------------------------------------
# test_show_plugin_unknown_config
# ---------------------------------------------------------------------------

class TestShowPluginUnknownConfig:
    """Тесты fallback при неизвестном plugin_class."""

    def test_no_crash_on_unknown_plugin(self, panel):
        """Неизвестный plugin_class не вызывает исключение."""
        # Не должно быть исключений
        panel.show_plugin("proc_x", 0, _UNKNOWN_DICT)

    def test_config_class_is_none_for_unknown(self, panel):
        """При неизвестном пути config_class равен None."""
        panel.show_plugin("proc_x", 0, _UNKNOWN_DICT)
        assert panel._config_class is None, (
            f"Для неизвестного плагина config_class должен быть None, "
            f"получен {panel._config_class}"
        )

    def test_scroll_visible_after_unknown_plugin(self, panel):
        """Scroll area не скрыта даже при fallback (форма показывает что есть)."""
        panel.show_plugin("proc_x", 0, _UNKNOWN_DICT)
        assert not panel._scroll.isHidden(), "Scroll area не должна быть скрыта после show_plugin"

    def test_unknown_plugin_config_cache_has_none(self, panel):
        """Кэш хранит None для неизвестного plugin_class."""
        panel.show_plugin("proc_x", 0, _UNKNOWN_DICT)
        plugin_class_path = _UNKNOWN_DICT["plugin_class"]
        assert plugin_class_path in PluginConfigPanel._config_cache, (
            "Путь должен попасть в кэш"
        )
        assert PluginConfigPanel._config_cache[plugin_class_path] is None, (
            "Кэш должен хранить None для несуществующего модуля"
        )


# ---------------------------------------------------------------------------
# test_clear
# ---------------------------------------------------------------------------

class TestClear:
    """Тесты метода clear()."""

    def test_clear_shows_placeholder(self, panel):
        """После clear() placeholder не скрыт, scroll скрыт."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)
        panel.clear()

        assert not panel._placeholder.isHidden(), "Placeholder не должен быть скрыт после clear()"
        assert panel._scroll.isHidden(), "Scroll area должна быть скрыта после clear()"

    def test_clear_resets_header(self, panel):
        """После clear() заголовок пустой."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)
        panel.clear()

        assert panel._header.text() == "", (
            f"Заголовок должен быть пустым после clear(), получен '{panel._header.text()}'"
        )

    def test_clear_resets_state(self, panel):
        """После clear() внутреннее состояние сброшено."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)
        panel.clear()

        assert panel._proc_key == "", "proc_key должен быть пустым"
        assert panel._plugin_index == 0, "plugin_index должен быть 0"
        assert panel._config_class is None, "config_class должен быть None"

    def test_clear_initial_state(self, panel):
        """Сразу после создания панель уже в пустом состоянии."""
        assert not panel._placeholder.isHidden(), "Placeholder не должен быть скрыт по умолчанию"
        assert panel._scroll.isHidden(), "Scroll area должна быть скрыта по умолчанию"


# ---------------------------------------------------------------------------
# test_config_changed_signal
# ---------------------------------------------------------------------------

class TestConfigChangedSignal:
    """Тесты сигнала config_changed."""

    def test_signal_emitted_on_field_change(self, panel):
        """Изменение поля формы эмитирует config_changed."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        received: list[tuple] = []
        panel.config_changed.connect(
            lambda proc_key, plugin_index, fields: received.append(
                (proc_key, plugin_index, fields)
            )
        )

        fps_widget = panel._form._field_widgets.get("fps")
        assert fps_widget is not None, "fps виджет должен существовать"
        assert isinstance(fps_widget, QSpinBox), "fps должен быть QSpinBox"

        fps_widget.setValue(30)

        assert len(received) > 0, "Сигнал config_changed должен был эмититься"

    def test_signal_args_correct(self, panel):
        """Сигнал передаёт правильные proc_key и plugin_index."""
        panel.show_plugin("my_proc", 2, _CAPTURE_DICT)

        received: list[tuple] = []
        panel.config_changed.connect(
            lambda proc_key, plugin_index, fields: received.append(
                (proc_key, plugin_index, fields)
            )
        )

        fps_widget = panel._form._field_widgets.get("fps")
        fps_widget.setValue(60)

        assert len(received) > 0, "Сигнал должен был эмититься"
        proc_key, plugin_index, _ = received[0]
        assert proc_key == "my_proc", f"proc_key должен быть 'my_proc', получен '{proc_key}'"
        assert plugin_index == 2, f"plugin_index должен быть 2, получен {plugin_index}"

    def test_signal_not_emitted_on_load(self, panel):
        """При программном заполнении через show_plugin сигнал не эмитируется."""
        received: list[tuple] = []
        panel.config_changed.connect(
            lambda proc_key, plugin_index, fields: received.append(
                (proc_key, plugin_index, fields)
            )
        )

        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        assert len(received) == 0, (
            f"Сигнал не должен эмититься при загрузке, получено {len(received)} сигналов"
        )

    def test_signal_contains_updated_field(self, panel):
        """dict в сигнале содержит обновлённое значение поля."""
        panel.show_plugin("proc_1", 0, _CAPTURE_DICT)

        received_fields: list[dict] = []
        panel.config_changed.connect(
            lambda _proc, _idx, fields: received_fields.append(fields)
        )

        fps_widget = panel._form._field_widgets["fps"]
        fps_widget.setValue(15)

        assert len(received_fields) > 0, "Сигнал должен был эмититься"
        assert received_fields[-1].get("fps") == 15, (
            f"dict должен содержать fps=15, получено {received_fields[-1].get('fps')}"
        )
