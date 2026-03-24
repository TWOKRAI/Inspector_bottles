# -*- coding: utf-8 -*-
"""
Схема для LOG сообщений.

Пример специализированной схемы для лог-сообщений.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional
import time


class LogMessageSchema(BaseModel):
    """
    Схема для LOG сообщений.
    
    Определяет только необходимые поля для лог-сообщений.
    Убирает ненужные поля из базовой схемы для производительности.
    """
    
    model_config = ConfigDict(
        extra='forbid',  # Запрещаем дополнительные поля
        frozen=False,
        validate_assignment=True,
    )
    
    # Обязательные поля
    id: str
    type: str = "log"
    sender: str
    targets: List[str] = Field(default_factory=lambda: ["logger"])
    timestamp: float = Field(default_factory=time.time)
    
    # Опциональные базовые поля
    priority: str = "normal"
    routers: List[str] = Field(default_factory=lambda: ["log"])
    channel: Optional[str] = Field(default="log")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Специфичные поля для LOG
    level: str  # Обязательное для LOG
    message: str  # Обязательное для LOG
    module: str = "main"
    
    def get_schema_info(self) -> Dict[str, str]:
        """Возвращает информацию о схеме."""
        return {
            'schema_name': self.__class__.__name__,
            'schema_module': self.__class__.__module__,
            'schema_path': f"{self.__class__.__module__}.{self.__class__.__name__}",
        }

