"""
Стратегия fallback с приоритетом эффективности.
"""
from typing import Dict, Any, Callable, Optional, List

from .base_strategy import BaseStrategy
from ..types import HandlerInfo


class FallbackMatchStrategy(BaseStrategy):
    """
    Стратегия fallback с приоритетом эффективности.
    
    Позволяет регистрировать несколько обработчиков с одним ключом.
    При поиске возвращается обработчик с наивысшей эффективностью.
    """
    
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        handlers_storage: Dict[str, List[HandlerInfo]] = None
    ) -> bool:
        """Регистрация обработчика (разрешаем несколько с одним ключом)."""
        if handlers_storage is None:
            handlers_storage = {}
        
        if key not in handlers_storage:
            handlers_storage[key] = []
        
        try:
            handler_info = HandlerInfo(
                key=key,
                handler=handler,
                expects_full_message=expects_full_message,
                metadata=metadata or {},
                efficiency=efficiency,
                tags=set(tags) if tags else set()
            )
            handlers_storage[key].append(handler_info)
            # Сортируем по эффективности (высшая эффективность первый)
            handlers_storage[key].sort(key=lambda h: h.efficiency, reverse=True)
            return True
        except Exception as e:
            print(f"FallbackMatchStrategy {self.dispatcher_name}: Failed to register handler '{key}': {e}")
            return False
    
    def find_handler(self, key: str, handlers_storage: Dict[str, List[HandlerInfo]]) -> Optional[HandlerInfo]:
        """Поиск обработчика с наивысшей эффективностью."""
        if key not in handlers_storage or not handlers_storage[key]:
            return None
        
        # Возвращаем обработчик с самой высокой эффективностью
        return handlers_storage[key][0]
    
    def get_all_handlers(self, handlers_storage: Dict[str, List[HandlerInfo]]) -> List[Dict]:
        """Получить все обработчики."""
        all_handlers = []
        for handlers_list in handlers_storage.values():
            all_handlers.extend(handlers_list)
        
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in all_handlers
        ]
    
    def get_handlers_by_tag(self, tag: str, handlers_storage: Dict[str, List[HandlerInfo]]) -> List[Dict]:
        """Получить обработчики по тегу."""
        all_handlers = []
        for handlers_list in handlers_storage.values():
            all_handlers.extend(handlers_list)
        
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in all_handlers if tag in h.tags
        ]
    
    def update_handler_efficiency(
        self,
        key: str,
        new_efficiency: int,
        handlers_storage: Dict[str, List[HandlerInfo]]
    ) -> bool:
        """Обновление эффективности всех обработчиков с ключом."""
        if key not in handlers_storage:
            return False
        
        for handler in handlers_storage[key]:
            handler.efficiency = new_efficiency
        
        # Пересортируем после изменения эффективности
        handlers_storage[key].sort(key=lambda h: h.efficiency, reverse=True)
        return True
    
    def update_handler_metadata(
        self,
        key: str,
        new_metadata: Dict[str, Any],
        handlers_storage: Dict[str, List[HandlerInfo]]
    ) -> bool:
        """Обновление метаданных всех обработчиков с ключом."""
        if key not in handlers_storage:
            return False
        
        for handler in handlers_storage[key]:
            handler.metadata = new_metadata
        return True
    
    def update_handler_tags(
        self,
        key: str,
        new_tags: List[str],
        handlers_storage: Dict[str, List[HandlerInfo]]
    ) -> bool:
        """Обновление тегов всех обработчиков с ключом."""
        if key not in handlers_storage:
            return False
        
        for handler in handlers_storage[key]:
            handler.tags = set(new_tags)
        return True
    
    def update_handler_function(
        self,
        key: str,
        new_handler: Callable,
        handlers_storage: Dict[str, List[HandlerInfo]]
    ) -> bool:
        """Обновление функции всех обработчиков с ключом."""
        if key not in handlers_storage:
            return False
        
        for handler in handlers_storage[key]:
            handler.handler = new_handler
        return True
    
    def update_expects_full_message(
        self,
        key: str,
        expects_full: bool,
        handlers_storage: Dict[str, List[HandlerInfo]]
    ) -> bool:
        """Обновление флага expects_full_message для всех обработчиков с ключом."""
        if key not in handlers_storage:
            return False
        
        for handler in handlers_storage[key]:
            handler.expects_full_message = expects_full
        return True



