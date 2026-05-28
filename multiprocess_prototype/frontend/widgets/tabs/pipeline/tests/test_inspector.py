"""Тесты NodeInspectorPanel — включая интеграцию с CardsFieldFactory.
Task E.1: мигрировано на AppServices. set_services вместо set_context.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from PySide6.QtWidgets import QLineEdit

from ._helpers import make_pipeline_services


# ------------------------------------------------------------------ #
#  Вспомогательные фабрики и фикстуры                                 #
# ------------------------------------------------------------------ #


def _make_services_no_rm():
    """AppServices без RegistersManager bridge."""
    return make_pipeline_services()


def _make_services_with_rm(fields: list):
    """AppServices с RegistersManager bridge, возвращающим заданные FieldInfo."""
    rm = MagicMock()
    rm.get_fields.return_value = fields
    return make_pipeline_services(registers_manager=rm)


def _make_field_info(field_name: str, field_type: type = str, default: Any = ""):
    """Создать FieldInfo для теста."""
    from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo

    return FieldInfo(
        plugin_name="test_plugin",
        field_name=field_name,
        field_type=field_type,
        default=default,
        meta=None,
        category="test",
    )


def _make_presenter_services(rm=None, bus=None):
    """AppServices для PipelinePresenter с опциональным rm и bus."""
    return make_pipeline_services(
        topology={"processes": [], "wires": []},
        registers_manager=rm,
        action_bus=bus,
    )


# ------------------------------------------------------------------ #
#  Оригинальные тесты (backward compatibility)                        #
# ------------------------------------------------------------------ #


class TestNodeInspectorPanel:
    def test_create(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        assert not panel._placeholder.isHidden()
        assert panel._content.isHidden()

    def test_show_node(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.show_node("camera", "source")
        assert panel.current_process == "camera"
        assert panel._placeholder.isHidden()
        assert not panel._content.isHidden()
        assert panel._title.text() == "camera"

    def test_show_node_with_plugins(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        plugins = [{"plugin_name": "capture"}, {"plugin_name": "filter"}]
        panel.show_node("camera", "source", plugins=plugins)
        assert panel._params_layout.count() >= 2

    def test_show_node_with_params(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30", "resolution": "1080"})
        assert "fps" in panel._field_editors
        assert "resolution" in panel._field_editors
        assert isinstance(panel._field_editors["fps"], QLineEdit)
        assert panel._field_editors["fps"].text() == "30"

    def test_clear(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.show_node("camera", "source")
        panel.clear()
        assert panel.current_process == ""
        assert not panel._placeholder.isHidden()
        assert panel._content.isHidden()

    def test_update_field_suppresses_signal(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30"})

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel.update_field("fps", "60")
        assert panel._field_editors["fps"].text() == "60"
        assert len(signals_received) == 0

    def test_field_changed_signal(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30"})

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel._field_editors["fps"].setText("60")
        panel._field_editors["fps"].editingFinished.emit()
        assert len(signals_received) == 1
        assert signals_received[0] == ("camera", "fps", "60")

    def test_show_different_node_clears_previous(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30"})
        panel.show_node("processor", "processing", params={"threshold": "128"})
        assert panel.current_process == "processor"
        assert "threshold" in panel._field_editors
        assert "fps" not in panel._field_editors


# ------------------------------------------------------------------ #
#  Новые тесты: CardsFieldFactory-ветка                               #
# ------------------------------------------------------------------ #


class TestCardsFieldFactoryBranch:
    def test_cards_branch_activated_when_rm_has_fields(self, qtbot):
        """Если rm.get_fields() возвращает список — создаются FieldEditor."""
        fi = _make_field_info("threshold", int, 128)
        services = _make_services_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_node("camera", "source")

        assert panel._use_cards is True
        assert "threshold" in panel._field_editors
        assert not isinstance(panel._field_editors["threshold"], QLineEdit)

    def test_lineedit_fallback_when_rm_none(self, qtbot):
        """Fallback на QLineEdit если RegistersManager недоступен."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel._use_cards is False
        assert isinstance(panel._field_editors["fps"], QLineEdit)

    def test_lineedit_fallback_when_rm_empty_fields(self, qtbot):
        """Fallback на QLineEdit если rm.get_fields() возвращает пустой список."""
        services = _make_services_with_rm([])
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel._use_cards is False
        assert isinstance(panel._field_editors["fps"], QLineEdit)

    def test_update_field_cards_suppresses_signal(self, qtbot):
        """update_field через FieldEditor не тригерит field_changed."""
        fi = _make_field_info("threshold", int, 128)
        services = _make_services_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_node("camera", "source")

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel.update_field("threshold", 200)
        assert len(signals_received) == 0

    def test_update_field_cards_sets_value(self, qtbot):
        """update_field через FieldEditor корректно устанавливает значение."""
        fi = _make_field_info("threshold", int, 128)
        services = _make_services_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_node("camera", "source")

        panel.update_field("threshold", 42)
        editor = panel._field_editors["threshold"]
        assert editor.getter() == 42

    def test_cards_field_changed_signal_emitted(self, qtbot):
        """Изменение значения через FieldEditor эмитит field_changed."""
        fi = _make_field_info("threshold", int, 128)
        services = _make_services_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_node("my_process", "source")

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        editor = panel._field_editors["threshold"]
        panel._on_field_editor_changed("threshold", editor)

        assert len(signals_received) == 1
        process_name, field_name, value = signals_received[0]
        assert process_name == "my_process"
        assert field_name == "threshold"

    def test_no_signal_leak_on_node_switch(self, qtbot):
        """Быстрое переключение нод не приводит к утечкам сигналов."""
        fi_a = _make_field_info("fps", int, 30)
        fi_b = _make_field_info("threshold", int, 128)

        rm = MagicMock()
        rm.get_fields.return_value = [fi_a]
        services = make_pipeline_services(registers_manager=rm)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        # Переключение: node A → node B
        panel.show_node("node_a", "source")

        rm.get_fields.return_value = [fi_b]
        panel.show_node("node_b", "source")

        assert "fps" not in panel._field_editors
        assert "threshold" in panel._field_editors

    def test_set_services_stores(self, qtbot):
        """set_services корректно сохраняет AppServices."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        services = _make_services_no_rm()
        panel.set_services(services)

        assert panel._services is services

    def test_suppress_changes_during_show_node(self, qtbot):
        """Во время show_node _suppress_changes=True, поэтому сигналы не эмитятся."""
        fi = _make_field_info("rate", float, 1.0)
        services = _make_services_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel.show_node("camera", "source")

        assert len(signals_received) == 0


# ------------------------------------------------------------------ #
#  Тесты: PipelinePresenter + ActionBus integration                   #
# ------------------------------------------------------------------ #


class TestPresenterInspectorIntegration:
    def test_set_inspector_connects_field_changed(self, qtbot):
        """set_inspector подключает inspector.field_changed к presenter."""
        services = _make_presenter_services()
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)

        # AppServices должен быть передан в panel
        assert panel._services is services

    def test_field_changed_calls_action_bus(self, qtbot):
        """field_changed → presenter → ActionBus.execute() вызывается."""
        rm = MagicMock()
        rm.get_fields.return_value = []
        rm.get_register.return_value = None

        bus = MagicMock()

        services = _make_presenter_services(rm=rm, bus=bus)
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)
        panel.show_node("camera", "source", params={"fps": "30"})

        panel.field_changed.emit("camera", "fps", "60")

        assert bus.execute.called

    def test_field_changed_no_bus_calls_rm(self, qtbot):
        """Если ActionBus=None, вызывается rm.set_value()."""
        rm = MagicMock()
        rm.get_fields.return_value = []
        rm.get_register.return_value = None

        services = _make_presenter_services(rm=rm, bus=None)
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)
        panel.field_changed.emit("camera", "fps", "60")

        rm.set_value.assert_called_once_with("camera", "fps", "60")

    def test_field_changed_no_bus_no_rm_logs_warning(self, qtbot, caplog):
        """Если ни ActionBus ни rm — логируется warning."""
        import logging

        services = _make_presenter_services(rm=None, bus=None)
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)

        with caplog.at_level(logging.WARNING):
            panel.field_changed.emit("camera", "fps", "60")

        assert any("warning" in r.levelname.lower() or r.levelno >= logging.WARNING for r in caplog.records)


# ------------------------------------------------------------------ #
#  Task 7a.3: combo target_process + combo display_id                 #
# ------------------------------------------------------------------ #


def _make_services_with_recipe(process_names: list[str]):
    """AppServices с RecipeManager bridge, возвращающим процессы из рецепта."""
    rm_mock = MagicMock()
    rm_mock.get_active.return_value = "test_recipe"
    blueprint_processes = [{"process_name": name} for name in process_names]
    rm_mock.read_recipe.return_value = {"blueprint": {"processes": blueprint_processes, "wires": []}}

    return make_pipeline_services(recipe_manager=rm_mock)


def _make_display_entry(display_id: str, name: str):
    """Создать mock DisplayEntry."""
    entry = MagicMock()
    entry.id = display_id
    entry.name = name
    return entry


class TestTargetProcessCombo:
    """Тесты combo «Процесс назначения» для plugin-узлов."""

    def test_show_plugin_node_creates_target_process_combo(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor", "output"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.set_services(services)

        panel.show_plugin_node("camera", "source", target_process="camera")

        assert panel._target_process_form.isVisible()
        assert not panel._display_id_form.isVisible()

        combo = panel._target_process_combo
        assert combo is not None
        assert combo.isEnabled()
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "camera" in items
        assert "processor" in items
        assert "output" in items

    def test_show_plugin_node_selects_current_target_process(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_plugin_node("camera", "source", target_process="processor")

        combo = panel._target_process_combo
        assert combo.currentText() == "processor"

    def test_target_process_change_emits_signal(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_plugin_node("node1", "source", target_process="camera")

        received = []
        panel.target_process_changed.connect(lambda nid, proc: received.append((nid, proc)))

        combo = panel._target_process_combo
        idx = combo.findText("processor")
        assert idx >= 0
        combo.setCurrentIndex(idx)

        assert len(received) == 1
        assert received[0] == ("node1", "processor")

    def test_show_with_no_recipe_manager_combo_disabled(self, qtbot):
        services = _make_services_no_rm()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_plugin_node("node1", "utility", target_process="")

        combo = panel._target_process_combo
        assert not combo.isEnabled() or combo.count() == 0

    def test_show_with_no_services_doesnt_crash(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_plugin_node("node1", "utility", target_process="proc1")

        combo = panel._target_process_combo
        assert combo is not None
        assert not combo.isEnabled() or combo.count() == 0

    def test_signal_suppression_during_show_plugin_node(self, qtbot):
        services = _make_services_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        received = []
        panel.target_process_changed.connect(lambda *args: received.append(args))

        panel.show_plugin_node("camera", "source", target_process="camera")

        assert len(received) == 0

    def test_show_node_alias_still_works(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel.current_process == "camera"
        assert panel._mode == "plugin"


class TestDisplayIdCombo:
    """Тесты combo «Display» для display-узлов."""

    def _make_display_services(self, entries):
        """Создать services с DisplayCatalog для display combo."""
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        displays = MagicMock()
        display_specs = tuple(DisplaySpec(display_id=e.id, display_name=e.name) for e in entries)
        displays.list_displays.return_value = display_specs
        displays.resolve.side_effect = lambda did: next((s for s in display_specs if s.display_id == did), None)

        from multiprocess_prototype.domain.tests.conftest import make_test_app_services

        return make_test_app_services(displays=displays)

    def test_show_display_node_creates_display_id_combo(self, qtbot):
        entries = [
            _make_display_entry("main_output", "Основной дисплей"),
            _make_display_entry("debug_view", "Отладочный вид"),
        ]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.set_services(services)

        panel.show_display_node("disp1", "main_output", "Основной дисплей")

        assert panel._display_id_form.isVisible()
        assert not panel._target_process_form.isVisible()

        combo = panel._display_id_combo
        assert combo is not None
        assert combo.isEnabled()
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "main_output" in ids
        assert "debug_view" in ids

    def test_show_display_node_selects_current_display_id(self, qtbot):
        entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("debug", "Отладка"),
        ]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        panel.show_display_node("disp1", "debug", "Отладка")

        combo = panel._display_id_combo
        assert combo.itemData(combo.currentIndex()) == "debug"

    def test_display_id_change_emits_signal(self, qtbot):
        entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("debug", "Отладка"),
        ]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_display_node("disp1", "main_output", "Основной")

        received = []
        panel.display_id_changed.connect(lambda nid, did: received.append((nid, did)))

        combo = panel._display_id_combo
        target_idx = -1
        for i in range(combo.count()):
            if combo.itemData(i) == "debug":
                target_idx = i
                break
        assert target_idx >= 0
        combo.setCurrentIndex(target_idx)

        assert len(received) == 1
        assert received[0] == ("disp1", "debug")

    def test_display_combo_disabled_when_no_services(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        panel.show_display_node("disp1", "some_id", "")

        combo = panel._display_id_combo
        assert not combo.isEnabled() or combo.count() == 0

    def test_signal_suppression_during_show_display_node(self, qtbot):
        entries = [_make_display_entry("main_output", "Основной")]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)

        received = []
        panel.display_id_changed.connect(lambda *args: received.append(args))

        panel.show_display_node("disp1", "main_output", "Основной")

        assert len(received) == 0

    def test_refresh_display_combo_updates_entries(self, qtbot):
        from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

        entries = [_make_display_entry("main_output", "Основной")]
        services = self._make_display_services(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        panel.show_display_node("disp1", "main_output", "Основной")

        # Добавить новый дисплей в реестр
        new_specs = (
            DisplaySpec(display_id="main_output", display_name="Основной"),
            DisplaySpec(display_id="secondary", display_name="Вторичный"),
        )
        services.displays.list_displays.return_value = new_specs

        panel.refresh_display_combo()

        combo = panel._display_id_combo
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "secondary" in ids
