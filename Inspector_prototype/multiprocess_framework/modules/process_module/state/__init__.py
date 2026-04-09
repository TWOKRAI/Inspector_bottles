"""
Управление состоянием процессов (Refactored).

Модуль для работы с состояниями процессов и межпроцессным взаимодействием.
"""

from .process_state import ProcessState
from .process_data import ProcessData, ProcessDataKeys, QueuesProxy, EventsProxy

__all__ = [
    "ProcessState",
    "ProcessData",
    "ProcessDataKeys",
    "QueuesProxy",
    "EventsProxy",
]
