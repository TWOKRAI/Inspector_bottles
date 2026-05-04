"""Тесты Фазы 3 конструктора — ShmConfigPanel, WireInspectorPanel,
ProcessPluginPanel, интеграция ConstructorTabWidget.

Разделены на:
1. ShmConfigPanel — форма SHM-конфига wire-канала
2. WireInspectorPanel — инспектор wire-соединения
3. ProcessPluginPanel — панель плагинов процесса
4. Интеграция widget.py (ConstructorTabWidget) — требует NodeGraphQt
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Предотвращаем circular import из tabs_setting/__init__.py и base/__init__.py.
#
# Цепочка проблемных импортов:
#   panels/__init__ → process_plugin_panel → plugin_config_panel
#     → base.editor.params_form → (base/__init__.py выполняется)
#     → base/__init__.py импортирует recipe_panel_base
#     → recipe_panel_base → recipes.settings_recipe_widget.schemas
#     → recipes.settings_recipe_widget/__init__.py → panel_widget
#     → panel_widget → base.recipe_panel_base (circular!)
#
# Решение: stub только leaf-модули, которые вызывают circular,
# НЕ трогая пакет base целиком (иначе base.editor станет недоступным).
_STUB_MODULES = [
    # tabs_setting circular stubs (паттерн из test_constructor_phase2.py)
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.camera_panel",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_settings_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.display_tab",
    # base leaf-stubs — только проблемные, пакет base остаётся реальным
    "multiprocess_prototype.frontend.widgets.base.recipe_panel_base",
    "multiprocess_prototype.frontend.widgets.base.navigation_panel_base",
    "multiprocess_prototype.frontend.widgets.base.cards_field_factory",
    # coordinators и touch_keyboard (нужны recipe_panel_base)
    "multiprocess_prototype.frontend.coordinators",
    "multiprocess_prototype.frontend.touch_keyboard_bind",
    # recipes stubs
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
# Тестовые данные
# ---------------------------------------------------------------------------

SAMPLE_PROC_DATA = {
    "name": "camera_0",
    "class_path": "test.CameraProcess",
    "priority": "normal",
    "auto_start": True,
    "sort_order": 0,
    "plugins": [
        {"plugin_class": "test.CapturePlugin", "plugin_name": "capture", "category": "source"},
        {"plugin_class": "test.ResizePlugin", "plugin_name": "resize", "category": "processing"},
    ],
}

SAMPLE_WIRE_DATA = {
    "source": "camera_0.capture.frame",
    "target": "processor_0.color_mask.frame",
    "transport": "router",
    "description": "Камера → Процессор",
    "shm_config": {
        "shm_name": "cam_to_proc",
        "buffer_slots": 4,
        "owner_process": "camera_0",
        "strategy": "direct",
    },
}


# =====================================================================
# 1. ShmConfigPanel
# =====================================================================


class TestShmConfigPanel:
    """Тесты формы конфигурации SharedMemory для wire-канала."""

    def test_set_config_fills_fields(self, qapp) -> None:
        """set_config заполняет все четыре поля формы корректными значениями."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.shm_config_panel import (
            ShmConfigPanel,
        )

        panel = ShmConfigPanel()
        panel.set_config(
            {"shm_name": "test_shm", "buffer_slots": 8, "strategy": "via_pm", "owner_process": "cam_0"},
            source_proc="cam_0",
            target_proc="proc_0",
        )

        assert panel._shm_name.text() == "test_shm"
        assert panel._buffer_slots.value() == 8
        assert panel._strategy.currentText() == "via_pm"
        assert panel._owner_process.currentText() == "cam_0"

    def test_get_config_returns_dict(self, qapp) -> None:
        """get_config возвращает dict с четырьмя обязательными ключами."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.shm_config_panel import (
            ShmConfigPanel,
        )

        panel = ShmConfigPanel()
        panel.set_config(
            {"shm_name": "my_shm", "buffer_slots": 6, "strategy": "direct", "owner_process": "cam_0"},
            source_proc="cam_0",
            target_proc="proc_0",
        )

        result = panel.get_config()

        assert "shm_name" in result
        assert "buffer_slots" in result
        assert "owner_process" in result
        assert "strategy" in result
        assert result["shm_name"] == "my_shm"
        assert result["buffer_slots"] == 6
        assert result["strategy"] == "direct"

    def test_config_changed_emitted_on_user_edit(self, qapp, qtbot) -> None:
        """Изменение spinbox без blockSignals вызывает эмиссию config_changed."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.shm_config_panel import (
            ShmConfigPanel,
        )

        panel = ShmConfigPanel()
        panel.set_config(
            {"shm_name": "s", "buffer_slots": 4, "strategy": "direct", "owner_process": ""},
            source_proc="",
            target_proc="",
        )

        with qtbot.waitSignal(panel.config_changed, timeout=1000) as blocker:
            # Программно меняем значение SpinBox — сигналы НЕ заблокированы (это user edit)
            panel._buffer_slots.setValue(10)

        assert blocker.signal_triggered
        emitted_dict = blocker.args[0]
        assert emitted_dict["buffer_slots"] == 10

    def test_no_signal_on_programmatic_fill(self, qapp, qtbot) -> None:
        """set_config не эмитирует config_changed (blockSignals активен)."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.shm_config_panel import (
            ShmConfigPanel,
        )

        panel = ShmConfigPanel()
        signal_received = []
        panel.config_changed.connect(lambda d: signal_received.append(d))

        panel.set_config(
            {"shm_name": "no_signal", "buffer_slots": 16, "strategy": "via_pm", "owner_process": "cam_0"},
            source_proc="cam_0",
            target_proc="proc_0",
        )

        # Обрабатываем события Qt
        qapp.processEvents()

        assert signal_received == [], "config_changed не должен эмитироваться при set_config"

    def test_owner_process_combo_contains_source_and_target(self, qapp) -> None:
        """Combo owner_process содержит оба процесса (source и target)."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.shm_config_panel import (
            ShmConfigPanel,
        )

        panel = ShmConfigPanel()
        panel.set_config(
            {"shm_name": "", "buffer_slots": 4, "strategy": "direct", "owner_process": "cam_0"},
            source_proc="cam_0",
            target_proc="proc_0",
        )

        items = [panel._owner_process.itemText(i) for i in range(panel._owner_process.count())]
        assert "cam_0" in items
        assert "proc_0" in items


