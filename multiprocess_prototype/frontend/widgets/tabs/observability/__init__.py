# -*- coding: utf-8 -*-
"""Вкладки наблюдаемости Логи/Ошибки/Статистика (Ф5.19) — один RecordHistoryPanel на kind."""

from .observability_tabs import ObservabilityTabs
from .record_history_panel import RecordHistoryPanel
from .record_history_presenter import RecordHistoryPresenter
from .record_source import RecordSource, open_default_source

__all__ = [
    "ObservabilityTabs",
    "RecordHistoryPanel",
    "RecordHistoryPresenter",
    "RecordSource",
    "open_default_source",
]
