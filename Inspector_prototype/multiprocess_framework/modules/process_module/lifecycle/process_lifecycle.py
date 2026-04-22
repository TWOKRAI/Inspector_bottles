"""
Жизненный цикл процесса.

Отвечает за инициализацию и завершение работы процесса.
"""

import traceback
from ..types import ProcessStatus


class ProcessLifecycle:
    """
    Управление жизненным циклом процесса.
    
    Инкапсулирует логику инициализации и завершения работы.
    """
    
    def __init__(self, process):
        """
        Инициализация жизненного цикла.
        
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process

    def _init_configuration(self) -> None:
        """Инициализация конфигурации процесса."""
        from ..configs import ProcessConfigHandler
        from ...config_module import ConfigManager

        self.process.config_handler = ProcessConfigHandler(
            self.process.name,
            self.process.shared_resources,
            self.process.config,
        )
        self.process.config_manager = ConfigManager()
        self.process.config_handler.config_manager = self.process.config_manager
        self.process.config = (
            self.process.config_handler.data if self.process.config_handler else {}
        )

    def _init_queues(self) -> None:
        """Инициализация очередей процесса.

        Основной путь: очереди уже созданы через
        SharedResourcesManager.register_process() → QueueRegistry.create_and_register_queues()
        и хранятся в ProcessData. Здесь они просто извлекаются.

        Fallback: если shared_resources не передан (тесты, standalone),
        создаются локальные multiprocessing.Queue.
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
            self.process.queues = queues_dict if queues_dict else None
        else:
            self.process.queues = None

        # Fallback: создать локальные очереди если не получены из SRM
        if not self.process.queues:
            from multiprocessing import Queue
            self.process.queues = {
                "system": Queue(maxsize=100),
                "data": Queue(maxsize=50),
                "broadcast": Queue(maxsize=20),
                "custom": Queue(maxsize=20),
            }

        if self.process.shared_resources:
            self.process.queue_registry = getattr(
                self.process.shared_resources, "queue_registry", None
            )
            self.process.memory_manager = getattr(
                self.process.shared_resources, "memory_manager", None
            )
        else:
            self.process.queue_registry = None
            self.process.memory_manager = None

    def initialize(self) -> bool:
        """
        Инициализация процесса.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # 1–2. Конфигурация и очереди (через process для мокаемости в тестах)
            self.process._init_configuration()
            self.process._init_queues()
            
            # 3. Инициализация менеджеров через ObservableMixin
            self.process._init_managers()
            
            # 4. Инициализация коммуникации
            self.process._init_communication()
            
            # 5. Регистрация состояния процесса
            self.process._register_process_state()
            
            # 6. Воркеры и кастомные менеджеры — до message_processor,
            #    чтобы register_message_handler успел зарегистрироваться
            self.process._init_custom_managers()
            self.process._init_application_threads()
            
            # 6b. Связать command_manager с router.message_dispatcher — иначе команды из очередей не обрабатываются
            self._register_commands_with_router()
            
            # 7. Системные потоки (message_processor) — после воркеров
            self.process._init_system_threads()
            
            # 8. Обновляем статус на "ready"
            self.process.update_process_state(status=ProcessStatus.READY.value)

            # 9. Контекст логирования (proc_name в extra для логов)
            logger = self.process.get_manager("logger")
            if logger and hasattr(logger, "push_context"):
                logger.push_context(proc_name=self.process.name)

            self.process.is_initialized = True
            self.process._log_info(f"Process '{self.process.name}' initialized successfully")
            return True

        except Exception as e:
            error_trace = traceback.format_exc()
            self.process._log_error(f"Failed to initialize process '{self.process.name}': {e}")
            self.process._log_error(f"Traceback: {error_trace}")
            print(f"[ProcessLifecycle] Init failed: {e}\n{error_trace}")
            return False
    
    def _register_commands_with_router(self) -> None:
        """Регистрирует все команды command_manager в router.message_dispatcher.
        Без этого команды из очередей (например start_capture от GUI) не доходят до обработчиков.
        """
        if not self.process.command_manager or not self.process.router_manager:
            return
        try:
            commands = self.process.command_manager.get_commands()
            cm = self.process.command_manager
            for cmd_info in commands:
                key = cmd_info.get("key") or cmd_info.get("key_pattern")
                if not key:
                    continue
                self.process.router_manager.register_message_handler(
                    key,
                    lambda msg, _cm=cm: _cm.handle_command(msg),
                    expects_full_message=True,
                )
            if commands:
                self.process._log_info(
                    f"Registered {len(commands)} command(s) with router: "
                    f"{[c.get('key','') for c in commands]}"
                )
        except Exception as e:
            self.process._log_warning(f"Failed to register commands with router: {e}")
    
    def shutdown(self) -> bool:
        """
        Завершение работы процесса.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # 1. Устанавливаем флаг остановки
            self.process.stop_process = True

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
            if self.process.shared_resources and hasattr(
                self.process.shared_resources, "shutdown"
            ):
                try:
                    self.process.shared_resources.shutdown()
                except Exception as e:
                    self.process._log_error(f"SRM shutdown error: {e}")
                    print(f"[ProcessLifecycle] SRM shutdown error: {e}", flush=True)

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

