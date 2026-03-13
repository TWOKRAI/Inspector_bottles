"""
Менеджер общих ресурсов для межпроцессного взаимодействия (Refactored).

Легковесный контейнер-библиотека (архив), который передается в каждый процесс.
Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.

Содержит только ProcessStateRegistry со всеми ProcessData всех процессов и EventManager.
БЕЗ Manager() и Lock() для кросс-платформенной совместимости.
Queue и Event сериализуемы сами по себе.

ConfigManager, QueueRegistry, MemoryManager создаются локально в каждом процессе
как вспомогательные утилиты и работают с данными из ProcessStateRegistry.
"""
from __future__ import annotations

from multiprocessing import Queue, Event
from typing import Dict, Any, Optional, TYPE_CHECKING

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.core.base_manager import _noop
from ..events.event_manager import EventManager
from ..state.process_data import ProcessData
from ..state.process_state_registry import ProcessStateRegistry


class SharedResourcesManager(BaseManager, ObservableMixin):
    """
    Менеджер общих ресурсов для всех процессов (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Легковесный контейнер-библиотека (архив), который передается в каждый процесс.
    Содержит только ProcessStateRegistry со всеми ProcessData всех процессов и EventManager.
    
    БЕЗ Manager() и Lock() - использует простой словарь с ProcessData.
    Queue и Event сериализуемы и могут передаваться между процессами.
    
    Attributes:
        manager_name: Имя менеджера
        process_state_registry: Реестр состояний процессов
        event_manager: Менеджер событий
        shared_resources: Словарь дополнительных общих ресурсов
    """
    
    def __init__(
        self,
        manager_name: str = "SharedResourcesManager",
        process: Optional[Any] = None,
        router_manager=None,
        logger=None,
        **kwargs
    ):
        """
        Инициализация менеджера общих ресурсов.
        
        БЕЗ Manager() - использует простой словарь с ProcessData.
        Содержит только ProcessStateRegistry - легковесный контейнер с данными всех процессов.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс (опционально)
            router_manager: RouterManager для распространения событий (опционально)
            logger: Логгер (опционально, используется через ObservableMixin)
            **kwargs: Дополнительные параметры для ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Инициализация ObservableMixin
        managers = kwargs.get('managers', {})
        if logger and 'logger' not in managers:
            managers['logger'] = logger
        
        config = kwargs.get('config', {})
        auto_proxy = kwargs.get('auto_proxy', True)
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=auto_proxy
        )
        
        # Словарь для хранения дополнительных общих ресурсов
        self.shared_resources: Dict[str, Any] = {}
        
        # Менеджер событий для межпроцессного взаимодействия
        # Передаем self после инициализации для избежания циклической зависимости
        self.event_manager = EventManager(
            manager_name=f"{manager_name}_EventManager",
            process=process,
            router_manager=router_manager,
            shared_resources=self,
            logger=logger
        )
        
        # Реестр состояний процессов (БЕЗ Manager и Lock)
        # Содержит все ProcessData всех процессов с их очередями, событиями и конфигурациями
        # Передаем event_manager для автоматической отправки событий при изменениях
        self.process_state_registry = ProcessStateRegistry(event_manager=self.event_manager)
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация менеджера общих ресурсов.
        
        Инициализирует EventManager и ProcessStateRegistry.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Инициализация EventManager
            if not self.event_manager.initialize():
                return False
            
            self.is_initialized = True
            self._log_info(f"SharedResourcesManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize SharedResourcesManager: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы менеджера общих ресурсов.
        
        Завершает EventManager и очищает ресурсы.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Завершение EventManager
            if self.event_manager:
                self.event_manager.shutdown()
            
            # Очищаем общие ресурсы
            self.shared_resources.clear()
            
            self.is_initialized = False
            self._log_info("SharedResourcesManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during SharedResourcesManager shutdown: {e}")
            return False
    
    # ========================================================================
    # УПРАВЛЕНИЕ ОБЩИМИ РЕСУРСАМИ
    # ========================================================================
    
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
        queue_names: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Регистрация состояния процесса.
        
        Делегирует вызов в ProcessStateRegistry.
        
        Args:
            process_name: Имя процесса
            initial_state: Начальное состояние процесса
            queue_names: Словарь имен очередей
            config: Конфигурация процесса {process: {...}, managers: {...}}
        
        Returns:
            bool: True если регистрация успешна
        """
        return self.process_state_registry.register_process(
            process_name, initial_state, queue_names, config
        )
    
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
    
    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики работы менеджера ресурсов.
        
        Интегрируется со статистикой BaseManager и ObservableMixin.
        """
        stats = super().get_stats() if hasattr(super(), 'get_stats') else {}
        
        shared_stats = {
            'process_state_registry': self.process_state_registry.get_stats() if hasattr(self.process_state_registry, 'get_stats') else {},
            'shared_resources': {
                'count': len(self.shared_resources),
                'names': list(self.shared_resources.keys())
            },
            'event_manager': self.event_manager.get_stats() if hasattr(self.event_manager, 'get_stats') else {}
        }
        
        if isinstance(stats, dict):
            stats['shared_resources'] = shared_stats
        else:
            stats = {'shared_resources': shared_stats}
        
        return stats
    
    # ========================================================================
    # ДИНАМИЧЕСКИЙ ДОСТУП К ПРОЦЕССАМ
    # ========================================================================
    
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
        # Fallback для proxy-методов после unpickle (исключены при pickle для multiprocessing)
        # Модульная функция вместо lambda — pickle-совместимо на Windows (spawn)
        _PICKLE_SKIP_ATTRS = (
            '_log_method', '_log_method_internal', '_log', '_record_metric_method',
            '_track_error_method', '_call_manager'
        )
        if name in _PICKLE_SKIP_ATTRS or name.startswith(('_log_', '_record_', '_track_')):
            return _noop
        # Проверяем, не является ли это специальным атрибутом
        if name.startswith('_') or name in ['process_state_registry', 'shared_resources', 'event_manager', 'get_stats', '__dict__']:
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
            DataManager экземпляр или None если модуль не доступен
        
        Note:
            data_schema вынесен как отдельный модуль для переиспользования.
            Используется адаптер для удобного доступа.
        """
        from ..registry.data_schema_adapter import DataSchemaAdapter
        
        if not hasattr(self, '_data_schema_adapter'):
            self._data_schema_adapter = DataSchemaAdapter(self)
        
        return self._data_schema_adapter.get_data_manager()
    
    @property
    def data_manager(self):
        """
        Получить DataManager (из data_schema модуля).
        
        Returns:
            DataManager или None если модуль не доступен
        """
        return self.get_data_manager()
    
    def __str__(self) -> str:
        """
        Строковое представление менеджера ресурсов.
        """
        stats = self.get_stats()
        registry_stats = stats.get('shared_resources', {}).get('process_state_registry', {})
        return (
            f"SharedResourcesManager("
            f"processes={registry_stats.get('total_processes', 0)}, "
            f"shared_resources={stats.get('shared_resources', {}).get('shared_resources', {}).get('count', 0)}"
            f")"
        )

    def __getstate__(self):
        """Pickle: исключаем proxy-методы и _registry (closures не pickle-able на Windows)."""
        state = self.__dict__.copy()
        _PICKLE_EXCLUDE = (
            'log_debug', 'log_info', 'log_warning', 'log_error', 'log_critical',
            'record_metric', 'increment', 'record_timing', 'gauge',
            'track_error', 'record_error',
            '_call_manager', '_registry', '_plugin_registry', '_proxy_created',
        )
        for key in _PICKLE_EXCLUDE:
            state.pop(key, None)
        # Обеспечиваем _adapters для BaseManager после unpickle
        if '_adapters' not in state:
            state['_adapters'] = {}
        return state

    def __setstate__(self, state):
        """Unpickle: восстанавливаем объект. Proxy-методы будут созданы при необходимости."""
        self.__dict__.update(state)


