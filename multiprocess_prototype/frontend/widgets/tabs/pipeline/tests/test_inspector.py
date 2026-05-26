"""Тесты NodeInspectorPanel — включая интеграцию с CardsFieldFactory."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from PySide6.QtWidgets import QLineEdit


# ------------------------------------------------------------------ #
#  Вспомогательные фабрики и фикстуры                                 #
# ------------------------------------------------------------------ #


def _make_ctx_no_rm():
    """AppContext без RegistersManager."""
    ctx = MagicMock()
    ctx.registers_manager.return_value = None
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.plugin_registry.return_value = None
    ctx.bindings.return_value = None
    ctx.topology_bridge.return_value = None
    ctx.config = {}
    # form_context() должен возвращать None — тесты используют mock без реального
    # ActionBus, binding-aware builders не могут работать с MagicMock.
    ctx.form_context.return_value = None
    return ctx


def _make_ctx_with_rm(fields: list):
    """AppContext с RegistersManager, возвращающим заданные FieldInfo."""
    ctx = _make_ctx_no_rm()
    rm = MagicMock()
    rm.get_fields.return_value = fields
    ctx.registers_manager.return_value = rm
    return ctx


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


def _make_presenter_ctx(rm=None, bus=None):
    """AppContext для PipelinePresenter."""
    ctx = MagicMock()
    ctx.config = {"topology": {"processes": [], "wires": []}}
    ctx.registers_manager.return_value = rm
    ctx.action_bus.return_value = bus
    ctx.topology_holder.return_value = None
    ctx.plugin_registry.return_value = None
    ctx.bindings.return_value = None
    ctx.topology_bridge.return_value = None
    return ctx


# ------------------------------------------------------------------ #
#  Оригинальные тесты (backward compatibility)                        #
# ------------------------------------------------------------------ #


class TestNodeInspectorPanel:
    def test_create(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()
        # placeholder виден, content скрыт
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
        # Проверяем что форма не пустая
        assert panel._params_layout.count() >= 2

    def test_show_node_with_params(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30", "resolution": "1080"})
        assert "fps" in panel._field_editors
        assert "resolution" in panel._field_editors
        # Fallback QLineEdit
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

        # Programmatic update — НЕ должен эмитить сигнал
        panel.update_field("fps", "60")
        assert panel._field_editors["fps"].text() == "60"
        assert len(signals_received) == 0

    def test_field_changed_signal(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30"})

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        # Пользовательское изменение
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
        ctx = _make_ctx_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_node("camera", "source")

        assert panel._use_cards is True
        assert "threshold" in panel._field_editors
        # Не QLineEdit — а FieldEditor
        assert not isinstance(panel._field_editors["threshold"], QLineEdit)

    def test_lineedit_fallback_when_rm_none(self, qtbot):
        """Fallback на QLineEdit если RegistersManager недоступен."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        # ctx не задан — rm = None

        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel._use_cards is False
        assert isinstance(panel._field_editors["fps"], QLineEdit)

    def test_lineedit_fallback_when_rm_empty_fields(self, qtbot):
        """Fallback на QLineEdit если rm.get_fields() возвращает пустой список."""
        ctx = _make_ctx_with_rm([])  # пустые поля
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        panel.show_node("camera", "source", params={"fps": "30"})

        # Fallback на QLineEdit
        assert panel._use_cards is False
        assert isinstance(panel._field_editors["fps"], QLineEdit)

    def test_update_field_cards_suppresses_signal(self, qtbot):
        """update_field через FieldEditor не тригерит field_changed."""
        fi = _make_field_info("threshold", int, 128)
        ctx = _make_ctx_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_node("camera", "source")

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        # Programmatic update — НЕ должен эмитить сигнал
        panel.update_field("threshold", 200)
        assert len(signals_received) == 0

    def test_update_field_cards_sets_value(self, qtbot):
        """update_field через FieldEditor корректно устанавливает значение."""
        fi = _make_field_info("threshold", int, 128)
        ctx = _make_ctx_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_node("camera", "source")

        panel.update_field("threshold", 42)
        editor = panel._field_editors["threshold"]
        # getter должен вернуть установленное значение
        assert editor.getter() == 42

    def test_cards_field_changed_signal_emitted(self, qtbot):
        """Изменение значения через FieldEditor эмитит field_changed."""
        fi = _make_field_info("threshold", int, 128)
        ctx = _make_ctx_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_node("my_process", "source")

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        # Вызов обработчика напрямую (имитация изменения пользователем)
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
        ctx = MagicMock()
        ctx.registers_manager.return_value = MagicMock()
        # form_context() = None → legacy путь; binding-aware builders требуют
        # реального ActionBus, которого здесь нет.
        ctx.form_context.return_value = None

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        # Переключение: node A → node B
        ctx.registers_manager.return_value.get_fields.return_value = [fi_a]
        panel.show_node("node_a", "source")

        ctx.registers_manager.return_value.get_fields.return_value = [fi_b]
        panel.show_node("node_b", "source")

        # После переключения: editors из node_a отключены, нет утечек
        assert "fps" not in panel._field_editors
        assert "threshold" in panel._field_editors

    def test_set_context_stores_ctx(self, qtbot):
        """set_context корректно сохраняет AppContext."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        ctx = _make_ctx_no_rm()
        panel.set_context(ctx)

        assert panel._ctx is ctx

    def test_suppress_changes_during_show_node(self, qtbot):
        """Во время show_node _suppress_changes=True, поэтому сигналы не эмитятся."""
        fi = _make_field_info("rate", float, 1.0)
        ctx = _make_ctx_with_rm([fi])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        signals_received = []
        panel.field_changed.connect(lambda *args: signals_received.append(args))

        panel.show_node("camera", "source")

        # Сигналов не должно быть эмитировано во время show_node
        assert len(signals_received) == 0


# ------------------------------------------------------------------ #
#  Новые тесты: PipelinePresenter + ActionBus integration             #
# ------------------------------------------------------------------ #


class TestPresenterInspectorIntegration:
    def test_set_inspector_connects_field_changed(self, qtbot):
        """set_inspector подключает inspector.field_changed к presenter."""
        ctx = _make_presenter_ctx()
        presenter = PipelinePresenter(ctx)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)

        # AppContext должен быть передан в panel
        assert panel._ctx is ctx

    def test_field_changed_calls_action_bus(self, qtbot):
        """field_changed → presenter → ActionBus.execute() вызывается."""
        rm = MagicMock()
        rm.get_fields.return_value = []
        rm.get_register.return_value = None

        bus = MagicMock()

        ctx = _make_presenter_ctx(rm=rm, bus=bus)
        presenter = PipelinePresenter(ctx)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)
        panel.show_node("camera", "source", params={"fps": "30"})

        # Эмитируем signal вручную
        panel.field_changed.emit("camera", "fps", "60")

        # ActionBus.execute() должен быть вызван
        assert bus.execute.called

    def test_field_changed_no_bus_calls_rm(self, qtbot):
        """Если ActionBus=None, вызывается rm.set_value()."""
        rm = MagicMock()
        rm.get_fields.return_value = []
        rm.get_register.return_value = None

        ctx = _make_presenter_ctx(rm=rm, bus=None)
        presenter = PipelinePresenter(ctx)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)
        panel.field_changed.emit("camera", "fps", "60")

        # rm.set_value() должен быть вызван
        rm.set_value.assert_called_once_with("camera", "fps", "60")

    def test_field_changed_no_bus_no_rm_logs_warning(self, qtbot, caplog):
        """Если ни ActionBus ни rm — логируется warning."""
        import logging

        ctx = _make_presenter_ctx(rm=None, bus=None)
        presenter = PipelinePresenter(ctx)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        presenter.set_inspector(panel)

        with caplog.at_level(logging.WARNING):
            panel.field_changed.emit("camera", "fps", "60")

        # В лог записано предупреждение
        assert any("warning" in r.levelname.lower() or r.levelno >= logging.WARNING for r in caplog.records)


# ------------------------------------------------------------------ #
#  Task 7a.3: combo target_process + combo display_id                 #
# ------------------------------------------------------------------ #


def _make_ctx_with_recipe(process_names: list[str]):
    """AppContext с RecipeManager, возвращающим заданные имена процессов.

    recipe_manager в AppContext — @property, поэтому используем PropertyMock.
    """
    from unittest.mock import PropertyMock

    ctx = MagicMock()
    ctx.registers_manager.return_value = None
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.plugin_registry.return_value = None
    ctx.form_context.return_value = None

    rm_mock = MagicMock()
    rm_mock.get_active.return_value = "test_recipe"
    blueprint_processes = [{"process_name": name} for name in process_names]
    rm_mock.read_recipe.return_value = {"blueprint": {"processes": blueprint_processes, "wires": []}}

    # recipe_manager — @property в AppContext, устанавливаем через PropertyMock
    type(ctx).recipe_manager = PropertyMock(return_value=rm_mock)
    ctx.display_registry = None
    return ctx


def _make_display_entry(display_id: str, name: str):
    """Создать mock DisplayEntry."""
    entry = MagicMock()
    entry.id = display_id
    entry.name = name
    return entry


def _make_ctx_with_display_registry(entries: list):
    """AppContext с DisplayRegistry, возвращающим заданные DisplayEntry."""
    ctx = MagicMock()
    ctx.registers_manager.return_value = None
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.plugin_registry.return_value = None
    ctx.form_context.return_value = None
    ctx.recipe_manager = None

    registry_mock = MagicMock()
    registry_mock.list.return_value = entries
    registry_mock.get.side_effect = lambda did: next((e for e in entries if e.id == did), None)
    ctx.display_registry = registry_mock
    return ctx


class TestTargetProcessCombo:
    """Тесты combo «Процесс назначения» для plugin-узлов."""

    def test_show_plugin_node_creates_target_process_combo(self, qtbot):
        """Combo «Процесс назначения» появляется и заполнен именами процессов."""
        ctx = _make_ctx_with_recipe(["camera", "processor", "output"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()  # нужно для корректной проверки isVisible()
        panel.set_context(ctx)

        panel.show_plugin_node("camera", "source", target_process="camera")

        # Форма с combo должна быть видима (panel.show() активирует дерево)
        assert panel._target_process_form.isVisible()
        assert not panel._display_id_form.isVisible()

        combo = panel._target_process_combo
        assert combo is not None
        assert combo.isEnabled()
        # Проверяем что combo заполнен именами процессов
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "camera" in items
        assert "processor" in items
        assert "output" in items

    def test_show_plugin_node_selects_current_target_process(self, qtbot):
        """Combo показывает текущее значение target_process."""
        ctx = _make_ctx_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        panel.show_plugin_node("camera", "source", target_process="processor")

        combo = panel._target_process_combo
        assert combo.currentText() == "processor"

    def test_target_process_change_emits_signal(self, qtbot):
        """Выбор нового процесса в combo → испускается сигнал target_process_changed."""
        ctx = _make_ctx_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_plugin_node("node1", "source", target_process="camera")

        received = []
        panel.target_process_changed.connect(lambda nid, proc: received.append((nid, proc)))

        # Симулируем выбор другого процесса
        combo = panel._target_process_combo
        idx = combo.findText("processor")
        assert idx >= 0
        combo.setCurrentIndex(idx)

        assert len(received) == 1
        assert received[0] == ("node1", "processor")

    def test_show_with_no_recipe_manager_combo_disabled(self, qtbot):
        """Если RecipeManager недоступен — combo disabled, не падает."""
        ctx = _make_ctx_no_rm()
        ctx.recipe_manager = None  # Явно None
        ctx.display_registry = None

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        # Не должно упасть
        panel.show_plugin_node("node1", "utility", target_process="")

        combo = panel._target_process_combo
        # Combo должен быть disabled и пустым
        assert not combo.isEnabled() or combo.count() == 0

    def test_show_with_no_ctx_doesnt_crash(self, qtbot):
        """set_context(None) — combo disabled, не падает при show_plugin_node."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        # ctx не задан

        # Не должно упасть
        panel.show_plugin_node("node1", "utility", target_process="proc1")

        combo = panel._target_process_combo
        assert combo is not None
        # Без контекста combo должен быть пустым/disabled
        assert not combo.isEnabled() or combo.count() == 0

    def test_signal_suppression_during_show_plugin_node(self, qtbot):
        """При show_plugin_node сигнал target_process_changed НЕ испускается."""
        ctx = _make_ctx_with_recipe(["camera", "processor"])

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        received = []
        panel.target_process_changed.connect(lambda *args: received.append(args))

        # show_plugin_node должен подавить сигналы
        panel.show_plugin_node("camera", "source", target_process="camera")

        assert len(received) == 0, "Сигнал target_process_changed не должен эмитироваться при programmatic show"

    def test_show_node_alias_still_works(self, qtbot):
        """show_node() продолжает работать как алиас show_plugin_node."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)

        # Не должно упасть, показывает plugin-узел
        panel.show_node("camera", "source", params={"fps": "30"})

        assert panel.current_process == "camera"
        assert panel._mode == "plugin"


class TestDisplayIdCombo:
    """Тесты combo «Display» для display-узлов."""

    def test_show_display_node_creates_display_id_combo(self, qtbot):
        """Combo «Display» появляется и заполнен display id+name."""
        entries = [
            _make_display_entry("main_output", "Основной дисплей"),
            _make_display_entry("debug_view", "Отладочный вид"),
        ]
        ctx = _make_ctx_with_display_registry(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show()  # нужно для корректной проверки isVisible()
        panel.set_context(ctx)

        panel.show_display_node("disp1", "main_output", "Основной дисплей")

        # Форма с combo display должна быть видима (panel.show() активирует дерево)
        assert panel._display_id_form.isVisible()
        assert not panel._target_process_form.isVisible()

        combo = panel._display_id_combo
        assert combo is not None
        assert combo.isEnabled()
        # Проверяем что display_id доступны через userData
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "main_output" in ids
        assert "debug_view" in ids

    def test_show_display_node_selects_current_display_id(self, qtbot):
        """Combo показывает текущий display_id."""
        entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("debug", "Отладка"),
        ]
        ctx = _make_ctx_with_display_registry(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        panel.show_display_node("disp1", "debug", "Отладка")

        combo = panel._display_id_combo
        # Выбранный элемент должен соответствовать display_id="debug"
        assert combo.itemData(combo.currentIndex()) == "debug"

    def test_display_id_change_emits_signal(self, qtbot):
        """Выбор display в combo → испускается сигнал display_id_changed."""
        entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("debug", "Отладка"),
        ]
        ctx = _make_ctx_with_display_registry(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_display_node("disp1", "main_output", "Основной")

        received = []
        panel.display_id_changed.connect(lambda nid, did: received.append((nid, did)))

        # Выбрать другой display
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

    def test_display_combo_disabled_when_registry_unavailable(self, qtbot):
        """Если DisplayRegistry недоступен — combo disabled, не падает."""
        ctx = _make_ctx_no_rm()
        ctx.display_registry = None
        ctx.recipe_manager = None

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        # Не должно упасть
        panel.show_display_node("disp1", "some_id", "")

        combo = panel._display_id_combo
        assert not combo.isEnabled() or combo.count() == 0

    def test_signal_suppression_during_show_display_node(self, qtbot):
        """При show_display_node сигнал display_id_changed НЕ испускается."""
        entries = [_make_display_entry("main_output", "Основной")]
        ctx = _make_ctx_with_display_registry(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)

        received = []
        panel.display_id_changed.connect(lambda *args: received.append(args))

        panel.show_display_node("disp1", "main_output", "Основной")

        assert len(received) == 0, "Сигнал display_id_changed не должен эмитироваться при programmatic show"

    def test_refresh_display_combo_updates_entries(self, qtbot):
        """refresh_display_combo() обновляет список дисплеев из реестра."""
        entries = [_make_display_entry("main_output", "Основной")]
        ctx = _make_ctx_with_display_registry(entries)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_context(ctx)
        panel.show_display_node("disp1", "main_output", "Основной")

        # Добавить новый дисплей в реестр
        new_entries = [
            _make_display_entry("main_output", "Основной"),
            _make_display_entry("secondary", "Вторичный"),
        ]
        ctx.display_registry.list.return_value = new_entries
        ctx.display_registry.get.side_effect = lambda did: next((e for e in new_entries if e.id == did), None)

        # Обновить combo
        panel.refresh_display_combo()

        combo = panel._display_id_combo
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "secondary" in ids
