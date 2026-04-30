# -*- coding: utf-8 -*-
"""
Typed команды для SQLManager.execute_command.

Pydantic-модели для валидации на границе (Dict at Boundary).
"""
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class DBQueryCommand(BaseModel):
    """Команда SELECT."""

    command: Literal["db.query"] = "db.query"
    sql: str = Field(..., description="SQL-запрос")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Параметры")
    timeout: int = Field(default=30, ge=1, le=300, description="Таймаут в секундах")


class DBExecuteCommand(BaseModel):
    """Команда DML (INSERT, UPDATE, DELETE)."""

    command: Literal["db.execute"] = "db.execute"
    sql: str = Field(..., description="SQL-запрос")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Параметры")


class DBInsertCommand(BaseModel):
    """Команда вставки по таблице и данным."""

    command: Literal["db.insert"] = "db.insert"
    table: str = Field(..., description="Имя таблицы")
    data: Dict[str, Any] = Field(default_factory=dict, description="Данные для вставки")
