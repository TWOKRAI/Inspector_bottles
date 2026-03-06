"""
Базовый менеджер - абстрактный класс для всех менеджеров системы.

Публичный API модуля. Используется извне модуля.
"""

from typing import Dict, Any, Optional, Callable, List
from abc import ABC, abstractmethod
import re

from ..utils.name_utils import get_adapter_name_from_class


def _noop(*a, **kw):
    """Заглушка для proxy-методов после unpickle. Pickle-совместима (модульная функция)."""
    return None


class BaseManager(ABC):
    """
    Базовый абстрактный класс для всех менеджеров системы.
    
    Менеджер может иметь адаптеры (инструменты), которые подключаются через attach_adapter().
    Адаптеры предоставляют дополнительную функциональность (интеграция с процессом, упрощенный API и т.д.)
    
    Attributes:
        manager_name (str): Уникальное имя менеджера
        process (Optional[Any]): Ссылка на родительский процесс (если есть)
        is_initialized (bool): Флаг инициализации менеджера
        _adapters (Dict[str, Any]): Словарь подключенных адаптеров
    """
    
    def __init__(self, manager_name: str, process: Optional[Any] = None):
        """
        Инициализация базового менеджера.
        
        Args:
            manager_name (str): Уникальное имя менеджера
            process (Optional[Any]): Ссылка на родительский процесс
        """
        self.manager_name = manager_name
        self.process = process
        self.is_initialized = False
        self._event_handlers: Dict[str, List[Callable]] = {}  # Callback'и для событий
        self._adapters: Dict[str, Any] = {}  # Подключенные адаптеры (инструменты)
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        Абстрактный метод инициализации менеджера.
        Должен быть реализован в дочерних классах.
        
        Returns:
            bool: True если инициализация успешна, False в противном случае
        """
        pass
    
    @abstractmethod  
    def shutdown(self) -> bool:
        """
        Абстрактный метод корректного завершения работы менеджера.
        Должен быть реализован в дочерних классах.
        
        Returns:
            bool: True если завершение успешно, False в противном случае
        """
        pass
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - УПРАВЛЕНИЕ АДАПТЕРАМИ
    # ========================================================================
    
    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер (инструмент) к менеджеру.
        
        Адаптер предоставляет дополнительную функциональность для менеджера.
        **Рекомендуется явно указывать имя адаптера** для надежности и читаемости.
        Если имя не указано, определяется автоматически (простая логика, может быть неточной).
        
        Args:
            adapter: Экземпляр адаптера
            name: Имя адаптера (опционально). 
                  **Рекомендуется указывать явно** для сложных имен классов.
                  Если не указано, определяется автоматически из имени класса.
            
        Returns:
            bool: True если адаптер успешно подключен
            
        Example:
            >>> adapter = CommandAdapter(manager, process)
            # Рекомендуемый способ - явное указание имени
            >>> manager.attach_adapter(adapter, name="command")
            >>> manager.command_adapter  # Доступ через magic-атрибут
            
            # Автоматическое определение (fallback)
            >>> manager.attach_adapter(adapter)  # Имя определится автоматически
        """
        if adapter is None:
            return False
        
        # Определяем имя адаптера: явное указание имеет приоритет
        if name is None:
            # Автоматическое определение используется только как fallback
            name = get_adapter_name_from_class(adapter.__class__.__name__)
        
        # Подключаем адаптер
        self._adapters[name] = adapter
        
        # Устанавливаем обратную ссылку на менеджера в адаптере
        if hasattr(adapter, 'manager'):
            adapter.manager = self
        
        return True
    
    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        ЯВНЫЙ способ получения адаптера (РЕКОМЕНДУЕТСЯ).
        
        Это основной и рекомендуемый способ доступа к адаптерам.
        Используйте этот метод вместо magic-доступа через атрибуты
        для лучшей читаемости и отладки.
        
        Args:
            name: Имя адаптера. Если не указано, возвращается первый адаптер.
            
        Returns:
            Адаптер или None если не найден
            
        Example:
            >>> # Рекомендуемый способ (явный)
            >>> adapter = manager.get_adapter("command")
            >>> if adapter:
            ...     adapter.execute("test")
            
            >>> # Альтернативный способ (magic-доступ, менее явный)
            >>> adapter = manager.command_adapter  # Работает, но менее очевидно
        """
        if name is None:
            # Возвращаем первый адаптер если имя не указано
            for adapter in self._adapters.values():
                if adapter is not None:
                    return adapter
            return None
        
        adapter = self._adapters.get(name)
        return adapter if adapter is not None else None
    
    def has_adapter(self, name: str) -> bool:
        """Проверить наличие адаптера по имени."""
        return name in self._adapters
    
    def list_adapters(self) -> List[str]:
        """Получить список имен подключенных адаптеров."""
        return list(self._adapters.keys())
    
    def detach_adapter(self, name: str) -> bool:
        """
        Отключить адаптер от менеджера.
        
        Args:
            name: Имя адаптера
            
        Returns:
            bool: True если адаптер был отключен
        """
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - СОБЫТИЯ
    # ========================================================================
    
    def on_event(self, event_type: str, callback: Callable) -> None:
        """
        Регистрация обработчика событий.
        
        Args:
            event_type (str): Тип события
            callback (Callable): Функция-обработчик события
        """
        self._event_handlers.setdefault(event_type, []).append(callback)
    
    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Генерация события и вызов зарегистрированных обработчиков.
        
        Args:
            event_type (str): Тип события
            data (Dict[str, Any]): Данные события
        """
        for callback in self._event_handlers.get(event_type, []):
            try:
                callback(data)
            except Exception as e:
                # Fallback логирование если нет доступа к логгеру
                print(f"Error in event handler for {event_type}: {e}")
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - СТАТИСТИКА
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики и метрик менеджера.
        
        Returns:
            Dict[str, Any]: Словарь со статистикой менеджера
        """
        stats = {
            "manager_name": self.manager_name,
            "is_initialized": self.is_initialized,
            "process_name": getattr(self.process, 'name', 'unknown') if self.process else 'standalone',
            "adapters": list(self._adapters.keys())
        }
        
        # Добавляем статистику адаптеров если они есть
        if self._adapters:
            adapters_info = {}
            for name, adapter in self._adapters.items():
                if adapter is None:
                    adapters_info[name] = {}
                elif hasattr(adapter, 'get_stats'):
                    try:
                        adapters_info[name] = adapter.get_stats()
                    except Exception:
                        adapters_info[name] = {}
                else:
                    adapters_info[name] = {}
            stats["adapters_info"] = adapters_info
        
        return stats
    
    # ========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ (не используются извне)
    # ========================================================================
    
    def __getattr__(self, name: str) -> Any:
        """
        Magic-доступ к адаптерам через атрибуты (удобный синтаксический сахар).
        
        ВНИМАНИЕ: Используйте get_adapter() для явного доступа.
        Этот метод может быть неочевидным при отладке и может скрывать ошибки.
        
        Позволяет обращаться к адаптерам как к атрибутам:
        manager.command_adapter вместо manager.get_adapter("command")
        
        Args:
            name: Имя атрибута
            
        Returns:
            Адаптер если найден
            
        Raises:
            AttributeError: Если атрибут не найден
            
        Example:
            >>> # Magic-доступ (работает, но менее явный)
            >>> adapter = manager.command_adapter
            
            >>> # Явный доступ (РЕКОМЕНДУЕТСЯ)
            >>> adapter = manager.get_adapter("command")
        """
        # Пробуем найти адаптер по имени (через __dict__ чтобы избежать рекурсии в __getattr__)
        _adapters = self.__dict__.get('_adapters', {})
        if name in _adapters:
            adapter = _adapters[name]
            if adapter is None:
                raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}' (adapter is None)")
            return adapter
        
        # Пробуем найти по snake_case версии имени класса
        for adapter_name, adapter in _adapters.items():
            if adapter is None:
                continue
            expected_name = get_adapter_name_from_class(adapter.__class__.__name__)
            if name == expected_name:
                return adapter

        # Fallback для proxy-методов после unpickle (исключены при pickle для multiprocessing)
        # Модульная функция вместо lambda — pickle-совместимо на Windows (spawn)
        if name in ('_log_method', '_log_method_internal', '_log', '_record_metric_method',
                    '_track_error_method', '_call_manager') or name.startswith(('_log_', '_record_', '_track_')):
            return _noop

        # Если не нашли, вызываем стандартное поведение
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def get_debug_info(self) -> Dict[str, Any]:
        """
        Получить информацию для отладки.
        
        Полезно для диагностики проблем и понимания состояния менеджера.
        
        Returns:
            Словарь с информацией:
            - manager_name: Имя менеджера
            - is_initialized: Флаг инициализации
            - process_name: Имя процесса (если есть)
            - adapters: Список имен адаптеров
            - adapter_details: Детали адаптеров (типы)
            - available_methods: Список доступных методов
        """
        info = {
            'manager_name': self.manager_name,
            'is_initialized': self.is_initialized,
            'process_name': getattr(self.process, 'name', 'unknown') if self.process else 'standalone',
            'adapters': list(self._adapters.keys()),
            'adapter_details': {
                name: type(adapter).__name__ if adapter is not None else None
                for name, adapter in self._adapters.items()
            },
            'available_methods': [
                m for m in dir(self) 
                if not m.startswith('__') and callable(getattr(self, m, None))
            ]
        }
        
        # Добавляем информацию из ObservableMixin если доступна
        if hasattr(self, 'get_available_methods'):
            try:
                observable_info = self.get_available_methods()
                info['observable_managers'] = observable_info.get('managers', [])
                info['observable_methods'] = {
                    'private': len(observable_info.get('private', [])),
                    'public': len(observable_info.get('public', []))
                }
            except Exception:
                pass
        
        return info
    
    def print_debug_info(self):
        """
        Вывести информацию для отладки в консоль.
        
        Удобный метод для быстрой диагностики проблем.
        """
        import json
        info = self.get_debug_info()
        print("=" * 60)
        print(f"Debug Info: {self.__class__.__name__}")
        print("=" * 60)
        print(json.dumps(info, indent=2, ensure_ascii=False))
        print("=" * 60)
    
    def __str__(self) -> str:
        """
        Строковое представление менеджера.
        
        Returns:
            str: Информация о менеджере
        """
        return f"BaseManager(name={self.manager_name}, initialized={self.is_initialized})"

