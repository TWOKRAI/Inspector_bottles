# multiprocess_prototype/database/__init__.py
"""
Реэкспорт из backend.database для обратной совместимости.
Новые импорты: from multiprocess_prototype.backend.database import ...
"""

from multiprocess_prototype.backend.database.schema_1 import DetectionSchema

__all__ = ["DetectionSchema"]
