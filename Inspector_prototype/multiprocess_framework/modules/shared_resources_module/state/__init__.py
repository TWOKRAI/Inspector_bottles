"""
shared_resources_module.state — данные процессов.
"""

from .process_data import ProcessData, ProcessDataKeys, QueuesProxy, EventsProxy
from .process_state_registry import ProcessStateRegistry

__all__ = [
    "ProcessData",
    "ProcessDataKeys",
    "QueuesProxy",
    "EventsProxy",
    "ProcessStateRegistry",
]
