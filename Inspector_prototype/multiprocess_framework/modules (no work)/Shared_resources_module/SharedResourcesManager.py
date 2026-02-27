"""
Менеджер общих ресурсов для межпроцессного взаимодействия.

Легковесный контейнер-библиотека, который передается в каждый процесс.
Содержит только ProcessStateRegistry со всеми ProcessData всех процессов.

ВАЖНО: БЕЗ Manager() и Lock() для кросс-платформенной совместимости.
Queue и Event сериализуемы сами по себе.

ConfigManager, QueueManager, ImageMemoryManager создаются локально в каждом процессе
как вспомогательные утилиты и работают с данными из ProcessStateRegistry.
"""

from multiprocessing import Queue, Event
from typing import Dict, Any, Optional

from ..Process_module.process_state_registry import ProcessStateRegistry
from ..Process_module.process_data import ProcessData
from .event_manager import EventManager, EventType
from .interfaces import ISharedResourcesManager, IProcessStateRegistry, IEventManager


class SharedResourcesManager(ISharedResourcesManager):
    """
    Менеджер общих ресурсов для всех процессов.
    
    Легковесный контейнер-библиотека, который передается в каждый процесс.
    Содержит только ProcessStateRegistry со всеми ProcessData всех процессов.
    
    ConfigManager, QueueManager, ImageMemoryManager создаются локально в каждом процессе
    как вспомогательные утилиты и работают с данными из ProcessStateRegistry.
    
    БЕЗ Manager() и Lock() - использует простой словарь с ProcessData.
    Queue и Event сериализуемы и могут передаваться между процессами.
    
    Этот класс создается в основном процессе и передается в каждый процесс
    для обеспечения общего доступа к данным всех процессов.
    
    Пример использования в процессе:
        # В ProcessModule создаются локальные менеджеры:
        from ..Config_module.config_manager import ConfigManager
        from ..Shared_resources_module.queue_manager import QueueManager
        from ..Shared_resources_module.Memory_Manager import ImageMemoryManager
        
        # Создаем локальные менеджеры с ссылкой на ProcessStateRegistry
        self.config_manager = ConfigManager()
        self.queue_manager = QueueManager(process_state_registry=shared_resources.process_state_registry)
        self.memory_manager = ImageMemoryManager(process_state_registry=shared_resources.process_state_registry)
        
        # Доступ к ProcessData своего процесса
        process_data = shared_resources.get_process_data(self.name)
        queue = process_data.get_queue('system')
        
        # Доступ к ProcessData других процессов
        other_process_data = shared_resources.get_process_data('other_process')
    """
    
    def __init__(self, router_manager=None):
        """
        Инициализация менеджера общих ресурсов.
        
        БЕЗ Manager() - использует простой словарь с ProcessData.
        Содержит только ProcessStateRegistry - легковесный контейнер с данными всех процессов.
        
        Args:
            router_manager: RouterManager для распространения событий (опционально, можно установить позже)
        """
        # Словарь для хранения дополнительных общих ресурсов
        self.shared_resources: Dict[str, Any] = {}
        
        # Менеджер событий для межпроцессного взаимодействия
        # Передаем self после инициализации shared_resources для избежания циклической зависимости
        self.event_manager = EventManager(router_manager=router_manager, shared_resources=self)
        
        # Реестр состояний процессов (БЕЗ Manager и Lock)
        # Содержит все ProcessData всех процессов с их очередями, событиями и конфигурациями
        # Передаем event_manager для автоматической отправки событий при изменениях
        self.process_state_registry = ProcessStateRegistry(event_manager=self.event_manager)
        
        # DataManager (из data_schema) для работы с данными компонентов - используется через get_data_manager()
    def add_shared_resource(self, name: str, resource: Any):
        """
        Добавление общего ресурса.
        
        Args:
            name: Имя ресурса
            resource: Ресурс для добавления
        """
        self.shared_resources[name] = resource
    
    def get_shared_resource(self, name: str) -> Optional[Any]:
        """
        Получение общего ресурса.
        
        Args:
            name: Имя ресурса
            
        Returns:
            Ресурс или None если не найден
        """
        return self.shared_resources.get(name)
    
    # ========================================================================
    # ДОСТУП К ProcessData
    # ========================================================================
    
    def get_process_data(self, process_name: str) -> Optional[ProcessData]:
        """
        Получает ProcessData объект процесса.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            ProcessData или None если процесс не найден
        """
        return self.process_state_registry.get_process_data(process_name)
    
    def get_all_process_data(self) -> Dict[str, ProcessData]:
        """
        Получает все ProcessData объекты всех процессов.
        
        Returns:
            Словарь {process_name: ProcessData}
        """
        return self.process_state_registry.get_all_process_data()
    
    def get_process_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """
        Получает очередь процесса напрямую из ProcessData.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
        
        Returns:
            Queue или None если не найдена
        """
        process_data = self.get_process_data(process_name)
        if process_data:
            return process_data.get_queue(queue_type)
        return None
    
    def get_process_event(self, process_name: str, event_name: str) -> Optional[Event]:
        """
        Получает событие процесса напрямую из ProcessData.
        
        Args:
            process_name: Имя процесса
            event_name: Имя события
        
        Returns:
            Event или None если не найдено
        """
        process_data = self.get_process_data(process_name)
        if process_data:
            return process_data.get_event(event_name)
        return None
    
    # ========================================================================
    # ДЕЛЕГИРОВАНИЕ МЕТОДОВ К ProcessStateRegistry
    # ========================================================================
    
    def register_process_state(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        queue_names: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Регистрация состояния процесса.
        
        Делегирует вызов в ProcessStateRegistry.
        
        Args:
            process_name: Имя процесса
            initial_state: Начальное состояние процесса
            queue_names: Словарь имен очередей
        
        Returns:
            bool: True если регистрация успешна
        """
        return self.process_state_registry.register_process(process_name, initial_state, queue_names)
    
    def register_process_with_config(
        self,
        process_name: str,
        config,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Регистрация процесса с конфигурацией.
        
        Делегирует вызов в ProcessStateRegistry.
        
        Args:
            process_name: Имя процесса
            config: ProcessConfiguration для процесса
            initial_state: Начальное состояние процесса
        
        Returns:
            bool: True если регистрация успешна
        """
        return self.process_state_registry.register_process_with_config(
            process_name, config, initial_state
        )
    
    def update_process_state(
        self,
        process_name: str,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        queues: Optional[Dict[str, str]] = None,
        custom: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Обновление состояния процесса.
        
        Делегирует вызов в ProcessStateRegistry.
        """
        return self.process_state_registry.update_state(
            process_name, status, events, metadata, queues, custom
        )
    
    def get_process_state(self, process_name: str) -> Optional[Dict[str, Any]]:
        """
        Получение состояния процесса.
        
        Делегирует вызов в ProcessStateRegistry.
        """
        return self.process_state_registry.get_state(process_name)
    
    def get_all_process_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Получение всех состояний процессов.
        
        Делегирует вызов в ProcessStateRegistry.
        """
        return self.process_state_registry.get_all_states()
    
    def get_process_names(self) -> list:
        """
        Получение списка всех зарегистрированных процессов.
        
        Делегирует вызов в ProcessStateRegistry.
        """
        return self.process_state_registry.get_process_names()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики работы менеджера ресурсов.
        
        Returns:
            Dict: Статистика по ProcessStateRegistry
        """
        return {
            'process_state_registry': self.process_state_registry.get_stats(),
            'shared_resources': {
                'count': len(self.shared_resources),
                'names': list(self.shared_resources.keys())
            },
            'event_manager': {
                'has_event_queue': self.event_manager.get_event_queue() is not None,
                'subscribers_count': sum(len(callbacks) for callbacks in self.event_manager._subscribers.values())
            }
        }
    
    def __getattr__(self, name: str):
        """
        Динамический доступ к данным процессов через атрибуты.
        
        Позволяет обращаться к данным процесса как к атрибуту:
            shared_resources.process_1.queues.data.put(item)
            shared_resources.process_1.config.get_process_config('key')
            shared_resources.process_1.events.start.set()
        
        Args:
            name: Имя процесса
            
        Returns:
            ProcessData или None если процесс не найден
            
        Raises:
            AttributeError: Если процесс не найден и имя не является специальным атрибутом
        """
        # Проверяем, не является ли это специальным атрибутом
        if name.startswith('_') or name in ['process_state_registry', 'shared_resources', 'get_stats', '__dict__']:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        
        # Пытаемся получить ProcessData для процесса
        process_data = self.get_process_data(name)
        if process_data is not None:
            return process_data
        
        # Если процесс не найден, вызываем стандартное исключение
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'. "
            f"Available processes: {', '.join(self.get_process_names())}"
        )
    
    # ========================================================================
    # ИНТЕГРАЦИЯ С DataManager (из data_schema модуля)
    # ========================================================================
    
    def get_data_manager(self):
        """
        Получить DataManager для работы с данными компонентов (из data_schema).
        
        Returns:
            DataManager экземпляр
        """
        from .data_schema import DataManager
        return DataManager.get_instance(self)
    
    @property
    def data_manager(self):
        """
        Получить DataManager (из data_schema модуля).
        
        Returns:
            DataManager
        """
        return self.get_data_manager()
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ ИНТЕРФЕЙСА ISharedResourcesManager
    # ========================================================================
    
    # process_state_registry и event_manager уже реализованы как свойства класса
    # Интерфейс ISharedResourcesManager требует их наличия, что выполнено
    
    def __str__(self) -> str:
        """
        Строковое представление менеджера ресурсов.
        """
        stats = self.get_stats()
        registry_stats = stats.get('process_state_registry', {})
        return (
            f"SharedResourcesManager("
            f"processes={registry_stats.get('total_processes', 0)}, "
            f"shared_resources={stats['shared_resources']['count']}"
            f")"
        )
