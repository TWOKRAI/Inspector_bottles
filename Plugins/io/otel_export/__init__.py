# -*- coding: utf-8 -*-
"""otel_export — хост экспортёра OTLP: плагин в GenericProcessApp.

Ф2.1: есть дверь конфига (регистры), identity плагина и сам `OtelExportPlugin` —
приём хвоста наблюдаемости, отметка приёма, счётчики, команды `otel_export.status`
и `otel_export.flush`. Отправки наружу ещё нет: `LogExporter` приходит в Ф2.2/2.4.

Импорт этого пакета исполняет `@register_plugin` и НЕ тянет `opentelemetry` в
`sys.modules` — SDK трогает только `Services/otel_export/exporter.py`, лениво,
внутри функции.
"""

from .config import OtelExportPluginConfig
from .plugin import OtelExportPlugin
from .registers import OtelExportRegisters

__all__ = [
    "OtelExportPlugin",
    "OtelExportPluginConfig",
    "OtelExportRegisters",
]
