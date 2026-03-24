# -*- coding: utf-8 -*-
"""
Схема для COMMAND сообщений.

Пример специализированной схемы для командных сообщений.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional
import time


class CommandMessageSchema(BaseModel):
    """
    Схема для COMMAND сообщений.
    
    Определяет только необходимые поля для командных сообщений.
    Убирает ненужные поля из базовой схемы для производительности.
    """
    
    model_config = ConfigDict(
        extra='forbid',  # Запрещаем дополнительные поля
        frozen=False,
        validate_assignment=True,
    )
    
    # Обязательные поля
    id: str
    type: str = "command"
    sender: str
    targets: List[str]
    timestamp: float = Field(default_factory=time.time)
    
    # Опциональные базовые поля
    priority: str = "normal"
    routers: List[str] = Field(default_factory=lambda: ["internal"])
    channel: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Специфичные поля для COMMAND
    command: str  # Обязательное для COMMAND
    args: Dict[str, Any] = Field(default_factory=dict)
    need_ack: bool = False
    
    def get_schema_info(self) -> Dict[str, str]:
        """Возвращает информацию о схеме."""
        return {
            'schema_name': self.__class__.__name__,
            'schema_module': self.__class__.__module__,
            'schema_path': f"{self.__class__.__module__}.{self.__class__.__name__}",
        }

