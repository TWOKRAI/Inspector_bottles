"""
Платформо-зависимые адаптеры (Refactored).
"""

from .base import StubPlatformAdapter


def get_platform_adapter():
    """Возвращает адаптер платформы."""
    return StubPlatformAdapter()


__all__ = ["get_platform_adapter", "StubPlatformAdapter"]
