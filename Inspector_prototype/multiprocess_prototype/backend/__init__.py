# multiprocess_prototype/backend/__init__.py
"""
Backend Inspector Prototype.

Пакет `processes` не импортируется здесь намеренно — избегаем циклов при `import backend`.
Используйте: `from multiprocess_prototype.backend.processes import …`
"""

from . import configs

__all__ = ["configs"]
