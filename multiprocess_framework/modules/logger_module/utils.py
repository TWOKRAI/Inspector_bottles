"""Re-export FallbackLogger для кода, уже импортирующего из logger_module.utils."""
from .._fallback import FallbackLogger

__all__ = ["FallbackLogger"]
