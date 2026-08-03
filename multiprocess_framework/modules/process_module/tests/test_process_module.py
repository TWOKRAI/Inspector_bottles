"""
Юнит-тесты для ProcessModule.
"""

from unittest.mock import Mock
from multiprocess_framework.modules.base_manager.types.process_status import ProcessStatus
from multiprocess_framework.modules.process_module import ProcessModule


class TestProcessModule:
    """Тесты для ProcessModule."""

    def test_create_process(self):
        """Тест создания процесса."""
        process = ProcessModule("test_process")

        assert process.manager_name == "test_process"
        assert process.name == "test_process"
        assert process.is_initialized is False

    def test_initialize(self):
        """Тест инициализации процесса."""
        # Мокируем shared_resources
        mock_shared_resources = Mock()
        mock_shared_resources.get_process_data = Mock(return_value=None)
        mock_shared_resources.update_process_state = Mock()

        process = ProcessModule("test_process", shared_resources=mock_shared_resources)

        # Мокируем компоненты которые требуют реальных модулей
        process._init_configuration = Mock()
        process._init_queues = Mock()
        process._init_managers = Mock()
        process._init_communication = Mock()
        process._register_process_state = Mock()
        process._init_system_threads = Mock()
        process._init_custom_managers = Mock()
        process._init_application_threads = Mock()
        process.update_process_state = Mock()

        result = process.initialize()

        assert result is True
        assert process.is_initialized is True

    def test_shutdown(self):
        """Тест завершения процесса."""
        process = ProcessModule("test_process")
        process.is_initialized = True
        process._stop_requested = False

        # Мокируем компоненты
        process._stop_system_threads = Mock()
        process.worker_manager = Mock()
        process.worker_manager.stop_all_workers = Mock()
        process.logger_manager = Mock()
        process.logger_manager.shutdown = Mock()
        process.command_manager = Mock()
        process.command_manager.shutdown = Mock()
        process.router_manager = Mock()
        process.router_manager.shutdown = Mock()
        process.update_process_state = Mock()

        result = process.shutdown()

        assert result is True
        assert process.is_initialized is False
        assert process._stop_requested is True

    def test_run_stop(self):
        """Тест запуска и остановки процесса."""
        process = ProcessModule("test_process")

        # Мокируем компоненты (run/stop вызывают log -> log_info)
        process.worker_manager = Mock()
        process.worker_manager.start_all_workers = Mock()
        process.worker_manager.stop_all_workers = Mock()
        process.update_process_state = Mock()
        process.log = Mock()
        process.shutdown = Mock(return_value=True)

        # Запуск
        process.run()

        assert process._stop_requested is False
        process.worker_manager.start_all_workers.assert_called_once()

        # Остановка
        process.stop()

        assert process._stop_requested is True

    def test_ready_announced_only_after_commands_registered(self):
        """5.11: готовность объявляется, когда команды процесса УЖЕ зарегистрированы.

        Живой прогон 2026-07-29: сигнал ставил runner сразу после ``initialize()``,
        а команды регистрируются в ``run()``. Отправитель, поверивший сигналу, слал
        команду в это окно, ребёнок ронял её (`No handler for key
        'observability.tail.subscribe'`) — и хвост подписчика пропадал молча.

        Проверяется СВОЙСТВО, а не имя вызова: в момент объявления команда,
        ради которой сигнал и читают, обязана быть разрешима.
        """
        process = ProcessModule("test_process")
        process.worker_manager = Mock()
        process.update_process_state = Mock()
        process.log = Mock()
        process.shutdown = Mock(return_value=True)

        registered: list = []
        cm = Mock()
        cm.register_command = Mock(side_effect=lambda name, *a, **k: registered.append(name))
        process.command_manager = cm

        registered_at_announce: list = []
        event = Mock()
        event.set = Mock(side_effect=lambda: registered_at_announce.append(list(registered)))
        process.attach_ready_event(event)

        process.run()
        process.stop()

        assert registered_at_announce, "готовность не объявлена вовсе — барьер PM ушёл бы в liveness-фолбэк"
        assert "observability.tail.subscribe" in registered_at_announce[0], (
            "в момент объявления готовности команда подписки ещё не зарегистрирована — "
            f"сигнал снова опережает обработчик (было зарегистрировано: {len(registered_at_announce[0])})"
        )

    def test_running_status_is_not_announced_before_commands_are_registered(self):
        """6.4б: статус RUNNING не имеет права опережать регистрацию команд.

        Находка Н-5б живого прогона 2026-08-03: ``run()`` выставлял ``RUNNING``
        ПЕРВОЙ строкой, а ``BuiltinCommands.register()`` шёл ниже. В это окно
        ``system_overview`` видел процесс «running» и получал по нему
        ``introspect_failed`` на четырёх ручках. Окно уже чинили однажды через
        ``attach_ready_event``, но на одном пути из трёх: сигнал стал честным,
        статус продолжал врать.

        Проверяется ПОРЯДОК как свойство: сколько команд было зарегистрировано
        к моменту, когда статус стал RUNNING.
        """
        process = ProcessModule("test_process")
        process.worker_manager = Mock()
        process.log = Mock()
        process.shutdown = Mock(return_value=True)

        registered: list = []
        cm = Mock()
        cm.register_command = Mock(side_effect=lambda name, *a, **k: registered.append(name))
        process.command_manager = cm

        registered_at_running: list = []

        def _capture_state(**kwargs):
            if kwargs.get("status") == ProcessStatus.RUNNING.value:
                registered_at_running.append(list(registered))

        process.update_process_state = Mock(side_effect=_capture_state)

        process.run()
        process.stop()

        assert registered_at_running, "статус RUNNING не выставлен вовсе"
        assert "observability.tail.subscribe" in registered_at_running[0], (
            "процесс объявил себя RUNNING до регистрации команд — снаружи это «работает», "
            f"а на introspect.* он отвечает «нет хендлера» (зарегистрировано было: "
            f"{len(registered_at_running[0])})"
        )

    def test_initialize_moves_both_status_planes_to_ready(self):
        """Ф6.х.7г: ``initialize()`` двигает ОБЕ плоскости статуса, не только PSR.

        Прежде PSR получал ``ready``, а ``_current_process_status`` оставался
        ``initializing`` до конца ``run()`` — heartbeat и introspect всё окно
        (у ``GuiProcess`` — вся жизнь Qt-loop) давали два разных ответа на один
        вопрос «процесс готов?».
        """
        process = ProcessModule("test_process")
        captured: list = []
        process.update_process_state = Mock(side_effect=lambda **kw: captured.append(kw.get("status")))

        try:
            assert process.initialize() is True, "initialize() не прошёл на пустом конфиге"
            assert ProcessStatus.READY.value in captured, "PSR не получил ready"
            assert process._current_process_status == ProcessStatus.READY.value, (
                f"вторая плоскость отстала: {process._current_process_status!r}"
            )
        finally:
            process.shutdown()

    def test_status_before_run_is_not_running(self):
        """Вторая половина пары: до ``run()`` процесс НЕ объявляет себя работающим.

        Дефолт ``"running"`` стоял прямо в ``__init__`` — то есть свежесозданный
        объект, у которого ещё не было ни ``initialize()``, ни воркеров, ни
        команд, рапортовал в heartbeat «работаю». Без этой половины первый тест
        зелен и на коде, где статус выставляется в конструкторе и больше нигде.
        """
        process = ProcessModule("test_process")

        assert process._current_process_status != ProcessStatus.RUNNING.value, (
            "процесс объявляет себя работающим из конструктора"
        )
        assert process._current_process_status == ProcessStatus.INITIALIZING.value

    def test_ready_event_absent_is_not_an_error(self):
        """Процесс без переданного события просто не объявляет готовность (SRM-mode)."""
        process = ProcessModule("test_process")
        process.worker_manager = Mock()
        process.update_process_state = Mock()
        process.log = Mock()
        process.shutdown = Mock(return_value=True)

        process.run()  # attach_ready_event не звали — падать не на чем
        process.stop()

        assert process.should_stop() is True

    def test_should_stop(self):
        """Тест проверки флага остановки."""
        process = ProcessModule("test_process")

        assert process.should_stop() is False

        process._stop_requested = True

        assert process.should_stop() is True

    def test_get_config(self):
        """Тест получения конфигурации."""
        process = ProcessModule("test_process", config={"key": "value"})

        # Без config_handler
        value = process.get_config("key")
        assert value == "value"

        # С config_handler
        process.config_handler = Mock()
        process.config_handler.get = Mock(return_value="handler_value")

        value = process.get_config("key")
        assert value == "handler_value"

    def test_update_config(self):
        """Тест обновления конфигурации."""
        process = ProcessModule("test_process", config={"key": "value"})

        process.update_config("key", "new_value")

        assert process.config["key"] == "new_value"

    def test_update_config_reaches_a_live_handler(self):
        """R6: у настоящего процесса ``config_handler`` есть — и запись шла мимо.

        ``Config.update`` принимает СЛОВАРЬ одним позиционным аргументом, а
        ``update_config`` звал его парой ``(key, value)`` → ``TypeError`` у
        любого процесса с обработчиком. Тест выше строит ``ProcessModule`` без
        него и проверяет только ветку ``self.config``, поэтому дефект жил.

        Читаем ТЕМ ЖЕ ``get_config``, каким читают потребители: он ходит в
        обработчик, а не в ``self.config``, и запись «в один из двух» для них
        неотличима от отсутствия записи.
        """
        from multiprocess_framework.modules.process_module.configs.process_config_handler import (
            ProcessConfigHandler,
        )

        process = ProcessModule("test_process", config={"key": "value"})
        process.config_handler = ProcessConfigHandler("test_process", config={"key": "value"})

        process.update_config("key", "new_value")

        assert process.get_config("key") == "new_value"
        assert process.config["key"] == "new_value"

    def test_managers_property(self):
        """Тест свойства managers."""
        process = ProcessModule("test_process")
        process.worker_manager = Mock()
        process.logger_manager = Mock()
        process.command_manager = Mock()
        process.router_manager = Mock()

        managers = process.managers

        assert managers["worker"] == process.worker_manager
        assert managers["logger"] == process.logger_manager
        assert managers["command"] == process.command_manager
        assert managers["router"] == process.router_manager

    def test_register_manager(self):
        """Тест регистрации менеджера."""
        process = ProcessModule("test_process")
        mock_manager = Mock()

        process.register_manager("test_manager", mock_manager)

        # Проверяем что менеджер зарегистрирован через ObservableMixin
        assert process.has_manager("test_manager")
        assert process.get_manager("test_manager") == mock_manager

    def test_get_manager(self):
        """Тест получения менеджера."""
        process = ProcessModule("test_process")
        mock_manager = Mock()

        process.register_manager("test_manager", mock_manager)

        manager = process.get_manager("test_manager")

        assert manager == mock_manager

    def test_log(self):
        """Тест логирования через ObservableMixin."""
        process = ProcessModule("test_process")

        # Приватные методы всегда доступны
        assert hasattr(process, "_log_info")
        assert hasattr(process, "_log_error")

        # Публичные прокси-методы создаются только после регистрации менеджера
        # Регистрируем mock менеджер для теста
        from unittest.mock import Mock

        mock_logger = Mock()
        process.register_manager("logger", mock_logger, enabled=True)

        # Теперь публичные методы должны быть доступны
        assert hasattr(process, "log_info")
        assert hasattr(process, "log_error")

        # Публичные методы вызываются без ошибок
        process.log_info("Test message", module="test_context")
        # Не должно упасть

    def test_get_stats(self):
        """Тест получения статистики процесса."""
        process = ProcessModule("test_process")
        process.is_initialized = True

        # Мокируем компоненты
        process.communication = Mock()
        process.communication.get_queue_stats = Mock(return_value={})
        process.worker_manager = Mock()
        process.worker_manager.get_stats = Mock(return_value={})

        stats = process.get_stats()

        assert stats["manager_name"] == "test_process"
        assert stats["is_initialized"] is True

    def test_send_receive_message(self):
        """Тест отправки и получения сообщений."""
        process = ProcessModule("test_process")

        # Мокируем communication
        process.communication = Mock()
        process.communication.send_message = Mock(return_value=True)
        process.communication.receive_message = Mock(return_value={"data": "test"})

        # Отправка
        result = process.send_message("target", {"data": "test"})
        assert result is True

        # Получение
        message = process.receive_message(timeout=1.0)
        assert message == {"data": "test"}
