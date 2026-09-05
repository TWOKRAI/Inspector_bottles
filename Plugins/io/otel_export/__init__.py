# -*- coding: utf-8 -*-
"""otel_export — хост экспортёра OTLP: плагин в GenericProcessApp.

Стадия `contract` (Ф0.4): есть дверь конфига (регистры) и identity плагина.
Самого `plugin.py` ещё нет — он приходит в Ф2.1, тогда же сюда добавится
реэкспорт `OtelExportPlugin`.
"""

from .config import OtelExportPluginConfig
from .registers import OtelExportRegisters

__all__ = [
    "OtelExportPluginConfig",
    "OtelExportRegisters",
]
