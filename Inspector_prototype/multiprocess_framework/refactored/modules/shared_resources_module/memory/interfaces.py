"""
Публичный контракт memory-подмодуля.

Re-export IMemoryManager из shared_resources.core.interfaces.
"""

from ..core.interfaces import IMemoryManager

__all__ = ["IMemoryManager"]
