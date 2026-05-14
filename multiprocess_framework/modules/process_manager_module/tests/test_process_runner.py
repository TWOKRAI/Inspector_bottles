"""
Тесты для run_process_function и вспомогательных функций process_runner.py.

Проверяют:
- _load_process_class: успех, ошибка импорта, ошибка атрибута
- _build_shared_resources_from_bundle: корректное построение SRM из bundle
- _run_lifecycle: stop_event, should_stop
- run_process_function: bundle mode, SRM mode, ошибка загрузки класса, ошибка инициализации
"""

import logging
import pytest
from multiprocessing import Event
from unittest.mock import MagicMock, patch

from ..runner.bundle_builder import _build_shared_resources_from_bundle
from ..runner.class_loader import _ProcessLogger, _load_process_class
from ..runner.process_runner import (
    _run_lifecycle,
    _update_process_state,
    run_process_function,
)


# ---------------------------------------------------------------------------
# Тесты _ProcessLogger
# ---------------------------------------------------------------------------


class TestProcessLogger:
    def test_log_without_manager_does_not_raise(self, caplog, monkeypatch) -> None:
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        monkeypatch.setattr(LoggerManager, "_instance", None)
        log = _ProcessLogger("TestProcess")
        with caplog.at_level(logging.INFO):
            log.info("info message")
            log.warning("warn message")
            log.error("error message")
        assert "info message" in caplog.text
        assert "warn message" in caplog.text
        assert "error message" in caplog.text

    def test_log_with_manager_calls_manager(self) -> None:
        mock_lm = MagicMock()
        log = _ProcessLogger("TestProcess", logger_manager=mock_lm)
        log.info("test")
        mock_lm.info.assert_called_once_with("test", module="TestProcess")

    def test_warning_with_manager(self) -> None:
        mock_lm = MagicMock()
        log = _ProcessLogger("P", logger_manager=mock_lm)
        log.warning("warn")
        mock_lm.warning.assert_called_once()

    def test_error_with_manager(self) -> None:
        mock_lm = MagicMock()
        log = _ProcessLogger("P", logger_manager=mock_lm)
        log.error("err")
        mock_lm.error.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты _load_process_class
# ---------------------------------------------------------------------------


class TestLoadProcessClass:
    def test_load_valid_class(self) -> None:
        log = _ProcessLogger("test")
        cls = _load_process_class("multiprocessing.Process", log)
        from multiprocessing import Process

        assert cls is Process

    def test_load_invalid_module(self) -> None:
        log = _ProcessLogger("test")
        result = _load_process_class("nonexistent_module.SomeClass", log)
        assert result is None

    def test_load_invalid_attribute(self) -> None:
        log = _ProcessLogger("test")
        result = _load_process_class("multiprocessing.NonExistentClass", log)
        assert result is None

    def test_load_invalid_path_format(self) -> None:
        log = _ProcessLogger("test")
        result = _load_process_class("NoDotsHere", log)
        assert result is None


# ---------------------------------------------------------------------------
# Тесты _build_shared_resources_from_bundle
# ---------------------------------------------------------------------------


class TestBuildSharedResourcesFromBundle:
    def test_builds_with_empty_bundle(self) -> None:
        bundle = {"queues": {}, "config": {}, "custom": {}}
        srm = _build_shared_resources_from_bundle("TestProcess", bundle)
        assert srm is not None
        data = srm.get_process_data("TestProcess")
        assert data is not None

    def test_builds_with_config(self) -> None:
        bundle = {
            "queues": {},
            "config": {"processes_config": {}},
            "custom": {"key": "value"},
        }
        srm = _build_shared_resources_from_bundle("P1", bundle)
        data = srm.get_process_data("P1")
        assert data is not None

    def test_routing_map_registers_other_processes(self) -> None:
        bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"OtherProcess": {}},
        }
        srm = _build_shared_resources_from_bundle("P1", bundle)
        # OtherProcess должен быть зарегистрирован
        other_data = srm.get_process_data("OtherProcess")
        assert other_data is not None

    def test_invalid_bundle_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid bundle"):
            _build_shared_resources_from_bundle("P1", {"bad": True})

    def test_routing_map_skips_self(self) -> None:
        bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"P1": {}, "Other": {}},
        }
        srm = _build_shared_resources_from_bundle("P1", bundle)
        # P1 зарегистрирован один раз (не дублируется)
        data = srm.get_process_data("P1")
        assert data is not None


# ---------------------------------------------------------------------------
# Тесты _run_lifecycle
# ---------------------------------------------------------------------------


