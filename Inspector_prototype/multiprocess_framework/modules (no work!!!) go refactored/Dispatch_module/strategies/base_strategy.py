"""
Базовый класс для стратегий диспетчеризации.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Optional, List

from ..types import HandlerInfo


class BaseStrategy(ABC):
    """
    Базовый класс для стратегий диспетчеризации.
    
    Каждая стратегия инкапсулирует логику:
    - Регистрации обработчиков
    - Поиска обработчиков
    - Управления обработчиками
    """
    
    def __init__(self, dispatcher_name: str):
        """
        Инициализация стратегии.
        
        Args:
            dispatcher_name: Имя диспетчера для логирования
        """
        self.dispatcher_name = dispatcher_name
    
    @abstractmethod
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        handlers_storage: Dict[str, HandlerInfo] = None
    ) -> bool:
        """
        Регистрация обработчика.
        
        Args:
            key: Ключ обработчика
            handler: Функция-обработчик
            expects_full_message: Получает ли обработчик полное сообщение
            metadata: Метаданные обработчика
            efficiency: Уровень эффективности
            tags: Теги обработчика
            handlers_storage: Хранилище обработчиков (может быть разным для разных стратегий)
            
        Returns:
            True если успешно, False в случае ошибки
        """
        pass
    
    @abstractmethod
    def find_handler(self, key: str, handlers_storage: Any) -> Optional[HandlerInfo]:
        """
        Поиск обработчика по ключу.
        
        Args:
            key: Ключ для поиска
            handlers_storage: Хранилище обработчиков (тип зависит от стратегии)
            
        Returns:
            HandlerInfo если найден, None если не найден
        """
        pass
    
    @abstractmethod
    def get_all_handlers(self, handlers_storage: Any) -> List[Dict]:
        """
        Получить все обработчики.
        
        Args:
            handlers_storage: Хранилище обработчиков
            
        Returns:
            Список словарей с информацией об обработчиках
        """
        pass
    
    @abstractmethod
    def get_handlers_by_tag(self, tag: str, handlers_storage: Any) -> List[Dict]:
        """
        Получить обработчики по тегу.
        
        Args:
            tag: Тег для поиска
            handlers_storage: Хранилище обработчиков
            
        Returns:
            Список словарей с информацией об обработчиках
        """
        pass
    
    def update_handler_efficiency(
        self,
        key: str,
        new_efficiency: int,
        handlers_storage: Any
    ) -> bool:
        """
        Обновление эффективности обработчика (базовая реализация).
        
        Может быть переопределена в подклассах.
        """
        return False
    
    def update_handler_metadata(
        self,
        key: str,
        new_metadata: Dict[str, Any],
        handlers_storage: Any
    ) -> bool:
        """
        Обновление метаданных обработчика (базовая реализация).
        
        Может быть переопределена в подклассах.
        """
        return False
    
    def update_handler_tags(
        self,
        key: str,
        new_tags: List[str],
        handlers_storage: Any
    ) -> bool:
        """
        Обновление тегов обработчика (базовая реализация).
        
        Может быть переопределена в подклассах.
        """
        return False
    
    def update_handler_function(
        self,
        key: str,
        new_handler: Callable,
        handlers_storage: Any
    ) -> bool:
        """
        Обновление функции обработчика (базовая реализация).
        
        Может быть переопределена в подклассах.
        """
        return False
    
    def update_expects_full_message(
        self,
        key: str,
        expects_full: bool,
        handlers_storage: Any
    ) -> bool:
        """
        Обновление флага expects_full_message (базовая реализация).
        
        Может быть переопределена в подклассах.
        """
        return False

