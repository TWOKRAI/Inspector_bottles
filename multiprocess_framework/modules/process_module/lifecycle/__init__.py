"""
Lifecycle компоненты Process Module.
"""

from .gc_discipline import GcDiscipline
from .process_lifecycle import ProcessLifecycle

__all__ = [
    "ProcessLifecycle",
    "GcDiscipline",
]
