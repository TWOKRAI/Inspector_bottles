# -*- coding: utf-8 -*-
"""Services/otel_export — SDK экспорта записей наблюдаемости наружу по OTLP.

Библиотека без процесса: контракт, конфиг-схема и (с Ф1–Ф2) маппер, резолвер
Resource и обёртка OTel SDK. Хост — плагин `Plugins/io/otel_export` в
`GenericProcessApp`; подключается фрагментом топологии.

Публичный контур пакета — контракт из `interfaces.py`:

    from Services.otel_export import RecordMapper, MappedRecord, ExportOutcome

Схема параметров и проверка SDK живут в своих модулях (они тянут pydantic и
метаданные дистрибутивов, контракту это не нужно):

    from Services.otel_export.config import OtelExportConfig
    from Services.otel_export.exporter import sdk_available

Импорт этого пакета НЕ тянет `opentelemetry` — проверяется тестом E3.
"""

from .interfaces import *  # noqa: F401,F403
from .interfaces import __all__ as _INTERFACES_ALL

#: Совпадает с `interfaces.__all__` по построению, а не по переписанному списку:
#: две копии перечня публичных имён разъезжаются молча.
__all__ = list(_INTERFACES_ALL)
