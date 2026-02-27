"""
Менеджер событий для межпроцессного взаимодействия.

Интегрирован с RouterManager для распространения событий через роутер.
События хранятся в SharedResourcesManager для удобного доступа.

Архитектура:
- ProcessStateRegistry отправляет события через роутер при изменении состояний
- RouterManager распространяет события через каналы
- SharedResourcesManager хранит события для подписки
- ProcessManager подписывается на события через роутер
"""

import time
from typing import Dict, Any, Optional, List, Callable
from multiprocessing import Event, Queue
from enum import Enum


class EventType(Enum):
    """Типы событий системы"""
    PROCESS_STATE_CHANGED = "process_state_changed"
    PROCESS_REGISTERED = "process_registered"
    PROCESS_UNREGISTERED = "process_unregistered"
    QUEUE_ADDED = "queue_added"
    EVENT_ADDED = "event_added"
    CONFIG_UPDATED = "config_updated"


class EventManager:
    """
    Менеджер событий для межпроцессного взаимодействия.
    
    Интегрирован с RouterManager для распространения событий через роутер.
    События хранятся в SharedResourcesManager для удобного доступа.
    
    Использование:
        # В ProcessStateRegistry при изменении состояния
        event_manager.emit_event(
            EventType.PROCESS_STATE_CHANGED,
            process_name="MyProcess",
            old_status="ready",
            new_status="running"
        )
        
        # В ProcessManager подписка на события
        event_manager.subscribe(
            EventType.PROCESS_STATE_CHANGED,
            callback=self._handle_state_change
        )
    """
    
    def __init__(self, router_manager=None, shared_resources=None):
        """
        Инициализация менеджера событий.
        
        Args:
            router_manager: RouterManager для распространения событий (можно установить позже через set_router_manager)
            shared_resources: SharedResourcesManager для хранения событий
        """
        self._router_manager = router_manager
        self.shared_resources = shared_resources
        
        # Очередь событий для хранения
        self._event_queue: Optional[Queue] = None
        
        # Подписчики на события {event_type: [callbacks]}
        self._subscribers: Dict[EventType, List[Callable]] = {}
        
        # Событие для уведомления о новых событиях
        self._new_event_event: Optional[Event] = None
        
        # Инициализация очереди и события
        self._init_event_resources()
    
    def _init_event_resources(self):
        """Инициализация ресурсов для событий"""
        if self.shared_resources:
            # Создаем очередь событий в SharedResourcesManager
            from multiprocessing import Queue, Event
            self._event_queue = Queue()
            self._new_event_event = Event()
            
            # Сохраняем в shared_resources для доступа из других процессов
            self.shared_resources.add_shared_resource("event_queue", self._event_queue)
            self.shared_resources.add_shared_resource("new_event_event", self._new_event_event)
    
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
        try:
            # Формируем событие
            event_data = {
                "type": "system_event",
                "event_type": event_type.value,
                "process_name": process_name,
                "timestamp": time.time(),
                **kwargs
            }
            
            # Отправляем через роутер если доступен
            if self._router_manager:
                # Используем специальный канал для событий
                # Формат сообщения для роутера с указанием канала
                message = {
                    "type": "system_event",
                    "command": "system_event",  # Ключ для диспетчера
                    "channel": "system_events",  # Явное указание канала
                    "sender": "EventManager",
                    "content": event_data,
                    "targets": ["ProcessManager"]  # Отправляем ProcessManager
                }
                try:
                    self._router_manager.send(message)
                except Exception as e:
                    # Логируем ошибку но не прерываем выполнение
                    print(f"EventManager: Failed to send event via router: {e}")
            
            # Сохраняем в очередь для подписчиков
            if self._event_queue:
                self._event_queue.put(event_data)
                # Устанавливаем событие для уведомления подписчиков
                if self._new_event_event:
                    self._new_event_event.set()
            
            # Вызываем локальных подписчиков
            self._notify_subscribers(event_type, event_data)
            
            return True
        
        except Exception as e:
            print(f"EventManager: Failed to emit event {event_type.value}: {e}")
            return False
    
    def subscribe(self, event_type: EventType, callback: Callable) -> bool:
        """
        Подписка на события определенного типа.
        
        Args:
            event_type: Тип события для подписки
            callback: Функция обратного вызова (event_data) -> None
        
        Returns:
            True если подписка успешна
        
        Пример:
            event_manager.subscribe(
                EventType.PROCESS_STATE_CHANGED,
                lambda event: print(f"Process {event['process_name']} changed state")
            )
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        self._subscribers[event_type].append(callback)
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
        """Уведомление подписчиков о событии"""
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    callback(event_data)
                except Exception as e:
                    print(f"EventManager: Error in subscriber callback: {e}")
    
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
            # Ждем события
            if self._new_event_event.wait(timeout=0.1):
                # Есть новое событие
                try:
                    event_data = self._event_queue.get(timeout=0.1)
                    
                    # Если указан тип события, фильтруем
                    if event_type is None or event_data.get("event_type") == event_type.value:
                        return event_data
                    
                    # Не подходящее событие, возвращаем в очередь
                    self._event_queue.put(event_data)
                    
                except Exception:
                    pass
                
                # Сбрасываем событие
                self._new_event_event.clear()
        
        return None
    
    def get_event_queue(self) -> Optional[Queue]:
        """Получить очередь событий"""
        return self._event_queue
    
    def get_new_event_event(self) -> Optional[Event]:
        """Получить событие для уведомления о новых событиях"""
        return self._new_event_event
    
    def set_router_manager(self, router_manager):
        """
        Установить RouterManager для распространения событий.
        
        Можно вызвать после создания EventManager, когда router_manager будет доступен.
        
        Args:
            router_manager: RouterManager для распространения событий
        """
        self._router_manager = router_manager
    
    @property
    def router_manager(self):
        """Получить RouterManager"""
        return self._router_manager

