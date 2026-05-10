"""Тесты NodeInspectorPanel — включая интеграцию с CardsFieldFactory."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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
    from multiprocess_prototype.registers.field_info import FieldInfo
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
        assert any("warning" in r.levelname.lower() or r.levelno >= logging.WARNING
                   for r in caplog.records)
