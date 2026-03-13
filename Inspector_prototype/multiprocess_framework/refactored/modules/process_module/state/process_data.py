"""
ProcessData — обратная совместимость.

Класс перенесён в shared_resources_module.state.process_data
для устранения циклической зависимости.

Этот файл сохраняется как алиас для старых импортов.
"""

from ...shared_resources_module.state.process_data import (
    ProcessData,
    ProcessDataKeys,
    QueuesProxy,
    EventsProxy,
)

__all__ = ["ProcessData", "ProcessDataKeys", "QueuesProxy", "EventsProxy"]
