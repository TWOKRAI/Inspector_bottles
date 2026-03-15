"""
Публичный контракт events-подмодуля.

Re-export IEventManager из shared_resources.core.interfaces.
"""

from ..core.interfaces import IEventManager

__all__ = ["IEventManager"]
