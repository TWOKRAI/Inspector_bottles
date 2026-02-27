"""
Process Module - Модуль процессов системы.

Разделен на логические компоненты:
- ProcessCore - базовый жизненный цикл
- ProcessConfigHandler - работа с конфигурацией
- ProcessManagers - управление менеджерами
- ProcessCommunication - межпроцессная коммуникация
- ProcessModule - главный класс, объединяющий все компоненты
- ProcessData - данные процесса (очереди, события, метаданные)
- ProcessStateRegistry - реестр состояний процессов
"""

from .process_module import ProcessModule
from .core import ProcessCore
from .config_handler import ProcessConfigHandler
from .communication import ProcessCommunication
from .process_data import ProcessData, ProcessDataKeys
from .process_state_registry import ProcessStateRegistry

__all__ = [
    'ProcessModule',
    'ProcessCore',
    'ProcessConfigHandler',
    'ProcessManagers',
    'ProcessCommunication',
    'ProcessData',
    'ProcessDataKeys',
    'ProcessStateRegistry',
]

