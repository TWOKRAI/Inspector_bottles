"""manager — серверная часть StateStore.

StateStoreManager — компонент для встраивания в ProcessManagerProcess.
DeltaDispatcher — рассылка дельт подписчикам через IPC.
"""
from .delta_dispatcher import DeltaDispatcher
from .state_store_manager import StateStoreManager

__all__ = [
    "StateStoreManager",
    "DeltaDispatcher",
]
