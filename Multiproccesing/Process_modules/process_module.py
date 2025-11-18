from multiprocessing import Queue
import time
import queue

from command_manager import CommandManager
from worker_manager import WorkerManager, ThreadConfig, ThreadPriority
from logger_manager_batch import LoggerManager
from module_message import SystemMessage, MessageFactory, MessageType, CommandMessage
from router_manager import UniversalRouterManager, DeliveryStatus
from queue_registry import QueueRegistry

class ProcessModule:
    def __init__(self, name: str, process_manager=None, config: dict = None):
        self.name = name
        self.process_manager = process_manager
        self.config = config or {}

        self.stop_process = False

        self.managers = {}
        
        # Очереди этого процесса
        self.queues = {
            'system': Queue(maxsize=100),    
            'data': Queue(maxsize=50),       
            'broadcast': Queue(maxsize=20),  
            'custom': Queue(maxsize=20),  
        }

        # Обязательная инициализация
        self._init_core_managers()
        self._init_system_threads()
        
        # Опциональная инициализация
        self._init_custom_managers()
        self._init_application_threads()

        # Регистрация в ProcessManager
        if process_manager:
            self.process_manager.register_process(self)
            self.process_manager.register_queues(self)
    
    def _init_core_managers(self):
        self.worker_manager = WorkerManager(self.name)
        self.command_manager = CommandManager(self.name)
        self.logger_manager = LoggerManager()
        self.router = UniversalRouterManager("internal")  # Внутренний роутер по умолчанию
        
        self.register_manager("workers", self.worker_manager)
        self.register_manager("commands", self.command_manager)
        self.register_manager("logger", self.logger_manager)
        self.register_manager("router", self.router)
        
        # Настраиваем интеграцию между менеджерами
        self._setup_managers_integration()

    def _setup_managers_integration(self):
        """Настройка взаимодействия менеджеров через роутер"""
        
        # Регистрируем методы отправки в роутере
        self.router.register_send_method("queue", self._send_to_queue)
        self.router.register_send_method("command", self._send_command)
        self.router.register_send_method("log", self._send_log)
        
        # Регистрируем обработчики входящих сообщений
        self.router.register_receive_handler("command", self.command_manager.handle_message)
        self.router.register_receive_handler("log", self.logger_manager.handle_log_message)
        
        # Настраиваем колбэки для CommandManager и LoggerManager
        self._setup_command_manager_callbacks()
        self._setup_logger_manager_callbacks()

    def _setup_command_manager_callbacks(self):
        """Настройка колбэков CommandManager для использования роутера"""
        # CommandManager будет использовать роутер для отправки команд
        original_send = self.command_manager.send_message

        def send_via_router(message, output_queue=None):
            # Преобразуем SystemMessage в dict для роутера
            message_dict = message.to_dict()
            # Добавляем информацию о маршрутизации
            message_dict['routers'] = message_dict.get('routers', [])
            return self.router.route_message(message_dict)

        # Переопределяем метод отправки
        self.command_manager.send_message = send_via_router

    def _setup_logger_manager_callbacks(self):
        """Настройка LoggerManager для использования роутера"""
        # LoggerManager будет использовать роутер для маршрутизации логов
        original_route_log = self.logger_manager.route_log

        def route_log_via_router(level, message, module):
            log_message = {
                "id": f"log_{int(time.time()*1000)}",
                "type": "log",
                "sender": self.name,
                "targets": ["logger"],
                "routers": ["internal"],
                "priority": "low",
                "data": {
                    "level": level,
                    "message": message,
                    "module": module
                },
                "timestamp": time.time()
            }
            return self.router.route_message(log_message)

        # Переопределяем метод маршрутизации логов
        self.logger_manager.route_log = route_log_via_router

    def _send_to_queue(self, target: str, message: Dict) -> bool:
        """Универсальный метод отправки в очередь через QueueRegistry"""
        try:
            # target может быть строкой с именем процесса или кортежем (process_name, queue_type)
            if isinstance(target, str):
                process_name = target
                queue_type = 'system'  # по умолчанию
            elif isinstance(target, tuple) and len(target) == 2:
                process_name, queue_type = target
            else:
                print(f"Invalid target format: {target}")
                return False

            # Используем QueueRegistry из process_manager
            if self.process_manager and hasattr(self.process_manager, 'queue_registry'):
                return self.process_manager.queue_registry.send_to_queue(process_name, queue_type, message)
            else:
                # Fallback: прямая отправка если QueueRegistry недоступен
                print(f"QueueRegistry not available, direct send not implemented")
                return False
                
        except Exception as e:
            print(f"Failed to send to queue {target}: {e}")
            return False

    def _send_command(self, target: str, message: Dict) -> bool:
        """Отправка команды через CommandManager"""
        try:
            # Преобразуем сообщение обратно в CommandMessage
            command_msg = CommandMessage.from_dict(message)
            # Обрабатываем команду локально
            return self.command_manager._execute_command_message(command_msg, "router")
        except Exception as e:
            print(f"Failed to send command to {target}: {e}")
            return False

    def _send_log(self, target: str, message: Dict) -> bool:
        """Отправка лога через LoggerManager"""
        try:
            # Преобразуем сообщение в LogMessage
            log_msg = SystemMessage.from_dict(message)
            # Обрабатываем лог локально
            self.logger_manager.handle_log_message(log_msg)
            return True
        except Exception as e:
            print(f"Failed to send log to {target}: {e}")
            return False

    def _init_system_threads(self):
        # Поток для обработки входящих сообщений через роутер
        self.worker_manager.create_worker(
            "message_processor",
            self._message_processing_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True
        )
        
        # Поток для обработки исходящих сообщений через роутер
        self.worker_manager.create_worker(
            "router_processor",
            self.router.process_incoming_messages,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True
        )

    def _message_processing_loop(self, stop_event, pause_event):
        """Цикл обработки входящих сообщений из системной очереди"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            # Обрабатываем сообщения из системной очереди
            try:
                message_data = self.queues['system'].get_nowait()
                # Передаем сообщение в роутер для обработки
                if isinstance(message_data, dict):
                    self.router.route_message(message_data)
                else:
                    # Пытаемся преобразовать в dict
                    try:
                        if hasattr(message_data, 'to_dict'):
                            message_dict = message_data.to_dict()
                        else:
                            message_dict = dict(message_data)
                        self.router.route_message(message_dict)
                    except Exception as e:
                        print(f"Failed to process message: {e}")
            except queue.Empty:
                pass
                
            time.sleep(0.01)

    def _init_application_threads(self):
        """Метод для переопределения в дочерних классах"""
        pass

    def register_manager(self, name: str, manager):
        self.managers[name] = manager
    
    def register_queue(self, name: str, queue: Queue):
        self.queues[name] = queue

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

    def send_message(self, message: Dict) -> Dict:
        """Универсальная отправка сообщений через роутер"""
        return self.router.route_message(message)

    def log(self, level: str, message: str, module: str = None):
        """Удобный метод для логирования через роутер"""
        log_msg = {
            "id": f"log_{int(time.time()*1000)}",
            "type": "log", 
            "sender": self.name,
            "targets": ["logger"],
            "routers": ["internal"],
            "priority": "low",
            "data": {
                "level": level,
                "message": message,
                "module": module or self.name
            },
            "timestamp": time.time()
        }
        return self.router.route_message(log_msg)