"""
Интерфейсы для DispatchModule.

Определяет контракты для компонентов модуля диспетчеризации сообщений.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Optional, List

from .types.types import DispatchStrategy, HandlerInfo


class IDispatcher(ABC):
    """
    Интерфейс для диспетчера сообщений.
    
    Определяет контракт для всех реализаций диспетчера.
    """
    
    @property
    @abstractmethod
    def manager_name(self) -> str:
        """Уникальное имя менеджера (как у BaseManager)."""
        pass
    
    @abstractmethod
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[DispatchStrategy] = None
    ) -> bool:
        """
        Зарегистрировать обработчик.
        
        Args:
            key: Уникальный ключ обработчика
            handler: Функция-обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные
            efficiency: Уровень эффективности обработчика
            tags: Список тегов для группировки
            strategy: Стратегия для регистрации
            
        Returns:
            True если регистрация успешна
        """
        pass
    
    @abstractmethod
    def dispatch(
        self,
        message: Dict[str, Any],
        key_field: str = "command",
        data_field: str = "data"
    ) -> Any:
        """
        Диспетчеризовать сообщение.
        
        Args:
            message: Сообщение для обработки
            key_field: Поле в сообщении, содержащее ключ диспетчеризации
            data_field: Поле в сообщении, содержащее данные для обработки
            
        Returns:
            Результат работы обработчика или словарь с ошибкой
        """
        pass
    
    @abstractmethod
    def get_handler_info(self, key: str) -> Optional[Dict]:
        """
        Получить информацию о обработчике.
        
        Args:
            key: Ключ обработчика
            
        Returns:
            Словарь с информацией или None
        """
        pass
    
    @abstractmethod
    def get_all_handlers(self) -> List[Dict]:
        """
        Получить информацию обо всех обработчиках.
        
        Returns:
            Список словарей с информацией об обработчиках
        """
        pass
    
    @abstractmethod
    def get_handlers_by_tag(self, tag: str) -> List[Dict]:
        """
        Получить обработчики по тегу.
        
        Args:
            tag: Тег для поиска
            
        Returns:
            Список словарей с информацией об обработчиках
        """
        pass

