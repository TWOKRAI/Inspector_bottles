"""TelemetrySinkRegisters — параметры плагина telemetry_sink.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import register_schema


@register_schema("TelemetrySinkRegistersV1")
class TelemetrySinkRegisters(SchemaBase):
    """Параметры стока телеметрии — путь к БД и период семпла."""

    db_path: Annotated[
        str,
        FieldMeta(
            "DB Path",
            info="Путь к SQLite файлу с историей телеметрии",
        ),
    ] = "data/telemetry.db"

    sample_interval_sec: Annotated[
        float,
        FieldMeta(
            "Sample Interval",
            info="Период снятия снимка кэша подписки",
            unit="s",
            min=0.5,
        ),
    ] = 5.0

    retention_days: Annotated[
        int,
        FieldMeta(
            "Retention Days",
            info="Хранить историю N дней (0 = без ретенции; чистка по команде purge_old)",
            unit="d",
            min=0,
        ),
    ] = 0