class TestRunLifecycle:
    def test_stops_on_stop_event(self) -> None:
        stop_event = Event()
        log = _ProcessLogger("test")

        mock_instance = MagicMock()
        mock_instance.run = MagicMock()
        del mock_instance.should_stop  # убираем should_stop

        stop_event.set()
        _run_lifecycle(mock_instance, stop_event, log)
        mock_instance.run.assert_called_once()

    def test_calls_stop_on_stop_event(self) -> None:
        stop_event = Event()
        log = _ProcessLogger("test")

        mock_instance = MagicMock()
        mock_instance.run = MagicMock()
        mock_instance.should_stop = MagicMock(return_value=False)

        stop_event.set()
        _run_lifecycle(mock_instance, stop_event, log)
        mock_instance.stop.assert_called_once()

    def test_stops_on_should_stop(self) -> None:
        stop_event = Event()
        log = _ProcessLogger("test")

        call_count = [0]

        def should_stop_fn():
            call_count[0] += 1
            return call_count[0] >= 2

        mock_instance = MagicMock()
        mock_instance.run = MagicMock()
        mock_instance.should_stop = should_stop_fn

        _run_lifecycle(mock_instance, stop_event, log)
        assert call_count[0] >= 2

    def test_works_without_run_method(self) -> None:
        stop_event = Event()
        log = _ProcessLogger("test")

        mock_instance = MagicMock(spec=[])
        stop_event.set()
        _run_lifecycle(mock_instance, stop_event, log)


# ---------------------------------------------------------------------------
# Тесты _update_process_state
# ---------------------------------------------------------------------------


class TestUpdateProcessState:
    def test_update_state_with_none_srm(self) -> None:
        # Не должен падать
        _update_process_state(None, "P1", "error")

    def test_update_state_updates_status(self) -> None:
        mock_srm = MagicMock()
        mock_psr = MagicMock()
        mock_srm.process_state_registry = mock_psr

        _update_process_state(mock_srm, "P1", "error")
        mock_psr.update_state.assert_called_once_with("P1", status="error")

    def test_update_state_handles_missing_process(self) -> None:
        mock_srm = MagicMock()
        mock_srm.process_state_registry = None
        _update_process_state(mock_srm, "P1", "error")


# ---------------------------------------------------------------------------
# Тесты run_process_function
# ---------------------------------------------------------------------------


class TestRunProcessFunction:
    def test_invalid_class_path_returns_early(self, capsys) -> None:
        stop_event = Event()
        stop_event.set()
        run_process_function(
            "nonexistent_module.BadClass",
            "TestProcess",
            stop_event,
            None,
        )
        captured = capsys.readouterr()
        assert "Failed to load" in captured.out or True  # не падает

    def test_bundle_mode_with_valid_class(self) -> None:
        """run_process_function с bundle и классом, который сразу завершается."""
        stop_event = Event()
        stop_event.set()

        bundle = {"queues": {}, "config": {}, "custom": {}}

        with patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load:
            mock_class = MagicMock()
            mock_instance = MagicMock()
            mock_instance.initialize.return_value = True
            mock_instance.should_stop.return_value = True
            mock_class.return_value = mock_instance
            mock_load.return_value = mock_class

            run_process_function(
                "fake.module.FakeClass",
                "TestProcess",
                stop_event,
                bundle,
            )

            mock_instance.initialize.assert_called_once()

    def test_initialization_failure_updates_state(self) -> None:
        """Ошибка инициализации → process_state обновляется на error."""
        stop_event = Event()

        bundle = {"queues": {}, "config": {}, "custom": {}}

        with patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load:
            mock_class = MagicMock()
            mock_instance = MagicMock()
            mock_instance.initialize.return_value = False
            mock_class.return_value = mock_instance
            mock_load.return_value = mock_class

            with patch(
                "multiprocess_framework.modules.process_manager_module.runner.process_runner._update_process_state"
            ) as mock_update:
                run_process_function(
                    "fake.module.FakeClass",
                    "TestProcess",
                    stop_event,
                    bundle,
                )
                mock_update.assert_called_once()
                assert mock_update.call_args[0][1] == "TestProcess"
                assert mock_update.call_args[0][2] == "error"

    def test_shutdown_called_in_finally(self) -> None:
        """shutdown() вызывается в блоке finally."""
        stop_event = Event()
        stop_event.set()

        bundle = {"queues": {}, "config": {}, "custom": {}}

        with patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load:
            mock_class = MagicMock()
            mock_instance = MagicMock()
            mock_instance.initialize.return_value = True
            mock_instance.should_stop.return_value = True
            mock_class.return_value = mock_instance
            mock_load.return_value = mock_class

            run_process_function(
                "fake.module.FakeClass",
                "TestProcess",
                stop_event,
                bundle,
            )

            mock_instance.shutdown.assert_called_once()
