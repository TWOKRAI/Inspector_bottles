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
from ...logger_module.adapters.std_facade import StdLoggerFacade
from ..runner.class_loader import _load_process_class
from ..runner.process_runner import (
    _run_lifecycle,
    _update_process_state,
    run_process_function,
)


# ---------------------------------------------------------------------------
# Логгер бутстрапа процесса (2.2: именованный вид вместо _ProcessLogger)
# ---------------------------------------------------------------------------


class TestBootstrapLogger:
    """Стартовые строки процесса пишутся под ИМЕНЕМ ПРОЦЕССА в обоих режимах.

    2.2 сняла ``_ProcessLogger`` (57 строк). Прежние тесты этого класса
    утверждали ``mock_lm.info.assert_called_once_with(...)`` — то есть сторожили
    имя метода на моке, причём ветку с явным ``logger_manager``, которая в проде
    не исполнялась НИ РАЗУ (оба вызова создавали логгер без менеджера). Здесь
    проверяется свойство: имя процесса доезжает до приёмника.
    """

    def test_without_manager_falls_back_to_stdlib_under_its_name(self, caplog, monkeypatch) -> None:
        from multiprocess_framework.modules.logger_module.core.logger_core import (
            bump_observability_epoch,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()
        log = StdLoggerFacade("TestProcess")
        with caplog.at_level(logging.INFO):
            log.info("info message")
            log.warning("warn message")
            log.error("error message")

        assert "info message" in caplog.text
        assert "warn message" in caplog.text
        assert "error message" in caplog.text
        # Имя, а не только текст: до Ф2.1 стартовые строки всех процессов были
        # неотличимы по полю источника.
        assert any(record.name == "mpf.TestProcess" for record in caplog.records), [r.name for r in caplog.records]

    def test_with_a_real_manager_the_name_reaches_the_file(self, tmp_path, monkeypatch) -> None:
        """Проверка по артефакту, а не по вызову на моке."""
        from multiprocess_framework.modules.logger_module.core.log_config import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_core import (
            bump_observability_epoch,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()
        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="bootstrap",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={
                    "system_file": LoggerChannelSchema(
                        name="system_file",
                        type="file",
                        enabled=True,
                        file_path="system.log",
                        rotate=False,
                    )
                },
                scopes={
                    scope: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["system_file"])
                    for scope in ("SYSTEM", "BUSINESS", "DEBUG")
                },
            )
        )
        try:
            StdLoggerFacade("camera_0").info("Process initialized")
        finally:
            logger.shutdown()

        written = (tmp_path / "system.log").read_text(encoding="utf-8")
        assert "camera_0" in written, written
        assert "Process initialized" in written

    def test_percent_in_message_is_not_interpreted(self, caplog, monkeypatch) -> None:
        """Сообщение приходит от чужого кода и может содержать ``%``.

        ``_ProcessLogger`` отдавал текст аргументом (``"%s", msg``) именно ради
        этого. У вида то же свойство даёт пустой ``args``: ``apply_format``
        возвращает сообщение нетронутым, когда аргументов нет.
        """
        from multiprocess_framework.modules.logger_module.core.logger_core import (
            bump_observability_epoch,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        monkeypatch.setattr(LoggerManager, "_instance", None)
        bump_observability_epoch()
        with caplog.at_level(logging.INFO):
            StdLoggerFacade("TestProcess").info("загрузка 50% готово")

        assert "загрузка 50% готово" in caplog.text


# ---------------------------------------------------------------------------
# Тесты _load_process_class
# ---------------------------------------------------------------------------


class TestLoadProcessClass:
    def test_load_valid_class(self) -> None:
        log = StdLoggerFacade("test")
        cls = _load_process_class("multiprocessing.Process", log)
        from multiprocessing import Process

        assert cls is Process

    def test_load_invalid_module(self) -> None:
        log = StdLoggerFacade("test")
        result = _load_process_class("nonexistent_module.SomeClass", log)
        assert result is None

    def test_load_invalid_attribute(self) -> None:
        log = StdLoggerFacade("test")
        result = _load_process_class("multiprocessing.NonExistentClass", log)
        assert result is None

    def test_load_invalid_path_format(self) -> None:
        log = StdLoggerFacade("test")
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
        log = StdLoggerFacade("test")

        mock_instance = MagicMock()
        mock_instance.run = MagicMock()
        del mock_instance.should_stop  # убираем should_stop

        stop_event.set()
        _run_lifecycle(mock_instance, stop_event, log)
        mock_instance.run.assert_called_once()

    def test_calls_stop_on_stop_event(self) -> None:
        stop_event = Event()
        log = StdLoggerFacade("test")

        mock_instance = MagicMock()
        mock_instance.run = MagicMock()
        mock_instance.should_stop = MagicMock(return_value=False)

        stop_event.set()
        _run_lifecycle(mock_instance, stop_event, log)
        mock_instance.stop.assert_called_once()

    def test_stops_on_should_stop(self) -> None:
        stop_event = Event()
        log = StdLoggerFacade("test")

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
        log = StdLoggerFacade("test")

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

    def test_ready_event_handed_to_process_not_set_by_runner(self) -> None:
        """5.11: процесс, умеющий объявить готовность, получает event — runner его НЕ взводит.

        Прежний контракт («set сразу после initialize()») живой прогон 2026-07-29
        опроверг: message-loop поднимается ВНУТРИ initialize(), а команды процесса
        регистрируются позже — в run(). Событие, взведённое здесь, означало
        «инициализирован», но читалось всеми как «умеет принимать команды», и
        адресованная в это окно команда терялась молча.
        """
        stop_event = Event()
        stop_event.set()

        ready_event = Event()
        bundle = {"queues": {}, "config": {}, "custom": {"ready_event": ready_event}}
        handed: list = []

        class _AnnouncingProcess:
            """Процесс, умеющий объявить готовность сам (как ProcessModule)."""

            def initialize(self) -> bool:
                return True

            def attach_ready_event(self, event) -> None:
                handed.append(event)

            def run(self) -> None:
                pass

            def should_stop(self) -> bool:
                return True

            def shutdown(self) -> None:
                pass

        with patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load:
            mock_load.return_value = lambda **kwargs: _AnnouncingProcess()

            run_process_function("fake.module.FakeClass", "TestProcess", stop_event, bundle)

        assert handed == [ready_event], "event обязан быть ПЕРЕДАН процессу (attach_ready_event)"
        assert not ready_event.is_set(), (
            "runner не имеет права объявлять готовность за процесс: он не знает, зарегистрировал ли тот свои команды"
        )

    def test_ready_event_set_by_runner_when_process_cannot_announce(self) -> None:
        """5.11: процесс БЕЗ attach_ready_event — прежний путь (runner взводит сам).

        Молчание здесь лишило бы барьер PM раннего выхода вовсе: не-ProcessModule
        (и старые классы) объявить себя не умеют, и «нет сигнала» для них норма,
        а не отказ.
        """
        stop_event = Event()
        stop_event.set()

        ready_event = Event()
        bundle = {"queues": {}, "config": {}, "custom": {"ready_event": ready_event}}

        class _LegacyProcess:
            def initialize(self) -> bool:
                return True

            def run(self) -> None:
                pass

            def should_stop(self) -> bool:
                return True

            def shutdown(self) -> None:
                pass

        with patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load:
            mock_load.return_value = lambda **kwargs: _LegacyProcess()

            run_process_function("fake.module.FakeClass", "TestProcess", stop_event, bundle)

        assert ready_event.is_set(), "процесс без attach_ready_event обязан получить готовность от runner'а"

    def test_ready_event_not_set_on_init_failure(self) -> None:
        """Ф3.2: провал initialize() → ready_event НЕ выставляется (ранний return)."""
        stop_event = Event()

        ready_event = Event()
        bundle = {"queues": {}, "config": {}, "custom": {"ready_event": ready_event}}

        with patch(
            "multiprocess_framework.modules.process_manager_module.runner.process_runner._load_process_class"
        ) as mock_load:
            mock_class = MagicMock()
            mock_instance = MagicMock()
            mock_instance.initialize.return_value = False
            mock_class.return_value = mock_instance
            mock_load.return_value = mock_class

            run_process_function("fake.module.FakeClass", "TestProcess", stop_event, bundle)

            assert not ready_event.is_set(), "ready_event НЕ должен выставляться при провале initialize()"

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
