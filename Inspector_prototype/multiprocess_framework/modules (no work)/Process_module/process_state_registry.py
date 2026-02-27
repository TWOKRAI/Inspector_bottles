"""
Реестр состояний процессов для межпроцессного взаимодействия.

Упрощенная версия БЕЗ Manager() и Lock() для кросс-платформенной совместимости.
Использует простой словарь с ProcessData объектами.

Хранит состояния всех процессов:
- Статусы процессов (ready, initializing, running, stopping, error)
- События процессов (Event объекты)
- Очереди процессов (Queue объекты)
- Метаданные процессов
- Кастомные данные для расширения
"""

import time
from typing import Dict, Any, Optional
from multiprocessing import Queue, Event

from .process_data import ProcessData


class ProcessStateRegistry:
    """
    Реестр состояний процессов БЕЗ Manager() и Lock().
    
    Использует простой словарь Dict[str, ProcessData] для хранения данных процессов.
    Queue и Event из multiprocessing сериализуемы и могут передаваться между процессами.
    
    Структура данных:
    {
        "process_name": ProcessData(
            queues={queue_type: Queue},
            events={event_name: Event},
            status="ready" | "initializing" | "running" | "stopping" | "error",
            metadata={},
            custom={},
            timestamp=float
        )
    }
    """
    
    # Стандартные статусы процессов
    STATUS_INITIALIZING = "initializing"
    STATUS_READY = "ready"
    STATUS_RUNNING = "running"
    STATUS_STOPPING = "stopping"
    STATUS_ERROR = "error"
    
    def __init__(self, event_manager: Optional[Any] = None):
        """
        Инициализация реестра состояний.
        
        БЕЗ Manager() и Lock() - использует простой словарь.
        Queue и Event сериализуемы сами по себе.
        
        Args:
            event_manager: EventManager для отправки событий при изменениях (опционально)
        """
        # Простой словарь состояний процессов
        # ProcessData содержит Queue и Event, которые сериализуемы
        self.states: Dict[str, ProcessData] = {}
        
        # Менеджер событий для уведомления об изменениях
        self.event_manager = event_manager
    
    def register_process(
        self, 
        process_name: str, 
        initial_state: Optional[Dict[str, Any]] = None,
        queue_names: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Регистрация процесса с начальным состоянием.
        
        Args:
            process_name: Имя процесса
            initial_state: Начальное состояние процесса (опционально)
            queue_names: Словарь имен очередей {queue_type: queue_name} (опционально, устаревший)
                         Теперь очереди добавляются через add_queue()
            config: Конфигурация процесса в виде словаря (опционально)
                   Сохраняется в custom['process_config'], custom['component_managers_config'], etc.
        
        Returns:
            bool: True если регистрация успешна
        """
        try:
            if process_name in self.states:
                # Процесс уже зарегистрирован, обновляем состояние
                process_data = self.states[process_name]
                if initial_state:
                    if "status" in initial_state:
                        process_data.update_status(initial_state["status"])
                    if "metadata" in initial_state:
                        process_data.update_metadata(**initial_state["metadata"])
                    if "custom" in initial_state:
                        process_data.update_custom(**initial_state["custom"])
                # Если передан config, сохраняем его в custom
                if config is not None:
                    if isinstance(config, dict):
                        # Сохраняем конфигурацию в custom
                        if 'process' in config:
                            process_data.custom['process_config'] = config['process'].copy()
                        if 'managers' in config:
                            process_data.custom['component_managers_config'] = config['managers'].copy()
                        if 'modules' in config:
                            process_data.custom['modules_config'] = config['modules'].copy()
                        if 'custom' in config:
                            process_data.custom['config_custom'] = config['custom'].copy()
                        process_data.update_timestamp()
            else:
                # Новая регистрация
                status = initial_state.get("status", self.STATUS_INITIALIZING) if initial_state else self.STATUS_INITIALIZING
                metadata = initial_state.get("metadata", {}) if initial_state else {}
                custom = initial_state.get("custom", {}) if initial_state else {}
                
                process_data = ProcessData(
                    name=process_name,
                    _queues_dict={},  # Очереди добавляются через add_queue()
                    _events_dict={},  # События добавляются через add_event()
                    status=status,
                    metadata=metadata,
                    custom=custom
                )
                
                # Если передан config, сохраняем его в custom
                if config:
                    if isinstance(config, dict):
                        # Сохраняем конфигурацию в custom
                        if 'process' in config:
                            process_data.custom['process_config'] = config['process'].copy()
                        if 'managers' in config:
                            process_data.custom['component_managers_config'] = config['managers'].copy()
                        if 'modules' in config:
                            process_data.custom['modules_config'] = config['modules'].copy()
                        if 'custom' in config:
                            process_data.custom['config_custom'] = config['custom'].copy()
                
                self.states[process_name] = process_data
                
                # Отправляем событие о регистрации процесса через EventManager
                if self.event_manager:
                    try:
                        from ..Shared_resources_module.event_manager import EventType
                        self.event_manager.emit_event(
                            EventType.PROCESS_REGISTERED,
                            process_name=process_name,
                            state=process_data.to_dict()
                        )
                    except Exception:
                        pass  # Игнорируем ошибки событий
            
            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to register process '{process_name}': {e}")
            return False
    
    def register_process_with_config(
        self,
        process_name: str,
        config: Dict[str, Any],
        initial_state: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Регистрация процесса с конфигурацией.
        
        Удобный метод для регистрации процесса с полной конфигурацией.
        
        Args:
            process_name: Имя процесса
            config: Конфигурация процесса в виде словаря
            initial_state: Начальное состояние процесса (опционально)
        
        Returns:
            bool: True если регистрация успешна
        """
        return self.register_process(process_name, initial_state, config=config)
    
    def update_state(
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
        
        Args:
            process_name: Имя процесса
            status: Новый статус (опционально)
            events: События для обновления (опционально, устаревший - используйте add_event())
            metadata: Метаданные для обновления (опционально, объединяется с существующими)
            queues: Очереди для обновления (опционально, устаревший - используйте add_queue())
            custom: Кастомные данные для обновления (опционально, объединяется с существующими)
        
        Returns:
            bool: True если обновление успешно
        """
        try:
            if process_name not in self.states:
                # Процесс не зарегистрирован, регистрируем с начальным состоянием
                return self.register_process(process_name, {
                    "status": status or self.STATUS_INITIALIZING,
                    "metadata": metadata or {},
                    "custom": custom or {}
                })
            
            process_data = self.states[process_name]
            
            # Сохраняем старый статус для события
            old_status = process_data.status if status is not None else None
            
            # Обновляем статус
            if status is not None:
                process_data.update_status(status)
                
                # Отправляем событие об изменении статуса через EventManager
                if self.event_manager and old_status != status:
                    try:
                        from ..Shared_resources_module.event_manager import EventType
                        self.event_manager.emit_event(
                            EventType.PROCESS_STATE_CHANGED,
                            process_name=process_name,
                            old_status=old_status,
                            new_status=status,
                            state=process_data.to_dict()
                        )
                    except Exception:
                        pass  # Игнорируем ошибки событий
            
            # Обновляем метаданные (объединяем с существующими)
            if metadata is not None:
                process_data.update_metadata(**metadata)
            
            # Обновляем кастомные данные (объединяем с существующими)
            if custom is not None:
                process_data.update_custom(**custom)
            
            # events и queues устарели - используйте add_event() и add_queue()
            if events is not None:
                print(f"ProcessStateRegistry: Warning - 'events' parameter is deprecated. Use add_event() instead.")
            
            if queues is not None:
                print(f"ProcessStateRegistry: Warning - 'queues' parameter is deprecated. Use add_queue() instead.")
            
            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to update state for '{process_name}': {e}")
            return False
    
    def add_queue(self, process_name: str, queue_type: str, queue: Queue) -> bool:
        """
        Добавляет очередь в процесс.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди (например, 'system', 'data')
            queue: Объект Queue
        
        Returns:
            bool: True если успешно
        """
        try:
            if process_name not in self.states:
                self.register_process(process_name)
            
            self.states[process_name].add_queue(queue_type, queue)
            
            # Отправляем событие о добавлении очереди через EventManager
            if self.event_manager:
                try:
                    from ..Shared_resources_module.event_manager import EventType
                    self.event_manager.emit_event(
                        EventType.QUEUE_ADDED,
                        process_name=process_name,
                        queue_type=queue_type
                    )
                except Exception:
                    pass  # Игнорируем ошибки событий
            
            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to add queue '{queue_type}' to '{process_name}': {e}")
            return False
    
    def add_event(self, process_name: str, event_name: str, event: Event) -> bool:
        """
        Добавляет событие в процесс.
        
        Args:
            process_name: Имя процесса
            event_name: Имя события
            event: Объект Event
        
        Returns:
            bool: True если успешно
        """
        try:
            if process_name not in self.states:
                self.register_process(process_name)
            
            self.states[process_name].add_event(event_name, event)
            
            # Отправляем событие о добавлении события через EventManager
            if self.event_manager:
                try:
                    from ..Shared_resources_module.event_manager import EventType
                    self.event_manager.emit_event(
                        EventType.EVENT_ADDED,
                        process_name=process_name,
                        event_name=event_name
                    )
                except Exception:
                    pass  # Игнорируем ошибки событий
            
            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to add event '{event_name}' to '{process_name}': {e}")
            return False
    
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """
        Получает очередь процесса по типу.
        
        Args:
            process_name: Имя процесса
            queue_type: Тип очереди
        
        Returns:
            Queue или None если не найдена
        """
        if process_name not in self.states:
            return None
        return self.states[process_name].get_queue(queue_type)
    
    def get_event(self, process_name: str, event_name: str) -> Optional[Event]:
        """
        Получает событие процесса по имени.
        
        Args:
            process_name: Имя процесса
            event_name: Имя события
        
        Returns:
            Event или None если не найдено
        """
        if process_name not in self.states:
            return None
        return self.states[process_name].get_event(event_name)
    
    def get_state(self, process_name: str) -> Optional[Dict[str, Any]]:
        """
        Получение состояния процесса.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            Словарь состояния процесса или None если процесс не найден
            ВАЖНО: Queue и Event не включаются в словарь (они остаются в ProcessData)
        """
        try:
            if process_name not in self.states:
                return None
            
            process_data = self.states[process_name]
            return process_data.to_dict()
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get state for '{process_name}': {e}")
            return None
    
    def get_process_data(self, process_name: str) -> Optional[ProcessData]:
        """
        Получает ProcessData объект процесса.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            ProcessData или None если процесс не найден
        """
        return self.states.get(process_name)
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Получение всех состояний процессов.
        
        Returns:
            Словарь {process_name: state_dict}
        """
        try:
            result = {}
            for process_name, process_data in self.states.items():
                result[process_name] = process_data.to_dict()
            return result
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get all states: {e}")
            return {}
    
    def get_all_process_data(self) -> Dict[str, ProcessData]:
        """
        Получает все ProcessData объекты.
        
        Returns:
            Словарь {process_name: ProcessData}
        """
        return self.states.copy()
    
    def get_process_names(self) -> list:
        """
        Получение списка всех зарегистрированных процессов.
        
        Returns:
            Список имен процессов
        """
        try:
            return list(self.states.keys())
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get process names: {e}")
            return []
    
    def unregister_process(self, process_name: str) -> bool:
        """
        Удаление процесса из реестра.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            bool: True если удаление успешно
        """
        try:
            if process_name in self.states:
                # Отправляем событие об удалении процесса через EventManager
                if self.event_manager:
                    try:
                        from ..Shared_resources_module.event_manager import EventType
                        self.event_manager.emit_event(
                            EventType.PROCESS_UNREGISTERED,
                            process_name=process_name
                        )
                    except Exception:
                        pass  # Игнорируем ошибки событий
                
                del self.states[process_name]
                return True
            return False
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to unregister process '{process_name}': {e}")
            return False
    
    def has_process(self, process_name: str) -> bool:
        """
        Проверка наличия процесса в реестре.
        
        Args:
            process_name: Имя процесса
        
        Returns:
            bool: True если процесс зарегистрирован
        """
        try:
            return process_name in self.states
        except Exception:
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики реестра.
        
        Returns:
            Словарь со статистикой
        """
        try:
            states = self.get_all_states()
            status_counts = {}
            for state in states.values():
                status = state.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            
            return {
                "total_processes": len(states),
                "status_counts": status_counts,
                "processes": list(states.keys())
            }
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get stats: {e}")
            return {"total_processes": 0, "status_counts": {}, "processes": []}
