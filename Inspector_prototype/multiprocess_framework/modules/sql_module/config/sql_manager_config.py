# -*- coding: utf-8 -*-
"""
SQLManagerConfig — конфигурационная схема SQLManager.

Следует паттерну SchemaBase + @register_schema (ADR-016).
"""
from typing import Annotated, Literal, Optional

from data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("sql_manager")
class SQLManagerConfig(SchemaBase):
    """Конфигурация SQLManager, регистрируется в реестре схем."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "SQLManager"
    url: Annotated[str, FieldMeta("URL подключения к БД")] = "sqlite:///:memory:"
    dialect: Annotated[
        str,
        FieldMeta("Диалект: postgresql, mysql, sqlite"),
    ] = "sqlite"
    mode: Annotated[
        Literal["sync", "async"],
        FieldMeta("Режим: sync или async"),
    ] = "sync"
    pool_size: Annotated[int, FieldMeta("Размер пула соединений", min=1, max=100)] = 5
    max_overflow: Annotated[
        int,
        FieldMeta("Дополнительные соединения сверх pool_size", min=0, max=50),
    ] = 10
    pool_recycle: Annotated[
        int,
        FieldMeta("Переподключение соединений через N секунд", min=60, max=86400),
    ] = 3600
    pool_pre_ping: Annotated[
        bool,
        FieldMeta("Проверка соединения перед использованием"),
    ] = True
    fork_safe: Annotated[
        bool,
        FieldMeta("Использовать NullPool для multiprocess"),
    ] = False
