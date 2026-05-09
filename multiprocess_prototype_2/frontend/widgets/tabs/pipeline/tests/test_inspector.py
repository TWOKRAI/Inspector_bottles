"""Тесты NodeInspectorPanel."""
import pytest
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel


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
