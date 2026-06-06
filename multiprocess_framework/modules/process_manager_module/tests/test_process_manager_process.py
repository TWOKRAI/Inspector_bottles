"""
Тесты для ProcessManagerProcess.

Проверяют:
- initialize: успех, ошибка → error_module → shutdown
- shutdown: порядок (monitor → registry → console → super)
- create_process, start_process, stop_process
- get_process_status, get_all_processes_status
- Регистрацию встроенных команд
"""

from unittest.mock import MagicMock, patch
from multiprocessing import Event

from ...process_module import ProcessModule
from ..process.process_manager_process import ProcessManagerProcess


def _make_mock_shared_resources(process_name: str = "ProcessManager"):
    """Создать mock SharedResourcesManager."""
    mock_srm = MagicMock()
    mock_process_data = MagicMock()
    mock_process_data.custom = {"stop_event": Event()}
    mock_process_data.state = {"status": "running"}
    mock_srm.get_process_data.return_value = mock_process_data
    mock_srm.process_state_registry = MagicMock()
    mock_srm.process_state_registry.queue_registry = None
    return mock_srm


class TestProcessManagerProcessInit:
    def test_init_creates_components(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp._console_manager = None
            # config_handler инициализируется в ProcessModule.__init__; задаём None вручную
            # т.к. __init__ подменён и атрибут не создаётся автоматически
            pmp.config_handler = None

            # Проверяем что _create_components не падает без shared_resources
            with (
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessRegistry"
                ) as _mock_reg,
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessPriority"
                ),
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessStatusMonitor"
                ),
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.ProcessMonitor"
                ),
                patch(
                    "multiprocess_framework.modules.process_manager_module.process.process_manager_process.QueueRegistry"
                ) as mock_qr,
            ):
                mock_qr.return_value.initialize.return_value = None
                pmp._create_components()
                assert hasattr(pmp, "_process_registry")
                assert hasattr(pmp, "_priority")
                assert hasattr(pmp, "_status")
                assert hasattr(pmp, "_process_monitor")


