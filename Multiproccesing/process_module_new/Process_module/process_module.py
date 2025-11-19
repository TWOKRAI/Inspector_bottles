from multiprocessing import Queue
import time
import queue

from command_manager import CommandManager
from worker_manager import WorkerManager, ThreadConfig, ThreadPriority
from logger_manager_batch import LoggerManager
from Multiproccesing.process_module_new.Message_module.message_manager import MessageManager
from router_manager import UniversalRouterManager

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
            process_manager.register_process(self)
    
    def _init_core_managers(self):
        """Инициализация основных менеджеров"""
        self.worker_manager = WorkerManager(self.name)
        self.message_manager = MessageManager(self.name)
        self.command_manager = CommandManager(self.name)
        self.logger_manager = LoggerManager()
        self.router = UniversalRouterManager("internal")
        
        # Регистрация менеджеров
        self.register_manager("workers", self.worker_manager)
        self.register_manager("messages", self.message_manager)
        self.register_manager("commands", self.command_manager)
        self.register_manager("logger", self.logger_manager)
        self.register_manager("router", self.router)
        
        # Настройка интеграции
        self._setup_managers_integration()

    def _setup_managers_integration(self):
        """Настройка взаимодействия между менеджерами"""
        # Регистрируем каналы доставки в роутере
        self.router.register_delivery_channel("queue", self._deliver_via_queue)
        self.router.register_delivery_channel("internal", self._deliver_internal)
        self.router.register_delivery_channel("log", self._deliver_log)
        
        # Регистрируем обработчики входящих сообщений
        self.router.register_receive_handler("command", self.command_manager.handle_message)
        self.router.register_receive_handler("log", self.logger_manager.handle_log_message)

    def _deliver_via_queue(self, target: str, message: Dict) -> bool:
        """Доставка через межпроцессные очереди"""
        try:
            if self.process_manager and hasattr(self.process_manager, 'queue_registry'):
                return self.process_manager.queue_registry.send_to_queue(target, 'system', message)
            return False
        except Exception as e:
            self._fallback_log("ERROR", f"Queue delivery failed to {target}: {e}", "router")
            return False

    def _deliver_internal(self, target: str, message: Dict) -> bool:
        """Внутренняя доставка (в этом же процессе)"""
        try:
            # Передаем сообщение соответствующему менеджеру
            msg_type = message.get('type')
            if msg_type == 'command':
                self.command_manager.handle_message(message)
            elif msg_type == 'log':
                self.logger_manager.handle_log_message(message)
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"Internal delivery failed: {e}", "router")
            return False

    def _deliver_log(self, target: str, message: Dict) -> bool:
        """Доставка логов в LoggerManager"""
        try:
            self.logger_manager.handle_log_message(message)
            return True
        except Exception as e:
            print(f"Log delivery failed: {e}")  # Фолбэк - консоль
            return False

    def _fallback_log(self, level: str, message: str, module: str):
        """Резервное логирование при недоступности роутера"""
        try:
            log_message = self.message_manager.create_log_message(level, message, module)
            self.router.route_message(log_message)
        except:
            print(f"[{level}] {module}: {message}")  # Последний фолбэк

    def _init_system_threads(self):
        """Инициализация системных потоков"""
        # Основной поток обработки сообщений
        self.worker_manager.create_worker(
            "message_processor",
            self._message_processing_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True
        )
        
        # Поток обработки логов
        self.worker_manager.create_worker(
            "log_processor", 
            self.logger_manager.process_logs,
            ThreadConfig(priority=ThreadPriority.BACKGROUND),
            auto_start=True
        )

    def _message_processing_loop(self, stop_event, pause_event):
        """Цикл обработки входящих сообщений"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            try:
                message_data = self.queues['system'].get_nowait()
                if isinstance(message_data, dict):
                    self.router.route_message(message_data)
                else:
                    # Конвертируем в dict если нужно
                    try:
                        message_dict = message_data.to_dict() if hasattr(message_data, 'to_dict') else dict(message_data)
                        self.router.route_message(message_dict)
                    except Exception as e:
                        self._fallback_log("ERROR", f"Failed to process message: {e}", "router")
            except queue.Empty:
                time.sleep(0.01)

    def _init_custom_managers(self):
        """Для переопределения в дочерних классах"""
        pass

    def _init_application_threads(self):
        """Для переопределения в дочерних классах"""
        pass

    def register_manager(self, name: str, manager):
        self.managers[name] = manager
    
    def register_queue(self, name: str, queue: Queue):
        self.queues[name] = queue

    def run(self):
        self.worker_manager.start_all_workers()
        print(f"[{self.name}] Starting process")
    
    def stop(self):
        print(f"[{self.name}] Stopping process")
        self.stop_process = True
        self.worker_manager.stop_all_workers()

    def get_manager(self, name: str):
        return self.managers.get(name)
    
    def should_stop(self) -> bool:
        return self.stop_process

    def send_message(self, message: Dict) -> Dict:
        """Универсальная отправка через роутер"""
        return self.router.route_message(message)

    def log(self, level: str, message: str, module: str = None):
        """Удобное логирование через роутер"""
        log_msg = self.message_manager.create_log_message(level, message, module)
        return self.router.route_message(log_msg)