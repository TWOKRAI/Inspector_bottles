"""
Стратегия сопоставления по регулярным выражениям.
"""
import re
from typing import Dict, Any, Callable, Optional, List

from .base_strategy import BaseStrategy
from ..types.types import HandlerInfo


class PatternMatchStrategy(BaseStrategy):
    """
    Стратегия сопоставления по регулярным выражениям.
    
    Обработчики регистрируются с regex паттернами в качестве ключей.
    Поиск происходит по первому подходящему паттерну.
    """
    
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        handlers_storage: List[HandlerInfo] = None
    ) -> bool:
        """Регистрация обработчика с валидацией regex паттерна."""
        if handlers_storage is None:
            handlers_storage = []
        
        # Проверяем валидность паттерна
        try:
            re.compile(key)
        except re.error:
            self._warn_log(f"PatternMatchStrategy {self.dispatcher_name}: Invalid regex pattern '{key}'")
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
            handlers_storage.append(handler_info)
            return True
        except Exception as e:
            self._err_log(f"PatternMatchStrategy {self.dispatcher_name}: Failed to register handler '{key}': {e}")
            return False
    
    def find_handler(self, key: str, handlers_storage: List[HandlerInfo]) -> Optional[HandlerInfo]:
        """Поиск обработчика по первому подходящему паттерну."""
        for handler_info in handlers_storage:
            try:
                if re.fullmatch(handler_info.key, key):
                    return handler_info
            except re.error:
                continue  # Пропускаем невалидные паттерны
        return None
    
    def get_all_handlers(self, handlers_storage: List[HandlerInfo]) -> List[Dict]:
        """Получить все обработчики."""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in handlers_storage
        ]
    
    def get_handlers_by_tag(self, tag: str, handlers_storage: List[HandlerInfo]) -> List[Dict]:
        """Получить обработчики по тегу."""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in handlers_storage if tag in h.tags
        ]
    
    def update_handler_metadata(
        self,
        key: str,
        new_metadata: Dict[str, Any],
        handlers_storage: List[HandlerInfo]
    ) -> bool:
        """Обновление метаданных обработчика."""
        for handler in handlers_storage:
            if handler.key == key:
                handler.metadata = new_metadata
                return True
        return False
    
    def update_handler_tags(
        self,
        key: str,
        new_tags: List[str],
        handlers_storage: List[HandlerInfo]
    ) -> bool:
        """Обновление тегов обработчика."""
        for handler in handlers_storage:
            if handler.key == key:
                handler.tags = set(new_tags)
                return True
        return False
    
    def update_handler_function(
        self,
        key: str,
        new_handler: Callable,
        handlers_storage: List[HandlerInfo]
    ) -> bool:
        """Обновление функции обработчика."""
        for handler in handlers_storage:
            if handler.key == key:
                handler.handler = new_handler
                return True
        return False
    
    def update_expects_full_message(
        self,
        key: str,
        expects_full: bool,
        handlers_storage: List[HandlerInfo]
    ) -> bool:
        """Обновление флага expects_full_message."""
        for handler in handlers_storage:
            if handler.key == key:
                handler.expects_full_message = expects_full
                return True
        return False

