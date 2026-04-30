# -*- coding: utf-8 -*-
"""
Схема для LOG сообщений (строгая валидация, extra='forbid').
"""

import time
from typing import Annotated, Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from ...data_schema_module import FieldMeta, SchemaBase


class LogMessageSchema(SchemaBase):
    """Только необходимые поля для лог-сообщений."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: Annotated[str, FieldMeta("Уникальный ID сообщения")]
    type: str = "log"
    sender: Annotated[str, FieldMeta("Отправитель")]
    targets: List[str] = Field(default_factory=lambda: ["logger"])
    timestamp: float = Field(default_factory=time.time)
    priority: str = "normal"
    routers: List[str] = Field(default_factory=lambda: ["log"])
    channel: Optional[str] = Field(default="log")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    level: Annotated[str, FieldMeta("Уровень лога")]
    message: Annotated[str, FieldMeta("Текст лога")]
    module: str = "main"

    def get_schema_info(self) -> Dict[str, str]:
        return {
            "schema_name": self.__class__.__name__,
            "schema_module": self.__class__.__module__,
            "schema_path": f"{self.__class__.__module__}.{self.__class__.__name__}",
        }
