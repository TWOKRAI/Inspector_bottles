"""frontend_module.state — generic GUI read-model телеметрии.

Публичный API подсистемы «чтение состояния на стороне GUI»:

- :class:`TelemetryViewModel` — локальный read-model: один поток дельт →
  снимок (``snapshot``/``get``) + история в кольцевых буферах (``history``).
  Late-binding: вкладка, открытая после публикации, читает актуальное сразу.
- :data:`DEFAULT_TRACKED_SUFFIXES` — суффиксы штатных gated-метрик фреймворка
  (дефолт для истории VM).
- :class:`TelemetryHistorySource` — read-only диапазонная выборка из SQLite-
  таблицы стока телеметрии (generic: имя таблицы/whitelist метрик/путь БД —
  параметры конструктора).

Модуль generic: не знает ни имён процессов, ни прикладного набора метрик, ни
схемы БД. Приложение передаёт эти параметры тонкой конфигурацией.
"""

from multiprocess_framework.modules.frontend_module.state.telemetry_history import (
    TelemetryHistorySource,
)
from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import (
    DEFAULT_TRACKED_SUFFIXES,
    TelemetryViewModel,
)

__all__ = [
    "TelemetryViewModel",
    "DEFAULT_TRACKED_SUFFIXES",
    "TelemetryHistorySource",
]
