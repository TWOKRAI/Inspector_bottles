"""
shared_resources_module — публичный контракт (interfaces.py).

Реэкспортирует интерфейсы из core/interfaces.py для удобства.
Единственный файл, от которого должны зависеть другие модули.
"""

from .core.interfaces import (
    IQueueRegistry,
    IEventManager,
    IMemoryManager,
    IProcessStateRegistry,
    ISharedResourcesManager,
)

__all__ = [
    "IQueueRegistry",
    "IEventManager",
    "IMemoryManager",
    "IProcessStateRegistry",
    "ISharedResourcesManager",
]
