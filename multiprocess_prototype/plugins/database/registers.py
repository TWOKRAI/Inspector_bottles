"""DatabaseRegisters — все параметры database плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase


@register_schema("DatabaseRegistersV1")
class DatabaseRegisters(SchemaBase):
    """Все параметры database — путь к БД + настройки batch."""

    db_path: Annotated[str, FieldMeta(
        "DB Path", info="Путь к SQLite файлу",
    )] = "data/inspector.db"

    batch_size: Annotated[int, FieldMeta(
        "Batch Size", info="Размер batch для flush",
        min=1, max=10000,
    )] = 100

    flush_interval_sec: Annotated[float, FieldMeta(
        "Flush Interval", info="Интервал авто-flush", unit="s",
        min=0.1,
    )] = 2.0
