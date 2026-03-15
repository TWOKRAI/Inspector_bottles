"""
Публичный контракт queues-подмодуля.

Re-export IQueueRegistry из shared_resources.core.interfaces.
"""

from ..core.interfaces import IQueueRegistry

__all__ = ["IQueueRegistry"]
