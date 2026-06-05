"""
Жизненный цикл процесса.

Helper-функции для инициализации и завершения работы (ADR-PM-009).
Оркестрация перенесена в ProcessModule.initialize().

Контракт: init_configuration() и init_queues() ЧИТАЮТ из self.process,
создают объекты и ВОЗВРАЩАЮТ результат. ProcessModule сам присваивает атрибуты.
"""

from ..types import ProcessStatus


class ProcessLifecycle:
    """
    Helper-класс жизненного цикла процесса.

    Инкапсулирует логику инициализации конфигурации, очередей и завершения работы.
    Оркестрация (порядок вызовов) — ответственность ProcessModule.
    """

    def __init__(self, process):
        """
        Инициализация жизненного цикла.

        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process

    def init_configuration(self) -> tuple:
        """Инициализация конфигурации процесса (return-based, ADR-PM-009).

        Читает из self.process (name, shared_resources, config).
        НЕ пишет в self.process.*.

        Returns:
            tuple: (config_handler, config_manager, config_dict)
        """
        from ..configs import ProcessConfigHandler
        from ...config_module import ConfigManager

        config_handler = ProcessConfigHandler(
            self.process.name,
            self.process.shared_resources,
            self.process.config,
        )
        config_manager = ConfigManager()
        config_handler.config_manager = config_manager
        config_dict = config_handler.data if config_handler else {}

        return config_handler, config_manager, config_dict

    def init_queues(self) -> tuple:
        """Инициализация очередей процесса (return-based, ADR-PM-009).

        Основной путь: очереди уже созданы через
        SharedResourcesManager.register_process() → QueueRegistry.create_and_register_queues()
        и хранятся в ProcessData. Здесь они просто извлекаются.

        Fallback: если shared_resources не передан (тесты, standalone),
        создаются локальные multiprocessing.Queue.

        Читает из self.process (name, shared_resources).
        НЕ пишет в self.process.*.

        Returns:
            tuple: (queues, queue_registry, memory_manager)
        """
        process_data = None
        if self.process.shared_resources:
            process_data = self.process.shared_resources.get_process_data(self.process.name)

        if process_data and process_data.queues:
            queues_dict = {}
            for queue_type in process_data.queues.keys():
                queue = process_data.get_queue(queue_type)
                if queue:
                    queues_dict[queue_type] = queue
            queues = queues_dict if queues_dict else None
        else:
            queues = None

        # Fallback: создать локальные очереди если не получены из SRM
        if not queues:
            from multiprocessing import Queue

            queues = {
                "system": Queue(maxsize=100),
                "data": Queue(maxsize=50),
                "broadcast": Queue(maxsize=20),
                "custom": Queue(maxsize=20),
            }

        if self.process.shared_resources:
            queue_registry = getattr(self.process.shared_resources, "queue_registry", None)
            memory_manager = getattr(self.process.shared_resources, "memory_manager", None)
        else:
            queue_registry = None
            memory_manager = None

        return queues, queue_registry, memory_manager

    # P4.4.1 (B2): register_commands_with_router + _make_command_handler УДАЛЕНЫ.
    # Раньше они КОПИРОВАЛИ все команды CommandManager в router.message_dispatcher
    # (через generic-closure с reply_to_request). После kind-router'а команды
    # (type=="command") диспатчатся напрямую в CommandManager из RouterManager.receive()
    # (`_dispatch_command`), а reply делает транспорт по request_id — копии в
    # message_dispatcher больше не нужны (дупликация реестра устранена). CommandManager —
    # единственный владелец командных ключей.

    def shutdown(self) -> bool:
        """
        Завершение работы процесса.

        Returns:
            bool: True если завершение успешно
        """
        try:
            # 1. Устанавливаем флаг остановки
            self.process._stop_requested = True

            # 1b. Снять контекст логирования
            logger = self.process.get_manager("logger")
            if logger and hasattr(logger, "pop_context"):
                logger.pop_context()

            # 2. Останавливаем системные потоки
            self.process._stop_system_threads()

            # 3. Останавливаем воркеры
            if self.process.worker_manager:
                self.process.worker_manager.stop_all_workers()

            # 3b. Завершаем SharedResourcesManager (unlink SharedMemory на macOS/Linux)
            if self.process.shared_resources and hasattr(self.process.shared_resources, "shutdown"):
                try:
                    self.process.shared_resources.shutdown()
                except Exception as e:
                    self.process._log_error(f"SRM shutdown error: {e}")

            # 4. Завершаем менеджеры
            if self.process.console_manager:
                self.process.console_manager.shutdown()
            if self.process.logger_manager:
                self.process.logger_manager.shutdown()
            if self.process.command_manager:
                self.process.command_manager.shutdown()
            if self.process.router_manager:
                self.process.router_manager.shutdown()

            # 5. Обновляем статус процесса
            self.process.update_process_state(status=ProcessStatus.STOPPED.value)

            self.process.is_initialized = False
            self.process._log_info(f"Process '{self.process.name}' shut down successfully")
            return True

        except Exception as e:
            self.process._log_error(f"Error during shutdown of process '{self.process.name}': {e}")
            return False
