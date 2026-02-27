"""
Типы данных для модуля диспетчеризации сообщений.

Содержит Enum и dataclasses для работы с обработчиками и сценариями.
"""
from typing import Dict, Any, Callable, List, Set
from dataclasses import dataclass, field
from enum import Enum


class DispatchStrategy(Enum):
    """Стратегии диспетчеризации сообщений."""
    EXACT_MATCH = "exact"           # Точное совпадение ключа
    PATTERN_MATCH = "pattern"        # Регулярные выражения для гибкого сопоставления
    FALLBACK_MATCH = "fallback"      # Fallback стратегия: сначала эффективные методы, потом простые
    CHAIN_MATCH = "chain"            # Цепочки выполнения обработчиков (сценарии)


@dataclass
class HandlerInfo:
    """
    Универсальная информация о зарегистрированном обработчике.
    
    Атрибуты:
        key: Уникальный ключ обработчика
        handler: Функция-обработчик
        expects_full_message: Если True, обработчик получает всё сообщение, иначе только data поле
        metadata: Дополнительные метаданные обработчика
        efficiency: Уровень эффективности обработчика (чем выше, тем эффективнее, используется для FALLBACK_MATCH)
        tags: Теги для группировки обработчиков
        stage: Этап выполнения в цепочке (используется для CHAIN_MATCH)
    """
    key: str
    handler: Callable
    expects_full_message: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    efficiency: int = 0  # Переименовано из priority для ясности
    tags: Set[str] = field(default_factory=set)
    stage: int = 0  # Этап выполнения в цепочке (для CHAIN_MATCH)


@dataclass
class Scenario:
    """
    Сценарий выполнения - цепочка обработчиков с порядком выполнения.
    
    Атрибуты:
        name: Уникальное имя сценария
        handlers: Список обработчиков, отсортированных по stage
        description: Описание сценария
        metadata: Дополнительные метаданные сценария
    """
    name: str
    handlers: List[HandlerInfo] = field(default_factory=list)
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_handler(self, handler: HandlerInfo, stage: int) -> bool:
        """Добавить обработчик на определенный этап."""
        handler.stage = stage
        self.handlers.append(handler)
        self.handlers.sort(key=lambda h: h.stage)
        return True
    
    def remove_handler(self, handler_key: str) -> bool:
        """Удалить обработчик по ключу."""
        self.handlers = [h for h in self.handlers if h.key != handler_key]
        return True
    
    def reorder_handler(self, handler_key: str, new_stage: int) -> bool:
        """Изменить порядок обработчика в цепочке."""
        for handler in self.handlers:
            if handler.key == handler_key:
                handler.stage = new_stage
                self.handlers.sort(key=lambda h: h.stage)
                return True
        return False
    
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о сценарии."""
        return {
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "handlers_count": len(self.handlers),
            "handlers": [
                {
                    "key": h.key,
                    "stage": h.stage,
                    "metadata": h.metadata,
                    "tags": list(h.tags)
                }
                for h in self.handlers
            ]
        }



