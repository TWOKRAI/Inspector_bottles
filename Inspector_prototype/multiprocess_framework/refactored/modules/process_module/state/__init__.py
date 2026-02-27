"""
Управление состоянием процессов (Refactored).

Модуль для работы с состояниями процессов и межпроцессным взаимодействием.
"""

from .process_state import ProcessState
from .process_data import ProcessData, ProcessDataKeys, QueuesProxy, EventsProxy
from .process_state_registry import ProcessStateRegistry

__all__ = [
    'ProcessState',
    'ProcessData',
    'ProcessDataKeys',
    'QueuesProxy',
    'EventsProxy',
    'ProcessStateRegistry',
]