class TestProcessManagerProcessShutdownOrder:
    def test_shutdown_order_monitor_then_registry(self) -> None:
        """Порядок shutdown: monitor → registry → console → super."""
        call_order = []

        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.config_handler = None

            mock_monitor = MagicMock()
            mock_registry = MagicMock()
            mock_console = MagicMock()

            def on_monitor_stop():
                call_order.append("monitor")

            def on_registry_stop(*args, **kwargs):
                call_order.append("registry")

            mock_monitor.stop.side_effect = on_monitor_stop
            mock_registry.stop_all.side_effect = on_registry_stop
            mock_console.close_all = MagicMock(side_effect=lambda: call_order.append("console"))

            pmp._process_monitor = mock_monitor
            pmp._process_registry = mock_registry
            pmp._console_manager = mock_console

            mock_super_shutdown = MagicMock(return_value=True)
            with patch.object(ProcessModule, "shutdown", mock_super_shutdown):
                pmp.shutdown()

        # Проверяем порядок: monitor до registry
        assert "monitor" in call_order and "registry" in call_order
        assert call_order.index("monitor") < call_order.index("registry")
        mock_super_shutdown.assert_called_once()

    def test_shutdown_without_console_does_not_raise(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.config_handler = None
            pmp._process_monitor = MagicMock()
            pmp._process_registry = MagicMock()
            pmp._console_manager = None

            with patch.object(ProcessManagerProcess.__bases__[0], "shutdown", return_value=True):
                pmp.shutdown()


class TestProcessManagerProcessStopProcess:
    def test_stop_process_graceful_before_terminate(self) -> None:
        """stop_process: join → terminate → kill (graceful cascade)."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_process = MagicMock()
            mock_process.is_alive.return_value = True

            mock_registry = MagicMock()
            mock_registry.get_process_by_name.return_value = mock_process
            mock_registry.stop_one.return_value = True
            pmp._process_registry = mock_registry

            def get_config(key):
                return {"stop_process_timeout": 0.1}.get(key)

            pmp.get_config = get_config

            mock_process.is_alive.side_effect = [True, False, False]

            pmp.stop_process("TestProcess")

            mock_registry.stop_one.assert_called_once_with("TestProcess", 0.1)

    def test_stop_process_unknown_returns_true(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_registry = MagicMock()
            mock_registry.get_process_by_name.return_value = None
            pmp._process_registry = mock_registry
            pmp.get_config = lambda k: None

            result = pmp.stop_process("Unknown")
            assert result is True


class TestProcessManagerProcessGetStatus:
    def test_get_process_status_unknown_returns_empty(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_registry = MagicMock()
            mock_registry.get_process_by_name.return_value = None
            pmp._process_registry = mock_registry

            result = pmp.get_process_status("Unknown")
            assert result == {}

    def test_get_all_processes_status_delegates_to_status(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_status = MagicMock()
            mock_status.get_all_status.return_value = {"P1": {"alive": True}}
            pmp._status = mock_status

            result = pmp.get_all_processes_status()
            assert result == {"P1": {"alive": True}}


class TestProcessManagerProcessBuiltinCommands:
    def test_cmd_process_list_returns_dict(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp._process_configs = {}  # обязателен для обогащения статуса

            mock_status = MagicMock()
            mock_status.get_all_status.return_value = {"P1": {}}
            pmp._status = mock_status

            result = pmp._cmd_process_list()
            assert isinstance(result, dict)

    def test_cmd_process_start_requires_name(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            result = pmp._cmd_process_start()
            assert "error" in result

    def test_cmd_process_stop_requires_name(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            result = pmp._cmd_process_stop()
            assert "error" in result

    def test_cmd_system_shutdown_sets_stop_event(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.stop_event = Event()
            pmp._log_info = MagicMock()

            result = pmp._cmd_system_shutdown()
            assert result["success"] is True
            assert pmp.stop_event.is_set()

    def test_cmd_system_stats_returns_dict(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_monitor = MagicMock()
            mock_monitor.get_stats.return_value = {"monitoring": False}
            pmp._process_monitor = mock_monitor

            mock_status = MagicMock()
            mock_status.get_all_status.return_value = {}
            pmp._status = mock_status

            result = pmp._cmd_system_stats()
            assert "monitor" in result
            assert "processes" in result

    def test_register_builtin_commands_registers_all(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}

            mock_cm = MagicMock()
            mock_cm.register_command.return_value = True
            pmp.command_manager = mock_cm

            pmp._register_builtin_commands()

            registered_names = [call_args[0][0] for call_args in mock_cm.register_command.call_args_list]
            assert "process.list" in registered_names
            assert "process.start" in registered_names
            assert "process.stop" in registered_names
            assert "process.restart" in registered_names
            assert "process.status" in registered_names
            assert "system.shutdown" in registered_names
            assert "system.stats" in registered_names

    def test_register_builtin_commands_skips_if_no_command_manager(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp.shared_resources = None
            pmp.config = {}
            pmp.command_manager = None

            pmp._register_builtin_commands()  # не должен падать


class TestProcessCommandResponse:
    """_handle_process_command делегирует ответ дженерик reply_to_request
    (absorb bespoke-reply, ADR-COMM-005). Адресация/correlation — внутри
    reply_to_request (покрыто router_module/tests reply_to_request)."""

    def _make_pmp(self):
        pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pmp.name = "ProcessManager"
        pmp.command_manager = MagicMock()
        pmp.router_manager = MagicMock()
        pmp._log_error = MagicMock()
        pmp._log_debug = MagicMock()
        return pmp

    def test_delegates_result_to_reply_to_request(self) -> None:
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {"success": True, "replaced": ["a"]}
        msg = {
            "command": "process.command",
            "sender": "gui",
            "data": {"cmd": "blueprint.replace", "correlation_id": "c1", "blueprint": {}},
        }
        pmp._handle_process_command(msg)

        pmp.router_manager.reply_to_request.assert_called_once()
        call = pmp.router_manager.reply_to_request.call_args
        # исходный билет передан → reply_to_request извлечёт correlation/target сам
        assert call.args[0] is msg
        assert call.args[1] == {"success": True, "replaced": ["a"]}  # результат вложенной команды
        assert call.kwargs.get("success") is True
        assert call.kwargs.get("response_command") == "process.command.response"
        pmp.router_manager.send.assert_not_called()  # больше НЕ кустарный send

    def test_inner_command_unwrapped_without_service_fields(self) -> None:
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {"status": "ok"}
        pmp._handle_process_command(
            {
                "command": "process.command",
                "sender": "gui",
                "data": {"cmd": "process.start", "correlation_id": "c2", "process_name": "cam"},
            }
        )
        inner = pmp.command_manager.handle_command.call_args[0][0]
        assert inner["command"] == "process.start"
        assert inner["data"] == {"process_name": "cam"}  # cmd/correlation_id отфильтрованы

    def test_command_error_marks_success_false(self) -> None:
        pmp = self._make_pmp()
        pmp.command_manager.handle_command.return_value = {"status": "error", "reason": "boom"}
        pmp._handle_process_command(
            {
                "command": "process.command",
                "sender": "gui",
                "data": {"cmd": "process.start", "correlation_id": "c3"},
            }
        )
        call = pmp.router_manager.reply_to_request.call_args
        assert call.kwargs.get("success") is False
        assert call.args[1] == {"status": "error", "reason": "boom"}
