"""
Менеджер событий для межпроцессного взаимодействия (Refactored).

Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.
Интегрируется с RouterManager для распространения событий через роутер.
Данные событий хранятся в data_schema через ProcessData.
"""

import time
from typing import Dict, Any, Optional, List, Callable
from multiprocessing import Event, Queue
from enum import Enum

from ...base_manager import BaseManager, ObservableMixin


class EventType(Enum):
    """Типы событий системы."""
    PROCESS_STATE_CHANGED = "process_state_changed"
    PROCESS_REGISTERED = "process_registered"
    PROCESS_UNREGISTERED = "process_unregistered"
    QUEUE_ADDED = "queue_added"
    EVENT_ADDED = "event_added"
    CONFIG_UPDATED = "config_updated"


class EventManager(BaseManager, ObservableMixin):
    """
    Менеджер событий для межпроцессного взаимодействия (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Интегрируется с RouterManager для распространения событий через роутер.
    Данные событий хранятся в data_schema через ProcessData.
    
    Attributes:
        manager_name: Имя менеджера
        _router_manager: RouterManager для распространения событий
        shared_resources: SharedResourcesManager для хранения событий
        _event_queue: Очередь событий для хранения
        _subscribers: Подписчики на события {event_type: [callbacks]}
        _new_event_event: Событие для уведомления о новых событиях
    """
    
    def __init__(
        self,
        manager_name: str = "EventManager",
        process: Optional[Any] = None,
        router_manager=None,
        shared_resources=None,
        logger=None,
        **kwargs
    ):
        """
        Инициализация менеджера событий.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс (опционально)
            router_manager: RouterManager для распространения событий (можно установить позже)
            shared_resources: SharedResourcesManager для хранения событий
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
        
        # Сохраняем зависимости
        self._router_manager = router_manager
        self.shared_resources = shared_resources
        
        # Очередь событий для хранения
        self._event_queue: Optional[Queue] = None
        
        # Подписчики на события {event_type: [callbacks]}
        self._subscribers: Dict[EventType, List[Callable]] = {}
        
        # Событие для уведомления о новых событиях
        self._new_event_event: Optional[Event] = None
        
        # Статистика
        self._stats = {
            'emitted': 0,
            'subscribed': 0,
            'notified': 0,
            'errors': 0
        }
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация менеджера событий.
        
        Инициализирует ресурсы для событий (очередь и событие).
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Инициализация ресурсов для событий
            self._init_event_resources()
            
            self.is_initialized = True
            self._log_info(f"EventManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize EventManager: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы менеджера событий.
        
        Очищает подписчиков и ресурсы.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Очищаем подписчиков
            self._subscribers.clear()
            
            # Очищаем ресурсы
            self._event_queue = None
            self._new_event_event = None
            
            self.is_initialized = False
            self._log_info("EventManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during EventManager shutdown: {e}")
            return False
    
    def _init_event_resources(self):
        """Инициализация ресурсов для событий."""
        # Создаем очередь событий и событие всегда (для работы wait_for_event)
        self._event_queue = Queue()
        self._new_event_event = Event()
        
        # Сохраняем в shared_resources для доступа из других процессов (если доступен)
        if self.shared_resources:
            self.shared_resources.add_shared_resource("event_queue", self._event_queue)
            self.shared_resources.add_shared_resource("new_event_event", self._new_event_event)
    
    # ========================================================================
    # ОСНОВНОЙ API - СОБЫТИЯ
    # ========================================================================
    
    def emit_event(
        self,
        event_type: EventType,
        process_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Отправка события через роутер и сохранение в очереди.
        
        Args:
            event_type: Тип события
            process_name: Имя процесса (если событие связано с процессом)
            **kwargs: Дополнительные данные события
        
        Returns:
            True если событие отправлено успешно
        """
        self._stats['emitted'] += 1
        
        try:
            # Формируем событие (данные хранятся в data_schema формате)
            event_data = {
                "type": "system_event",
                "event_type": event_type.value,
                "process_name": process_name,
                "timestamp": time.time(),
                **kwargs
            }
            
            # Отправляем через роутер если доступен
            if self._router_manager:
                message = {
                    "type": "system_event",
                    "command": "system_event",
                    "channel": "system_events",
                    "sender": "EventManager",
                    "content": event_data,
                    "targets": ["ProcessManager"]
                }
                try:
                    self._router_manager.send(message)
                except Exception as e:
                    self._log_error(f"Failed to send event via router: {e}")
                    self._stats['errors'] += 1
            
            # Сохраняем в очередь для подписчиков
            if self._event_queue:
                self._event_queue.put(event_data)
                if self._new_event_event:
                    self._new_event_event.set()
            
            # Вызываем локальных подписчиков
            self._notify_subscribers(event_type, event_data)
            
            return True
        
        except Exception as e:
            self._log_error(f"Failed to emit event {event_type.value}: {e}")
            self._stats['errors'] += 1
            return False
    
    def subscribe(self, event_type: EventType, callback: Callable) -> bool:
        """
        Подписка на события определенного типа.
        
        Args:
            event_type: Тип события для подписки
            callback: Функция обратного вызова (event_data) -> None
        
        Returns:
            True если подписка успешна
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        self._subscribers[event_type].append(callback)
        self._stats['subscribed'] += 1
        return True
    
    def unsubscribe(self, event_type: EventType, callback: Callable) -> bool:
        """
        Отписка от событий.
        
        Args:
            event_type: Тип события
            callback: Функция обратного вызова для удаления
        
        Returns:
            True если отписка успешна
        """
        if event_type in self._subscribers:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)
                return True
        return False
    
    def _notify_subscribers(self, event_type: EventType, event_data: Dict[str, Any]):
        """Уведомление подписчиков о событии."""
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(event_data)
                    self._stats['notified'] += 1
                except Exception as e:
                    self._log_error(f"Error in subscriber callback: {e}")
                    self._stats['errors'] += 1
    
    def wait_for_event(
        self,
        event_type: Optional[EventType] = None,
        timeout: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        Ожидание события с таймаутом.
        
        Args:
            event_type: Тип события для ожидания (None = любое событие)
            timeout: Таймаут ожидания в секундах
        
        Returns:
            Данные события или None если таймаут
        """
        if not self._new_event_event or not self._event_queue:
            return None
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self._new_event_event.wait(timeout=0.1):
                try:
                    event_data = self._event_queue.get(timeout=0.1)
                    
                    if event_type is None or event_data.get("event_type") == event_type.value:
                        return event_data
                    
                    self._event_queue.put(event_data)
                except Exception:
                    pass
                
                self._new_event_event.clear()
        
        return None
    
    # ========================================================================
    # ДОСТУП К РЕСУРСАМ
    # ========================================================================
    
    def get_event_queue(self) -> Optional[Queue]:
        """Получить очередь событий."""
        return self._event_queue
    
    def get_new_event_event(self) -> Optional[Event]:
        """Получить событие для уведомления о новых событиях."""
        return self._new_event_event
    
    def set_router_manager(self, router_manager):
        """
        Установить RouterManager для распространения событий.
        
        Args:
            router_manager: RouterManager для распространения событий
        """
        self._router_manager = router_manager
    
    @property
    def router_manager(self):
        """Получить RouterManager."""
        return self._router_manager
    
    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику менеджера событий.
        
        Интегрируется со статистикой BaseManager и ObservableMixin.
        """
        stats = super().get_stats() if hasattr(super(), 'get_stats') else {}
        
        event_stats = {
            'emitted': self._stats['emitted'],
            'subscribed': self._stats['subscribed'],
            'notified': self._stats['notified'],
            'errors': self._stats['errors'],
            'subscribers_count': sum(len(callbacks) for callbacks in self._subscribers.values()),
            'event_types': [et.value for et in self._subscribers.keys()]
        }
        
        if isinstance(stats, dict):
            stats['events'] = event_stats
        else:
            stats = {'events': event_stats}
        
        return stats

    def __getstate__(self):
        """Pickle: исключаем proxy-методы, Queue, callbacks для multiprocessing на Windows."""
        state = self.__dict__.copy()
        _PICKLE_EXCLUDE = (
            'log_debug', 'log_info', 'log_warning', 'log_error', 'log_critical',
            'record_metric', 'increment', 'record_timing', 'gauge',
            'track_error', 'record_error',
            '_call_manager', '_registry', '_plugin_registry', '_proxy_created',
            '_event_queue', '_subscribers', '_new_event_event',  # Queue, Event, callbacks
        )
        for key in _PICKLE_EXCLUDE:
            state.pop(key, None)
        if '_adapters' not in state:
            state['_adapters'] = {}
        return state

    def __setstate__(self, state):
        """Unpickle: восстанавливаем объект. Исключённые Queue/Event — None."""
        self.__dict__.update(state)
        if '_event_queue' not in self.__dict__:
            self._event_queue = None
        if '_subscribers' not in self.__dict__:
            self._subscribers = {}
        if '_new_event_event' not in self.__dict__:
            self._new_event_event = None