# =====================================================================
# 2. WireInspectorPanel
# =====================================================================


class TestWireInspectorPanel:
    """Тесты инспектора wire-соединения."""

    def test_show_wire_fills_all_fields(self, qapp) -> None:
        """show_wire заполняет заголовок, source, target, transport и description."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        panel.show_wire("w1", SAMPLE_WIRE_DATA)

        assert "w1" in panel._title_label.text()
        assert panel._source_label.text() == SAMPLE_WIRE_DATA["source"]
        assert panel._target_label.text() == SAMPLE_WIRE_DATA["target"]
        assert panel._transport.currentText() == SAMPLE_WIRE_DATA["transport"]
        assert panel._description.text() == SAMPLE_WIRE_DATA["description"]

    def test_wire_changed_on_transport_change(self, qapp, qtbot) -> None:
        """Изменение transport combo эмитирует wire_changed с ключом transport."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        panel.show_wire("w1", SAMPLE_WIRE_DATA)

        with qtbot.waitSignal(panel.wire_changed, timeout=1000) as blocker:
            # Переключаем transport на "direct"
            idx = panel._transport.findText("direct")
            panel._transport.setCurrentIndex(idx)

        assert blocker.signal_triggered
        wire_key, changed = blocker.args
        assert wire_key == "w1"
        assert "transport" in changed
        assert changed["transport"] == "direct"

    def test_wire_changed_on_description_change(self, qapp, qtbot) -> None:
        """Изменение description эмитирует wire_changed с ключом description."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        panel.show_wire("w1", SAMPLE_WIRE_DATA)

        with qtbot.waitSignal(panel.wire_changed, timeout=1000) as blocker:
            panel._description.setText("новое описание")

        assert blocker.signal_triggered
        wire_key, changed = blocker.args
        assert wire_key == "w1"
        assert "description" in changed
        assert changed["description"] == "новое описание"

    def test_source_target_readonly(self, qapp) -> None:
        """source и target отображаются как QLabel (не QLineEdit)."""
        from PySide6.QtWidgets import QLabel, QLineEdit

        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()

        assert isinstance(panel._source_label, QLabel), "source должен быть QLabel"
        assert isinstance(panel._target_label, QLabel), "target должен быть QLabel"
        assert not isinstance(panel._source_label, QLineEdit), "source не должен быть QLineEdit"
        assert not isinstance(panel._target_label, QLineEdit), "target не должен быть QLineEdit"

    def test_clear_resets_all(self, qapp) -> None:
        """clear() сбрасывает wire_key в None и очищает все поля."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        panel.show_wire("w1", SAMPLE_WIRE_DATA)

        panel.clear()

        assert panel.current_wire_key() is None
        assert panel._source_label.text() == ""
        assert panel._target_label.text() == ""
        assert panel._description.text() == ""

    def test_show_wire_sets_wire_key(self, qapp) -> None:
        """show_wire корректно устанавливает wire_key."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.wire_inspector import (
            WireInspectorPanel,
        )

        panel = WireInspectorPanel()
        panel.show_wire("wire_abc", SAMPLE_WIRE_DATA)

        assert panel.current_wire_key() == "wire_abc"


# =====================================================================
# 3. ProcessPluginPanel
# =====================================================================


class TestProcessPluginPanel:
    """Тесты правой панели конструктора — chain editor + catalog + config."""

    def test_show_process_shows_chain(self, qapp) -> None:
        """show_process отображает имя процесса в заголовке и передаёт ключ chain editor."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.process_plugin_panel import (
            ProcessPluginPanel,
        )

        panel = ProcessPluginPanel()
        panel.show_process("cam_0", {
            "name": "cam_0",
            "plugins": [{"plugin_class": "Foo", "plugin_name": "foo"}],
        })

        assert panel._title_label.text() == "cam_0"
        assert panel._chain_editor._proc_key == "cam_0"

    def test_process_changed_on_plugin_remove(self, qapp, qtbot) -> None:
        """Удаление плагина эмитирует process_changed с укороченным списком плагинов."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.process_plugin_panel import (
            ProcessPluginPanel,
        )

        panel = ProcessPluginPanel()
        panel.show_process("cam_0", {
            "name": "cam_0",
            "plugins": [
                {"plugin_class": "A", "plugin_name": "a"},
                {"plugin_class": "B", "plugin_name": "b"},
            ],
        })

        with qtbot.waitSignal(panel.process_changed, timeout=1000) as blocker:
            panel._chain_editor.plugin_removed.emit("cam_0", 0)

        assert blocker.signal_triggered
        proc_key, proc_data = blocker.args
        assert proc_key == "cam_0"
        assert len(proc_data["plugins"]) == 1

    def test_clear_resets_all(self, qapp) -> None:
        """clear() сбрасывает текущий proc_key в None."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.process_plugin_panel import (
            ProcessPluginPanel,
        )

        panel = ProcessPluginPanel()
        panel.show_process("cam_0", {"name": "cam_0", "plugins": []})

        panel.clear()

        assert panel.current_proc_key() is None

    def test_process_changed_on_plugin_add(self, qapp, qtbot) -> None:
        """Добавление плагина через каталог эмитирует process_changed с 2 плагинами."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.process_plugin_panel import (
            ProcessPluginPanel,
        )

        panel = ProcessPluginPanel()
        panel.show_process("cam_0", {
            "name": "cam_0",
            "plugins": [{"plugin_class": "A", "plugin_name": "a"}],
        })

        with qtbot.waitSignal(panel.process_changed, timeout=1000) as blocker:
            panel._catalog.plugin_activated.emit({"plugin_class": "Bar", "plugin_name": "bar"})

        assert blocker.signal_triggered
        proc_key, proc_data = blocker.args
        assert proc_key == "cam_0"
        assert len(proc_data["plugins"]) == 2
        plugin_names = [p["plugin_name"] for p in proc_data["plugins"]]
        assert "bar" in plugin_names

    def test_clear_title_empty(self, qapp) -> None:
        """clear() очищает заголовок панели."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.panels.process_plugin_panel import (
            ProcessPluginPanel,
        )

        panel = ProcessPluginPanel()
        panel.show_process("cam_0", {"name": "cam_0", "plugins": []})

        panel.clear()

        assert panel._title_label.text() == ""


