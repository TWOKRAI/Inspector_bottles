"""
Стратегия точного совпадения ключей.
"""
from typing import Dict, Any, Callable, Optional, List

from .base_strategy import BaseStrategy
from ..types import HandlerInfo


class ExactMatchStrategy(BaseStrategy):
    """
    Стратегия точного совпадения ключей.
    
    Обработчики регистрируются с уникальными ключами.
    Поиск происходит по точному совпадению ключа.
    """
    
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
        """Регистрация обработчика с проверкой дубликатов."""
        if handlers_storage is None:
            handlers_storage = {}
        
        if key in handlers_storage:
            print(f"ExactMatchStrategy {self.dispatcher_name}: Handler '{key}' already exists. Use overwrite_handler() to replace it.")
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
            handlers_storage[key] = handler_info
            return True
        except Exception as e:
            print(f"ExactMatchStrategy {self.dispatcher_name}: Failed to register handler '{key}': {e}")
            return False
    
    def find_handler(self, key: str, handlers_storage: Dict[str, HandlerInfo]) -> Optional[HandlerInfo]:
        """Поиск обработчика по точному совпадению ключа."""
        return handlers_storage.get(key)
    
    def get_all_handlers(self, handlers_storage: Dict[str, HandlerInfo]) -> List[Dict]:
        """Получить все обработчики."""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in handlers_storage.values()
        ]
    
    def get_handlers_by_tag(self, tag: str, handlers_storage: Dict[str, HandlerInfo]) -> List[Dict]:
        """Получить обработчики по тегу."""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in handlers_storage.values() if tag in h.tags
        ]
    
    def update_handler_efficiency(
        self,
        key: str,
        new_efficiency: int,
        handlers_storage: Dict[str, HandlerInfo]
    ) -> bool:
        """Обновление эффективности обработчика."""
        if key not in handlers_storage:
            return False
        handlers_storage[key].efficiency = new_efficiency
        return True
    
    def update_handler_metadata(
        self,
        key: str,
        new_metadata: Dict[str, Any],
        handlers_storage: Dict[str, HandlerInfo]
    ) -> bool:
        """Обновление метаданных обработчика."""
        if key not in handlers_storage:
            return False
        handlers_storage[key].metadata = new_metadata
        return True
    
    def update_handler_tags(
        self,
        key: str,
        new_tags: List[str],
        handlers_storage: Dict[str, HandlerInfo]
    ) -> bool:
        """Обновление тегов обработчика."""
        if key not in handlers_storage:
            return False
        handlers_storage[key].tags = set(new_tags)
        return True
    
    def update_handler_function(
        self,
        key: str,
        new_handler: Callable,
        handlers_storage: Dict[str, HandlerInfo]
    ) -> bool:
        """Обновление функции обработчика."""
        if key not in handlers_storage:
            return False
        handlers_storage[key].handler = new_handler
        return True
    
    def update_expects_full_message(
        self,
        key: str,
        expects_full: bool,
        handlers_storage: Dict[str, HandlerInfo]
    ) -> bool:
        """Обновление флага expects_full_message."""
        if key not in handlers_storage:
            return False
        handlers_storage[key].expects_full_message = expects_full
        return True



