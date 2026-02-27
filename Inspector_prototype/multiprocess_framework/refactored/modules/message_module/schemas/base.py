"""
Базовая схема сообщения (Pydantic v2).

Определяет базовые поля для всех типов сообщений.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional
import time


class BaseMessageSchema(BaseModel):
    """
    Базовая схема сообщения.
    
    Определяет обязательные и опциональные поля для всех типов сообщений.
    Используется как основа для специализированных схем.
    
    Производительность:
    - model_config с frozen=False для производительности
    - Использует Pydantic v2 для быстрой валидации
    """
    
    model_config = ConfigDict(
        # Разрешаем дополнительные поля для обратной совместимости
        # Но валидация будет через MessageValidator
        extra='allow',
        # Не замораживаем для производительности
        frozen=False,
        # Валидация по умолчанию
        validate_assignment=True,
    )
    
    # Обязательные поля
    id: str
    type: str
    sender: str
    targets: List[str]
    timestamp: float = Field(default_factory=time.time)
    
    # Опциональные поля с дефолтными значениями
    priority: str = "normal"
    routers: List[str] = Field(default_factory=lambda: ["internal"])
    channel: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Специфичные поля для разных типов сообщений (опциональные)
    # GENERAL
    content: Optional[Any] = None
    
    # COMMAND
    command: Optional[str] = None
    args: Dict[str, Any] = Field(default_factory=dict)
    need_ack: bool = False
    
    # LOG
    level: Optional[str] = None
    message: Optional[str] = None
    module: str = "main"
    
    # SYSTEM
    action: Optional[str] = None
    data: Optional[Any] = None
    
    # BROADCAST
    exclude: List[str] = Field(default_factory=list)
    
    # DATA
    data_type: Optional[str] = None
    use_shared_memory: bool = False
    memory_key: Optional[str] = None
    
    # REQUEST
    request_type: Optional[str] = None
    query: Optional[Any] = None
    timeout: float = 5.0
    
    # RESPONSE
    request_id: Optional[str] = None
    success: bool = True
    result: Optional[Any] = None
    error: Optional[str] = None
    
    # EVENT
    event_type: Optional[str] = None
    event_data: Optional[Any] = None
    
    def get_schema_info(self) -> Dict[str, str]:
        """
        Возвращает информацию о схеме для хранения в сообщении.
        
        Returns:
            Словарь с информацией о схеме (путь, название, версия)
        """
        return {
            'schema_name': self.__class__.__name__,
            'schema_module': self.__class__.__module__,
            'schema_path': f"{self.__class__.__module__}.{self.__class__.__name__}",
        }

