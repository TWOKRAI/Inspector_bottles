"""Тесты для bridge и controls."""

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge
from multiprocess_prototype.frontend.widgets.controls.process_status import ProcessStatusWidget
from multiprocess_prototype.frontend.widgets.controls.command_panel import CommandPanel


class TestStateListeners:
    """§11.15: multi-subscriber add_state_listener вместо closure-мультиплексора."""

    def test_primary_and_listeners_called_in_order(self, qtbot):
        """state-сообщение → _state_cb, затем все add_state_listener, по порядку."""
        bridge = DataReceiverBridge()
        calls: list[str] = []
        bridge.set_state_callback(lambda m: calls.append("primary"))
        bridge.add_state_listener(lambda m: calls.append("listener_1"))
        bridge.add_state_listener(lambda m: calls.append("listener_2"))

        # dispatch из main thread → AutoConnection вызывает _on_deliver синхронно
        bridge.dispatch({"data_type": "state_delta", "path": "p", "value": 1})

        assert calls == ["primary", "listener_1", "listener_2"]

    def test_listener_added_once(self, qtbot):
        """Повторное добавление того же cb игнорируется (идемпотентность)."""
        bridge = DataReceiverBridge()
        calls: list[int] = []

        def listener(_m):
            calls.append(1)

        bridge.add_state_listener(listener)
        bridge.add_state_listener(listener)
        bridge.dispatch({"data_type": "state_delta", "path": "p", "value": 1})

        assert calls == [1]


class TestCommandSender:
    """Тесты CommandSender."""

    def test_send_command_format(self):
        """send_command формирует корректный dict."""
        mock_process = MagicMock()
        mock_process.name = "gui"
        sender = CommandSender(mock_process)

        sender.send_command("camera_0", "start_capture", {"resolution": "1080p"})

        mock_process.send_message.assert_called_once()
        args = mock_process.send_message.call_args
        assert args[0][0] == "camera_0"  # target
        msg = args[0][1]
        assert msg["type"] == "command"
        assert msg["data_type"] == "start_capture"
        assert msg["sender"] == "gui"
        assert msg["targets"] == ["camera_0"]
        assert msg["data"] == {"resolution": "1080p"}

    def test_send_command_no_args(self):
        """send_command без args → data == {}."""
        mock_process = MagicMock()
        mock_process.name = "gui"
        sender = CommandSender(mock_process)

        sender.send_command("camera_0", "stop_capture")

        msg = mock_process.send_message.call_args[0][1]
        assert msg["data"] == {}


class TestProcessStatusWidget:
    """Тесты ProcessStatusWidget."""

    def test_on_state_updated(self, qtbot):
        """on_state_updated обновляет таблицу."""
        widget = ProcessStatusWidget()
        qtbot.addWidget(widget)

        widget.on_state_updated(
            {
                "data_type": "status",
                "sender": "camera_0",
                "data": {"status": "running", "pid": 1234},
            }
        )

        assert widget._table.rowCount() == 1
        assert widget._table.item(0, 0).text() == "camera_0"
        assert widget._table.item(0, 1).text() == "running"
        assert widget._table.item(0, 2).text() == "1234"

    def test_multiple_processes(self, qtbot):
        """Несколько процессов отображаются."""
        widget = ProcessStatusWidget()
        qtbot.addWidget(widget)

        widget.on_state_updated({"sender": "camera_0", "data": {"status": "running", "pid": 100}})
        widget.on_state_updated({"sender": "processor_0", "data": {"status": "ready", "pid": 200}})

        assert widget._table.rowCount() == 2


class TestCommandPanel:
    """Тесты CommandPanel."""

    def test_creates(self, qtbot):
        """CommandPanel создаётся без crash."""
        mock_sender = MagicMock()
        panel = CommandPanel(mock_sender)
        qtbot.addWidget(panel)
        assert panel is not None
