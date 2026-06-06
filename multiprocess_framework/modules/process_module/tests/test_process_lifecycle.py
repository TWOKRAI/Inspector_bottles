# -*- coding: utf-8 -*-
"""Тесты для process_module lifecycle — initialize/shutdown с мок shared_resources."""

from unittest.mock import Mock

from ..core.process_module import ProcessModule
from ..types import ProcessStatus


def make_mock_shared_resources():
    """Создать мок shared_resources, совместимый с ISharedResources."""
    sr = Mock()
    sr.get_process_data = Mock(return_value=None)
    sr.queue_registry = None
    sr.memory_manager = None
    sr.event_manager = Mock()
    sr.event_manager.set_router_manager = Mock()
    sr.process_state_registry = Mock()
    sr.process_state_registry.get_process_names = Mock(return_value=[])
    sr.process_state_registry.register_process = Mock(return_value=True)
    sr.process_state_registry.update_state = Mock(return_value=True)
    return sr


class TestProcessModuleCreation:
    def test_create_minimal(self):
        process = ProcessModule("test_proc")
        assert process.name == "test_proc"
        assert process.manager_name == "test_proc"
        assert process.is_initialized is False
        assert process._stop_requested is False

    def test_create_with_config(self):
        config = {"key": "value", "workers": {}}
        process = ProcessModule("test_proc", config=config)
        assert process.config["key"] == "value"

    def test_create_with_shared_resources(self):
        sr = make_mock_shared_resources()
        process = ProcessModule("test_proc", shared_resources=sr)
        assert process.shared_resources is sr


class TestProcessModuleLifecycle:
    def _make_process_with_mocked_init(self, name="test_proc"):
        """Создать процесс с замоканными шагами инициализации."""
        sr = make_mock_shared_resources()
        process = ProcessModule(name, shared_resources=sr)

        process._init_configuration = Mock()
        process._init_queues = Mock()
        process._init_managers = Mock()
        process._init_communication = Mock()
        process._register_process_state = Mock()
        process._init_custom_managers = Mock()
        process._init_application_threads = Mock()
        process._init_system_threads = Mock()
        process.update_process_state = Mock()

        return process

    def test_initialize_returns_true(self):
        process = self._make_process_with_mocked_init()
        result = process.initialize()
        assert result is True
        assert process.is_initialized is True

    def test_initialize_calls_all_steps(self):
        process = self._make_process_with_mocked_init()
        process.initialize()

        process._init_configuration.assert_called_once()
        process._init_queues.assert_called_once()
        process._init_managers.assert_called_once()
        process._init_communication.assert_called_once()
        process._register_process_state.assert_called_once()
        process._init_system_threads.assert_called_once()

    def test_initialize_sets_ready_status(self):
        process = self._make_process_with_mocked_init()
        process.initialize()
        process.update_process_state.assert_called_with(status=ProcessStatus.READY.value)

    def test_initialize_returns_false_on_exception(self):
        process = self._make_process_with_mocked_init()
        process._init_configuration = Mock(side_effect=RuntimeError("config error"))
        result = process.initialize()
        assert result is False

    def test_shutdown_returns_true(self):
        process = self._make_process_with_mocked_init()
        process.is_initialized = True

        process._stop_system_threads = Mock()
        process.worker_manager = Mock()
        process.logger_manager = Mock()
        process.command_manager = Mock()
        process.router_manager = Mock()
        process.update_process_state = Mock()

        result = process.shutdown()
        assert result is True
        assert process.is_initialized is False

    def test_shutdown_sets_stopped_status(self):
        process = self._make_process_with_mocked_init()
        process.is_initialized = True
        process._stop_system_threads = Mock()
        process.update_process_state = Mock()

        process.shutdown()
        process.update_process_state.assert_called_with(status=ProcessStatus.STOPPED.value)


class TestProcessModuleRunStop:
    def _make_process_no_log(self, name="test_proc"):
        """Процесс с замоканным методом log (proxy не создан без logger_manager)."""
        process = ProcessModule(name)
        process.log = Mock()
        return process

    def test_run_starts_workers(self):
        process = self._make_process_no_log()
        process.worker_manager = Mock()
        process.update_process_state = Mock()

        process.run()

        process.update_process_state.assert_called_with(status=ProcessStatus.RUNNING.value)
        process.worker_manager.start_all_workers.assert_called_once()

    def test_stop_sets_flag(self):
        process = self._make_process_no_log()
        process.worker_manager = Mock()
        process.update_process_state = Mock()
        process._lifecycle.shutdown = Mock(return_value=True)

        process.stop()

        assert process._stop_requested is True
        process.update_process_state.assert_called_with(status=ProcessStatus.STOPPING.value)

    def test_should_stop_false_initially(self):
        process = ProcessModule("test_proc")
        assert process.should_stop() is False

    def test_should_stop_true_after_stop(self):
        process = ProcessModule("test_proc")
        process._stop_requested = True
        assert process.should_stop() is True


# P4.4.1 (B2): TestCommandHandlerReply удалён — closure _make_command_handler снят,
# reply делает транспорт (RouterManager._dispatch_command). Покрытие reply/
# manages_own_reply/fallback — в router_module/tests/test_router_manager.py
# (TestDispatchCommand).


class TestBuiltinCommandsReachableViaCommandManager:
    """P4.4.1 (B2): builtin-команды (worker.*/introspect.*), регистрируемые в run(),
    живут в CommandManager и достижимы через kind-router (type==command →
    CommandManager) в RouterManager.receive().

    Раньше требовался ре-синк копий команд в event_dispatcher
    (register_commands_with_router) — удалён: дупликация реестра устранена,
    CommandManager — единственный владелец командных ключей.
    """

    def test_builtin_commands_in_command_manager_after_run(self):
        sr = make_mock_shared_resources()
        process = ProcessModule("reach_proc", shared_resources=sr, config={})
        assert process.initialize() is True
        process.run()  # регистрирует BuiltinCommands
        try:
            cm = process.command_manager
            cm_keys = {c.get("key") for c in cm.get_commands()}

            for key in (
                "introspect.handlers",
                "introspect.registers",
                "introspect.status",
                "worker.create",
                "worker.remove",
                "wire.configure",
            ):
                assert key in cm_keys, f"{key} нет в CommandManager"
                # kind-router нашёл бы реальный handler (не молчаливый дроп)
                assert cm.get_command_info(key) is not None, f"{key} не резолвится в CM"
        finally:
            process.shutdown()
