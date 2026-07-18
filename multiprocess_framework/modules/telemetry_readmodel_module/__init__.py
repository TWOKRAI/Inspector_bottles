"""telemetry_readmodel_module — generic Qt-free ядро read-model телеметрии.

Одна проекция состояния (снимок ``path → value``) + кольцевые буферы истории,
наполняемые ОДНИМ потоком уже разобранных дельт. Ядро транспорт-агностично и не
зависит от Qt — переиспользуется разными потребителями:

- GUI (:class:`~multiprocess_framework.modules.frontend_module.state.TelemetryViewModel`)
  оборачивает его Qt-коалесингом сигнала ``updated``;
- headless-драйвер диагностики (backend_ctl) наполняет его push'ами
  ``state.changed`` и отдаёт агенту ``telemetry_snapshot``/``telemetry_history``.

Публичный API:
    ITelemetryReadModel      — контракт (interfaces.py)
    TelemetryReadModel       — реализация: snapshot/get/history + ingest
    DEFAULT_TRACKED_SUFFIXES — суффиксы штатных gated-метрик фреймворка (дефолт истории)

Модуль generic: не знает ни имён процессов, ни прикладного набора метрик.
Потребитель передаёт эти параметры тонкой конфигурацией (``tracked_suffixes``).
"""

from .interfaces import ITelemetryReadModel
from .telemetry_read_model import DEFAULT_TRACKED_SUFFIXES, TelemetryReadModel

__all__ = [
    "ITelemetryReadModel",
    "TelemetryReadModel",
    "DEFAULT_TRACKED_SUFFIXES",
]