# =====================================================================
# 4. Интеграция ConstructorTabWidget
# =====================================================================


def _make_topology_editor():
    """Создать SystemTopologyEditor с тестовыми данными."""
    from multiprocess_prototype.frontend.models.system_topology_editor import (
        SystemTopologyEditor,
    )

    data = {
        "processes": {
            "camera_0": {
                "name": "camera_0",
                "class_path": "CameraProcess",
                "priority": "high",
                "auto_start": True,
                "sort_order": 0,
                "plugins": [
                    {"plugin_class": "CapturePlugin", "plugin_name": "capture"},
                ],
            },
        },
        "workers": {},
        "cameras": {},
        "regions": {},
        "pipeline": {},
        "displays": {},
        "wires": {
            "w1": {
                "source": "camera_0.capture.frame",
                "target": "processor_0.color_mask.frame",
                "transport": "router",
                "description": "тест",
                "shm_config": {},
            },
        },
    }
    editor = SystemTopologyEditor()
    editor.load(data)
    return editor


def _nodegraphqt_available() -> bool:
    """Проверить доступность NodeGraphQt."""
    try:
        import NodeGraphQt  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _nodegraphqt_available(),
    reason="NodeGraphQt недоступен",
)
class TestConstructorTabWidgetIntegration:
    """Интеграционные тесты ConstructorTabWidget (требуют NodeGraphQt)."""

    def _make_widget(self, qapp):
        """Создать ConstructorTabWidget для тестов."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.widget import (
            ConstructorTabWidget,
        )

        editor = _make_topology_editor()
        widget = ConstructorTabWidget(topology_editor=editor)
        widget.show()
        qapp.processEvents()
        return widget, editor

    def test_stack_switches_to_process_panel_on_node_select(self, qapp) -> None:
        """_on_node_selected переключает stack на страницу ProcessPluginPanel (index=1)."""
        widget, editor = self._make_widget(qapp)

        widget._on_node_selected("camera_0")
        qapp.processEvents()

        assert widget._stack.currentIndex() == 1

    def test_stack_switches_to_wire_panel_on_wire_select(self, qapp) -> None:
        """_on_wire_selected переключает stack на страницу WireInspectorPanel (index=2)."""
        widget, editor = self._make_widget(qapp)

        widget._on_wire_selected("w1")
        qapp.processEvents()

        assert widget._stack.currentIndex() == 2

    def test_stack_returns_to_placeholder_on_clear(self, qapp) -> None:
        """_on_selection_cleared возвращает stack на placeholder (index=0)."""
        widget, editor = self._make_widget(qapp)

        # Сначала выбираем ноду
        widget._on_node_selected("camera_0")
        qapp.processEvents()
        assert widget._stack.currentIndex() == 1

        # Сбрасываем выделение
        widget._on_selection_cleared()
        qapp.processEvents()

        assert widget._stack.currentIndex() == 0

    def test_toolbar_has_blueprint_buttons(self, qapp) -> None:
        """Toolbar содержит кнопки 'Сохранить Blueprint' и 'Загрузить Blueprint'."""
        from PySide6.QtWidgets import QPushButton

        widget, _ = self._make_widget(qapp)

        button_texts = set()
        for child in widget._toolbar.findChildren(QPushButton):
            button_texts.add(child.text())

        assert "Сохранить Blueprint" in button_texts, (
            f"Кнопка 'Сохранить Blueprint' не найдена. Найдены: {button_texts}"
        )
        assert "Загрузить Blueprint" in button_texts, (
            f"Кнопка 'Загрузить Blueprint' не найдена. Найдены: {button_texts}"
        )


# =====================================================================
# 5. Интеграция ConstructorTabWidget (без NodeGraphQt — fallback режим)
# =====================================================================


class TestConstructorTabWidgetFallback:
    """Тесты ConstructorTabWidget в fallback-режиме (NodeGraphQt недоступен).

    Используют реальный виджет; если NodeGraphQt доступен — тоже работают.
    Тестируют правую панель (stack), toolbar и базовый layout.
    """

    def _make_widget(self, qapp):
        """Создать ConstructorTabWidget."""
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.widget import (
            ConstructorTabWidget,
        )

        editor = _make_topology_editor()
        widget = ConstructorTabWidget(topology_editor=editor)
        widget.show()
        qapp.processEvents()
        return widget, editor

    def test_stack_has_three_pages(self, qapp) -> None:
        """QStackedWidget содержит ровно 3 страницы (placeholder, process, wire)."""
        widget, _ = self._make_widget(qapp)

        assert widget._stack.count() == 3

    def test_initial_stack_index_is_placeholder(self, qapp) -> None:
        """При инициализации показывается placeholder (index=0)."""
        widget, _ = self._make_widget(qapp)

        assert widget._stack.currentIndex() == 0

    def test_on_node_selected_unknown_process_no_crash(self, qapp) -> None:
        """_on_node_selected с несуществующим ключом не вызывает исключение."""
        widget, _ = self._make_widget(qapp)

        # Не должно выбрасывать исключение
        widget._on_node_selected("nonexistent_process")
        qapp.processEvents()

        # Stack остаётся на placeholder (процесс не найден)
        assert widget._stack.currentIndex() == 0

    def test_on_wire_selected_unknown_wire_no_crash(self, qapp) -> None:
        """_on_wire_selected с несуществующим ключом не вызывает исключение."""
        widget, _ = self._make_widget(qapp)

        widget._on_wire_selected("nonexistent_wire")
        qapp.processEvents()

        # Stack остаётся на placeholder
        assert widget._stack.currentIndex() == 0

    def test_toolbar_has_blueprint_buttons_fallback(self, qapp) -> None:
        """Toolbar содержит кнопки Blueprint даже в fallback-режиме."""
        from PySide6.QtWidgets import QPushButton

        widget, _ = self._make_widget(qapp)

        button_texts = {child.text() for child in widget._toolbar.findChildren(QPushButton)}

        assert "Сохранить Blueprint" in button_texts
        assert "Загрузить Blueprint" in button_texts
