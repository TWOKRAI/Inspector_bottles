"""
Базовый класс для всех процессов системы.

Использует композицию для разделения ответственности:
- ProcessCore - жизненный цикл
- ProcessConfigHandler - конфигурация
- ProcessManagers - управление менеджерами
- ProcessCommunication - коммуникация
"""

import time
from typing import Dict, Any, Optional, List
from multiprocessing import Queue

# Исправляем импорты для избежания ошибок при импорте из других модулей
try:
    from multiprocess_framework.modules.Config_module import ConfigManager
except ImportError:
    # Fallback для случаев когда модуль не найден
    ConfigManager = None

try:
    from multiprocess_framework.modules.Worker_module.worker_manager import ThreadConfig, ThreadPriority
except ImportError:
    ThreadConfig = None
    ThreadPriority = None

# Импорт компонентов
from .core import ProcessCore
from .config_handler import ProcessConfigHandler
from .managers import ManagersComponents
from .communication import ProcessCommunication


class ProcessModule(ProcessCore):
    """
    Базовый класс для всех процессов системы.
    
    Использует композицию для разделения ответственности:
    - ProcessCore - базовый жизненный цикл
    - ProcessConfigHandler - работа с конфигурацией
    - ProcessManagers - управление менеджерами
    - ProcessCommunication - межпроцессная коммуникация
    
    Attributes:
        name: Имя процесса
        config: Конфигурация процесса
        managers: Словарь менеджеров (доступ через managers_component)
        adapters: Словарь адаптеров (доступ через managers_component)
        queues: Словарь очередей для коммуникации
    """
    
    def __init__(
        self, 
        name: str, 
        shared_resources=None, 
        config: dict = None
    ):
        """
        Инициализация процесса.
        
        Args:
            name: Имя процесса
            shared_resources: SharedResourcesManager (легковесный контейнер с ProcessStateRegistry)
            config: Локальная конфигурация процесса (опционально, берется из process_data если не указана)
        """
        # Инициализация ядра
        # ConfigManager создается локально в ProcessCore
        super().__init__(name, shared_resources, config)
        
        # Компоненты процесса
        # ProcessConfigHandler берет конфигурацию из process_data через shared_resources
        self.config_handler = ProcessConfigHandler(name, shared_resources, config)
        # Устанавливаем config_manager в config_handler после создания ProcessCore
        self.config_handler.config_manager = self.config_manager

        self.shared_resources = shared_resources
        
        # Создаем локальные менеджеры как вспомогательные утилиты
        # Они работают с данными из ProcessStateRegistry
        if shared_resources:
            from ..Shared_resources_module.queue_registry import QueueRegistry
            from ..Shared_resources_module.Memory_Manager import ImageMemoryManager
            
            # QueueRegistry создается локально с ссылкой на ProcessStateRegistry
            self.queue_registry = QueueRegistry(process_state_registry=shared_resources.process_state_registry)
            
            # ImageMemoryManager создается локально
            self.memory_manager = ImageMemoryManager()
        else:
            self.queue_registry = None
            self.memory_manager = None
        
        self.managers_component = ManagersComponents(
            name, 
            self.config_handler, 
            shared_resources,
            process=self,  # Передаем ссылку на процесс для адаптеров и queue_registry
            logger_callback=self._fallback_log
        )
        self.communication = None  # Будет создан после инициализации роутера
        
        # Инициализация в правильном порядке
        self.managers_component.initialize_core_managers()
        
        # Обновляем EventManager в shared_resources с router_manager
        if self.shared_resources and self.shared_resources.event_manager:
            self.shared_resources.event_manager.set_router_manager(
                self.managers_component.router_manager
            )
        
        # Создаем компонент коммуникации после инициализации роутера
        self.communication = ProcessCommunication(
            name,
            self.queues,
            self.managers_component.router_manager,
            shared_resources,
            logger_callback=self._fallback_log
        )
        
        # Регистрация очередей
        self.communication.register_process_queues()
        self.communication.register_router_channels()
        
        # Регистрация состояния процесса (initializing)
        self._register_process_state()
        
        # Инициализация системных потоков
        self._init_system_threads()
        
        # Опциональная инициализация для дочерних классов
        self._init_custom_managers()
        self._init_application_threads()
        
        # Обновляем статус на "ready" после полной инициализации
        self.update_process_state(status="ready")
    
    # ========================================================================
    # УДОБНЫЕ СВОЙСТВА ДЛЯ ДОСТУПА К КОМПОНЕНТАМ
    # ========================================================================
    
    @property
    def managers(self):
        """Доступ к менеджерам"""
        return self.managers_component.managers
    
    @property
    def adapters(self):
        """
        Доступ к адаптерам (словарь {manager_name: adapter}).
        
        Note: Рекомендуется использовать доступ через менеджеры:
        process.command_manager.get_adapter() или process.command_adapter
        """
        adapters = {}
        for manager_name, manager in self.managers.items():
            if hasattr(manager, 'get_adapter'):
                adapter = manager.get_adapter()
                if adapter:
                    adapters[manager_name] = adapter
        return adapters
    
    @property
    def worker_manager(self):
        """Доступ к worker_manager"""
        return self.managers_component.worker_manager
    
    @property
    def logger_manager(self):
        """Доступ к logger_manager"""
        return self.managers_component.logger_manager
    
    @property
    def command_manager(self):
        """Доступ к command_manager"""
        return self.managers_component.command_manager
    
    @property
    def router_manager(self):
        """Доступ к router_manager"""
        return self.managers_component.router_manager
    
    @property
    def router(self):
        """Прямой доступ к роутеру для отправки сообщений"""
        return self.router_manager
    
    @property
    def logger_adapter(self):
        """Доступ к logger_adapter через менеджера"""
        return self.logger_manager.get_adapter() if self.logger_manager else None
    
    @property
    def command_adapter(self):
        """Доступ к command_adapter через менеджера"""
        return self.command_manager.get_adapter() if self.command_manager else None
    
    @property
    def router_adapter(self):
        """Доступ к router_adapter через менеджера"""
        return self.router_manager.get_adapter() if self.router_manager else None
    
    # ========================================================================
    # СИСТЕМНЫЕ ПОТОКИ
    # ========================================================================
    
    def _init_system_threads(self):
        """Инициализация системных потоков"""
        # Основной поток обработки сообщений
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker(
            "message_processor",
            self._message_processing_loop,
            config,
            auto_start=True
        )
    
    def _message_processing_loop(self, stop_event, pause_event):
        """
        Цикл обработки входящих сообщений.
        
        Args:
            stop_event: Событие остановки
            pause_event: Событие паузы
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            try:
                # Получаем сообщения из очередей через роутер
                messages = self.router_manager.receive(timeout=0.0)
                
                for message in messages:
                    self._handle_message(message)
                
                # Небольшая пауза чтобы не загружать CPU
                time.sleep(0.01)
                
            except Exception as e:
                self._fallback_log("ERROR", f"Message processing error: {e}", "processor")
                time.sleep(0.1)
    
    def _handle_message(self, message: Dict):
        """
        Обработка входящего сообщения.
        
        Args:
            message: Сообщение для обработки
        """
        try:
            msg_type = message.get('type')
            
            # Маршрутизуем через router для внутренней обработки
            message['channel'] = 'internal'
            result = self.router_manager.send(message)
            
            if result.get('status') == 'error':
                self._fallback_log("ERROR", f"Message handling failed: {result.get('reason')}", "handler")
                
        except Exception as e:
            self._fallback_log("ERROR", f"Message handling error: {e}", "handler")
    
    # ========================================================================
    # ПЕРЕОПРЕДЕЛЯЕМЫЕ МЕТОДЫ ДЛЯ ДОЧЕРНИХ КЛАССОВ
    # ========================================================================
    
    def _init_custom_managers(self):
        """
        Инициализация кастомных менеджеров для дочерних классов.
        
        Переопределите этот метод в дочерних классах для создания
        специализированных менеджеров (например, DatabaseManager, VisionManager и т.д.)
        """
        pass

    def _init_application_threads(self):
        """
        Инициализация функциональных потоков для дочерних классов.
        
        Переопределите этот метод в дочерних классах для создания
        функциональных воркеров, которые выполняют бизнес-логику процесса.
        """
        pass
    
    # ========================================================================
    # РЕГИСТРАЦИЯ СОСТОЯНИЯ ПРОЦЕССА
    # ========================================================================
    
    def _register_process_state(self):
        """
        Регистрация состояния процесса в ProcessStateRegistry.
        
        Вызывается автоматически при инициализации процесса.
        """
        if not self.shared_resources or not hasattr(self.shared_resources, 'process_state_registry'):
            return
        
        try:
            # Получаем имена очередей из локального queue_registry
            queue_names = {}
            if self.queue_registry:
                process_queues = self.queue_registry.get_process_queues(self.name)
                if process_queues:
                    queue_names = {queue_type: f"{self.name}_{queue_type}" for queue_type in process_queues.keys()}
            
            # Регистрируем процесс со статусом "initializing"
            self.shared_resources.register_process_state(
                process_name=self.name,
                initial_state={
                    "status": "initializing",
                    "metadata": {
                        "config": self.config or {},
                        "queues_count": len(self.queues)
                    }
                },
                queue_names=queue_names
            )
            
            self._fallback_log("INFO", f"Process state registered: {self.name}", "state")
        except Exception as e:
            self._fallback_log("WARNING", f"Failed to register process state: {e}", "state")
    
    def update_process_state(
        self,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None
    ):
        """
        Обновление состояния процесса.
        
        Args:
            status: Новый статус процесса (ready, running, stopping, error)
            events: События для добавления
            metadata: Метаданные для обновления
            custom: Кастомные данные для обновления
        """
        if not self.shared_resources or not hasattr(self.shared_resources, 'update_process_state'):
            return
        
        try:
            self.shared_resources.update_process_state(
                process_name=self.name,
                status=status,
                events=events,
                metadata=metadata,
                custom=custom
            )
        except Exception as e:
            self._fallback_log("WARNING", f"Failed to update process state: {e}", "state")
    
    # ========================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ - ДЕЛЕГИРОВАНИЕ К КОМПОНЕНТАМ
    # ========================================================================
    
    def register_manager(self, name: str, manager):
        """Регистрация менеджера"""
        self.managers_component.register_manager(name, manager)
    
    def register_adapter(self, name: str, adapter):
        """Регистрация адаптера"""
        self.managers_component.register_adapter(name, adapter)
    
    def get_manager(self, name: str):
        """Получение менеджера по имени"""
        return self.managers_component.get_manager(name)
    
    def get_adapter(self, name: str):
        """Получение адаптера по имени"""
        return self.managers_component.get_adapter(name)
    
    def reload_manager(self, manager_name: str) -> bool:
        """Пересоздать менеджер на основе текущей конфигурации"""
        return self.managers_component.reload_manager(manager_name)
    
    def update_config(self, new_config: Dict[str, Any]) -> bool:
        """
        Обновить конфигурацию процесса и перезагрузить затронутые менеджеры.
        
        Args:
            new_config: Новая конфигурация
            
        Returns:
            bool: True если обновление успешно
        """
        try:
            # Обновляем конфигурацию
            success = self.config_handler.update_config(new_config)
            if not success:
                return False
            
            # Определяем какие менеджеры нужно перезагрузить
            if 'managers' in new_config:
                managers_to_reload = list(new_config['managers'].keys())
                for manager_name in managers_to_reload:
                    if manager_name in self.managers:
                        self.reload_manager(manager_name)
            
            self._fallback_log("INFO", f"Configuration updated for process '{self.name}'", "config")
            return True
            
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to update configuration: {e}", "config")
            return False
    
    # ========================================================================
    # КОММУНИКАЦИЯ
    # ========================================================================
    
    def send(self, message) -> Dict:
        """
        Универсальная отправка сообщения.
        
        Args:
            message: BaseMessage или Dict
            
        Returns:
            Dict: Результат отправки
        """
        return self.communication.send(message)
    
    def receive(self, timeout: float = 0.01) -> list:
        """
        Получение входящих сообщений из всех каналов.
        
        Args:
            timeout: Таймаут опроса
            
        Returns:
            List[Dict]: Список полученных сообщений
        """
        return self.communication.receive(timeout)
    
    def send_to_process(self, target: str, message: Dict) -> bool:
        """Отправка сообщения конкретному процессу"""
        return self.communication.send_to_process(target, message)
    
    def broadcast_message(self, message: Dict, exclude_self: bool = True) -> int:
        """Рассылка сообщения всем процессам"""
        return self.communication.broadcast(message, exclude_self)
    
    # ========================================================================
    # УДОБНЫЕ МЕТОДЫ
    # ========================================================================
    
    def log(self, level: str, message: str, context: str = None):
        """Логирование через адаптер"""
        adapter = self.logger_adapter
        if adapter:
            adapter.log(level, message, context or self.name)
    
    def execute_command(self, command: str, data: Dict = None) -> Any:
        """Выполнение команды через адаптер"""
        adapter = self.command_adapter
        if adapter:
            return adapter.execute(command, data)
        return None
    
    # ========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def run(self):
        """Запуск процесса"""
        # Обновляем статус на "running"
        self.update_process_state(status="running")
        
        self.worker_manager.start_all_workers()
        self.log("INFO", f"Process '{self.name}' started", "lifecycle")
        print(f"[{self.name}] Process running")
    
    def stop(self):
        """Остановка процесса"""
        # Обновляем статус на "stopping"
        self.update_process_state(status="stopping")
        
        self.log("INFO", f"Process '{self.name}' stopping", "lifecycle")
        print(f"[{self.name}] Stopping process")
        self.stop_process = True
        
        # Останавливаем все воркеры
        if self.worker_manager:
            self.worker_manager.stop_all_workers()
        
        # Останавливаем менеджеры и адаптеры
        self.managers_component.stop_all()
        
        # Отменяем регистрацию очередей
        if self.communication:
            self.communication.unregister_process()
    
    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики процесса.
        
        Returns:
            Dict: Статистика всех компонентов
        """
        stats = {
            "name": self.name,
            "running": not self.stop_process,
        }
        
        # Статистика менеджеров и адаптеров
        stats.update(self.managers_component.get_stats())
        
        # Статистика очередей
        if self.communication:
            stats["queues"] = self.communication.get_queue_stats()
        
        # Статистика воркеров
        if self.worker_manager:
            try:
                stats["workers"] = self.worker_manager.get_stats() if hasattr(self.worker_manager, 'get_stats') else {}
            except Exception as e:
                stats["workers"] = {"error": str(e)}
        
        return stats
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def _fallback_log(self, level: str, message: str, context: str = "system"):
        """
        Аварийное логирование при недоступности логгера.
        
        Args:
            level: Уровень логирования
            message: Текст сообщения
            context: Контекст
        """
        try:
            adapter = self.logger_adapter
            if adapter:
                adapter.log(level, message, context)
            else:
                print(f"[{level}] [{self.name}] {context}: {message}")
        except Exception:
            print(f"[{level}] [{self.name}] {context}: {message}")
