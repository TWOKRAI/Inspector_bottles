"""
Базовый класс диспетчера для обработки сообщений.

Содержит общий функционал для всех типов диспетчеров.
"""
from typing import Dict, Any, Callable, Optional, List
from abc import ABC, abstractmethod

from .types import DispatchStrategy, HandlerInfo


class BaseDispatcher(ABC):
    """
    Базовый класс диспетчера для обработки сообщений.
    
    Содержит общий функционал для всех типов диспетчеров.
    """
    
    def __init__(self, name: str, strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH):
        """
        Инициализация базового диспетчера.
        
        Args:
            name: Уникальное имя диспетчера для идентификации
            strategy: Стратегия диспетчеризации (по умолчанию EXACT_MATCH)
        """
        self.name = name
        self.strategy = strategy
        self.handlers: Dict[str, HandlerInfo] = {}
    
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Регистрация обработчика с метаданными.
        
        Args:
            key: Уникальный ключ обработчика
            handler: Функция-обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные
            efficiency: Уровень эффективности обработчика
            tags: Список тегов для группировки
            
        Returns:
            True если регистрация успешна, False в случае ошибки
        """
        if key in self.handlers:
            print(f"BaseDispatcher {self.name}: Handler '{key}' already exists. Use overwrite_handler() to replace it.")
            return False
        
        try:
            handler_info = HandlerInfo(
                key=key,
                handler=handler,
                expects_full_message=expects_full_message,
                metadata=metadata or {},
                efficiency=efficiency,
                tags=set(tags) if tags else set()
            )
            self.handlers[key] = handler_info
            return True
        except Exception as e:
            print(f"BaseDispatcher {self.name}: Failed to register handler '{key}': {e}")
            return False
    
    def overwrite_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Принудительная перезапись обработчика.
        
        Args:
            key: Ключ обработчика для перезаписи
            handler: Новая функция-обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные
            efficiency: Уровень эффективности обработчика
            tags: Список тегов для группировки
            
        Returns:
            True если перезапись успешна, False в случае ошибки
        """
        try:
            handler_info = HandlerInfo(
                key=key,
                handler=handler,
                expects_full_message=expects_full_message,
                metadata=metadata or {},
                efficiency=efficiency,
                tags=set(tags) if tags else set()
            )
            self.handlers[key] = handler_info
            print(f"BaseDispatcher {self.name}: Handler '{key}' overwritten successfully.")
            return True
        except Exception as e:
            print(f"BaseDispatcher {self.name}: Failed to overwrite handler '{key}': {e}")
            return False
    
    def update_handler_efficiency(self, key: str, new_efficiency: int) -> bool:
        """Обновление уровня эффективности обработчика."""
        if key not in self.handlers:
            return False
        self.handlers[key].efficiency = new_efficiency
        return True
    
    def update_handler_metadata(self, key: str, new_metadata: Dict[str, Any]) -> bool:
        """Обновление метаданных обработчика."""
        if key not in self.handlers:
            return False
        self.handlers[key].metadata = new_metadata
        return True
    
    def update_handler_tags(self, key: str, new_tags: List[str]) -> bool:
        """Обновление тегов обработчика."""
        if key not in self.handlers:
            return False
        self.handlers[key].tags = set(new_tags)
        return True
    
    def update_handler_function(self, key: str, new_handler: Callable) -> bool:
        """Обновление функции-обработчика."""
        if key not in self.handlers:
            return False
        self.handlers[key].handler = new_handler
        return True
    
    def update_expects_full_message(self, key: str, expects_full: bool) -> bool:
        """Обновление флага expects_full_message."""
        if key not in self.handlers:
            return False
        self.handlers[key].expects_full_message = expects_full
        return True
    
    def dispatch(
        self,
        message: Dict[str, Any],
        key_field: str = "command",
        data_field: str = "data"
    ) -> Any:
        """
        Основной метод диспетчеризации сообщений.
        
        Args:
            message: Сообщение для обработки
            key_field: Поле в сообщении, содержащее ключ диспетчеризации
            data_field: Поле в сообщении, содержащее данные для обработки
            
        Returns:
            Результат работы обработчика или словарь с ошибкой
        """
        try:
            key = message.get(key_field)
            if not key:
                return {"status": "error", "reason": f"Key field '{key_field}' not found"}

            handler_info = self._find_handler(key)
            if not handler_info:
                return {"status": "error", "reason": f"No handler for key '{key}'"}

            handler_data = message if handler_info.expects_full_message else message.get(data_field, {})
            return handler_info.handler(handler_data)

        except Exception as e:
            return {"status": "error", "reason": f"Dispatch failed: {str(e)}"}
    
    @abstractmethod
    def _find_handler(self, key: str) -> Optional[HandlerInfo]:
        """Поиск обработчика по выбранной стратегии. Должен быть реализован в подклассах."""
        pass
    
    def get_handler_info(self, key: str) -> Optional[Dict]:
        """Получение информации о конкретном обработчике"""
        if key not in self.handlers:
            return None
        info = self.handlers[key]
        return {
            "key": info.key,
            "metadata": info.metadata,
            "efficiency": info.efficiency,
            "tags": list(info.tags),
            "stage": info.stage
        }
    
    def get_all_handlers(self) -> List[Dict]:
        """Получение информации обо всех обработчиках."""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in self.handlers.values()
        ]
    
    def get_handlers_by_tag(self, tag: str) -> List[Dict]:
        """Получение обработчиков по тегу."""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in self.handlers.values() if tag in h.tags
        ]

