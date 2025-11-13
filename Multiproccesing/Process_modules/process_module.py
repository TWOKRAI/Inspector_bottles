from multiprocessing import Queue
from command_manager import CommandManager
from worker_manager import WorkerManager, ThreadConfig, ThreadPriority
from logger_manager_batch import LoggerManager
from module_message import SystemMessage, MessageFactory, MessageType


class ProcessModule:
    def __init__(self, name: str, process_manager: None, config: dict = None):
        self.name = name
        self.process_manager = process_manager
        self.stop_process = False
        self.config = config or {}
        self.stop_process = False

        self.managers = {}
        
        self.queues = {
            'system': Queue(maxsize=100),    
            'data': Queue(maxsize=50),       
            'broadcast': Queue(maxsize=20),  
            'costoum': Queue(maxsize=20),  
        }

        # Обязательная инициализация
        self._init_core_managers()
        self._init_system_threads()
        
        # Опциональная инициализация
        self._init_custom_managers()
        self._init_application_threads()

        # Регистрация в ProcessManager
        self.process_manager.register_process(self)
    
    def _init_core_managers(self):
        self.worker_manager = WorkerManager(self.name)
        self.command_manager = CommandManager(self.name)
        self.logger_manager = LoggerManager()
        
        self.register_manager("workers", self.worker_manager)
        self.register_manager("commands", self.command_manager)
        self.register_manager("logger", self.logger_manager)
        
        # Настраиваем интеграцию между менеджерами
        self._setup_managers_integration()

    def _init_message_handlers(self):
        """Регистрация обработчиков различных типов сообщений"""
        self.message_handlers = {
            MessageType.LOG: self._handle_log_message,
            MessageType.EVENT: self._handle_event_message,
            MessageType.METRIC: self._handle_metric_message,
        }
    
    def _setup_managers_integration(self):
        """Настройка взаимодействия менеджеров через сообщения"""
        # CommandManager отправляет логи через LoggerManager
        def log_from_command(message, *args):
            if hasattr(message, 'log_level'):
                self.logger_manager.handle_log_message(message)
        
        self.command_manager.callbacks['message_failed'].append(log_from_command)
    
    def _handle_log_message(self, log_message: SystemMessage):
        """Обработка лог-сообщений"""
        self.logger_manager.handle_log_message(log_message)
    
    def _handle_event_message(self, event_message: SystemMessage):
        """Обработка событий"""
        # Можно добавить логику обработки событий
        print(f"Event: {event_message.data}")
    
    def _handle_metric_message(self, metric_message: SystemMessage):
        """Обработка метрик"""
        # Можно интегрировать с будущим MetricsManager
        print(f"Metric: {metric_message.data}")
    
    def send_message(self, message: SystemMessage, output_queue: str = None):
        """Универсальная отправка сообщений"""
        return self.command_manager.send_message(message, output_queue)
    
    def log(self, level: str, message: str, module: str = None):
        """Удобный метод для логирования"""
        log_msg = MessageFactory.create_log(
            self.name, level, message, module or self.name
        )
        self.logger_manager.handle_log_message(log_msg)

    def _init_custom_managers(self):
        pass
    
    def _init_system_threads(self):
        # Поток для команд (высокий приоритет)
        self.worker_manager.create_worker(
            "command_processor",
            self.command_manager.process_loop,
            ThreadConfig(priority=ThreadPriority.SYSTEM),
            auto_start=True
        )
        
        # Поток для логирования (реальное время)
        self.worker_manager.create_worker(
            "log_processor",
            self.logger_manager.process_logs,
            ThreadConfig(priority=ThreadPriority.REALTIME),
            auto_start=True
        )
    
    def _init_application_threads(self):
        pass
    
    def register_manager(self, name: str, manager):
        self.managers[name] = manager
    
    def run(self):
        print(f"[{self.name}] Starting process")
        # Все потоки уже запущены через WorkerManager
        print(f"[{self.name}] Process started successfully")
    
    def stop(self):
        print(f"[{self.name}] Stopping process")
        self.stop_process = True
        self.worker_manager.stop_all_workers()
        print(f"[{self.name}] Process stopped")
    
    def get_manager(self, name: str):
        return self.managers.get(name)
    
    def should_stop(self) -> bool:
        return self.stop_process