from typing import Dict, Any, Callable, Optional, List, Union, Set
from dataclasses import dataclass, field
from enum import Enum

class DispatchStrategy(Enum):
    EXACT_MATCH = "exact"      # Точное совпадение ключа
    PATTERN_MATCH = "pattern"  # Регулярные выражения
    PRIORITY_MATCH = "priority" # Приоритетная обработка

@dataclass
class HandlerInfo:
    """Универсальная информация о зарегистрированном обработчике"""
    key: str
    handler: Callable
    expects_full_message: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    tags: Set[str] = field(default_factory=set)

class Dispatcher:
    """
    Универсальный диспетчер для обработки сообщений различного типа.
    """

    def __init__(self, name: str, strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH):
        self.name = name
        self.strategy = strategy
        self.handlers: Dict[str, HandlerInfo] = {}

    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        priority: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Регистрация обработчика с метаданными и приоритетом.
        """
        try:
            handler_info = HandlerInfo(
                key=key,
                handler=handler,
                expects_full_message=expects_full_message,
                metadata=metadata or {},
                priority=priority,
                tags=set(tags) if tags else set()
            )
            self.handlers[key] = handler_info
            return True
        except Exception as e:
            print(f"UniversalDispatcher {self.name}: Failed to register handler '{key}': {e}")
            return False

    def dispatch(
        self,
        message: Dict[str, Any],
        key_field: str = "command",
        data_field: str = "data"
    ) -> Any:
        """
        Основной метод диспетчеризации сообщений.
        """
        try:
            # Извлекаем ключ для диспетчеризации
            key = message.get(key_field)
            if not key:
                return {"status": "error", "reason": f"Key field '{key_field}' not found"}

            # Ищем подходящий обработчик
            handler_info = self._find_handler(key)
            if not handler_info:
                return {"status": "error", "reason": f"No handler for key '{key}'"}

            # Подготавливаем данные для обработчика
            handler_data = message if handler_info.expects_full_message else message.get(data_field, {})

            # Выполняем обработчик
            return handler_info.handler(handler_data)

        except Exception as e:
            return {"status": "error", "reason": f"Dispatch failed: {str(e)}"}

    def _find_handler(self, key: str) -> Optional[HandlerInfo]:
        """Поиск обработчика по выбранной стратегии"""
        if self.strategy == DispatchStrategy.EXACT_MATCH:
            return self.handlers.get(key)

        elif self.strategy == DispatchStrategy.PRIORITY_MATCH:
            # Возвращаем обработчик с самым высоким приоритетом
            return max(
                (h for h in self.handlers.values() if h.key == key),
                key=lambda h: h.priority,
                default=None
            )

        # Для PATTERN_MATCH можно добавить логику регулярных выражений
        return self.handlers.get(key)

    def get_handler_info(self, key: str) -> Optional[Dict]:
        """Получение информации о конкретном обработчике"""
        if key not in self.handlers:
            return None
        info = self.handlers[key]
        return {
            "key": info.key,
            "metadata": info.metadata,
            "priority": info.priority,
            "tags": list(info.tags)
        }

    def get_all_handlers(self) -> List[Dict]:
        """Получение информации обо всех обработчиках"""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "priority": h.priority,
                "tags": list(h.tags)
            }
            for h in self.handlers.values()
        ]

    def get_handlers_by_tag(self, tag: str) -> List[Dict]:
        """Получение обработчиков по тегу"""
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "priority": h.priority,
                "tags": list(h.tags)
            }
            for h in self.handlers.values() if tag in h.tags
        ]
