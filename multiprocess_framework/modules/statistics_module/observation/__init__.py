# -*- coding: utf-8 -*-
"""Порт наблюдений процесса — четвёртый канонический слот рядом с logger/stats/error.

Пакет НЕ переэкспортируется из ``statistics_module/__init__.py`` намеренно.
``observation_manager`` тянет ``process_module.heartbeat.telemetry`` (хранилище
уровней, которое он оборачивает), а ``process_module`` тянет
``statistics_module`` (``StatsManager`` в ``ProcessManagers.create_all``).
Eager-реэкспорт замкнул бы кольцо на импорте пакета — тот же класс, что уже
ловился на переносе schema-модуля с back-compat шимом. Импортировать явным
путём: ``from ...statistics_module.observation.observation_manager import ...``.
"""

from .observation_manager import (
    OBSERVATION_SLOT,
    ObservationManager,
    ObservationPort,
    PluginObservationHandle,
    observation_port,
)

__all__ = [
    "OBSERVATION_SLOT",
    "ObservationManager",
    "ObservationPort",
    "PluginObservationHandle",
    "observation_port",
]
