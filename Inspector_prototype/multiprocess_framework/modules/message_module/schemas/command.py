# -*- coding: utf-8 -*-
"""
Схема для COMMAND сообщений (строгая валидация, extra='forbid').
"""

import time
from typing import Annotated, Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from ...data_schema_module import FieldMeta, SchemaBase


class CommandMessageSchema(SchemaBase):
    """Только необходимые поля для командных сообщений."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: Annotated[str, FieldMeta("Уникальный ID сообщения")]
    type: str = "command"
    sender: Annotated[str, FieldMeta("Отправитель")]
    targets: Annotated[List[str], FieldMeta("Получатели")]
    timestamp: float = Field(default_factory=time.time)
    priority: str = "normal"
    routers: List[str] = Field(default_factory=lambda: ["internal"])
    channel: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    command: Annotated[str, FieldMeta("Имя команды")]
    args: Dict[str, Any] = Field(default_factory=dict)
    need_ack: bool = False

    def get_schema_info(self) -> Dict[str, str]:
        return {
            "schema_name": self.__class__.__name__,
            "schema_module": self.__class__.__module__,
            "schema_path": f"{self.__class__.__module__}.{self.__class__.__name__}",
        }
