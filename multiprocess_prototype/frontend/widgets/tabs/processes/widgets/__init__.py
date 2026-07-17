# -*- coding: utf-8 -*-
"""Виджеты вкладки «Процессы»: насыщенная карточка + таблица воркеров + диалоги."""

from __future__ import annotations

from .dialogs import CreateProcessDialog, CreateWorkerDialog
from .process_card import ProcessCard
from .telemetry_sparkline import TelemetrySparkline
from .worker_table import WorkerTable

__all__ = ["ProcessCard", "WorkerTable", "CreateProcessDialog", "CreateWorkerDialog", "TelemetrySparkline"]
