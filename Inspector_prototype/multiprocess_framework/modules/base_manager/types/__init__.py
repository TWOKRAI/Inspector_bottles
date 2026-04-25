"""
base_manager types — общие типы и перечисления фреймворка.

Единый источник ProcessStatus для всех модулей (ADR-117).
"""

from .process_status import ProcessStatus

__all__ = [
    "ProcessStatus",
]
