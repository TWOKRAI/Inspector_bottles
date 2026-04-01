# multiprocess_prototype_v2\backend\__init__.py
"""
Backend Inspector Prototype v2.

Пакет `processes` не импортируется здесь намеренно — избегаем циклов.

Явный импорт конфигов: ``from multiprocess_prototype_v2.backend.configs import ...``

Атрибут ``configs`` подгружается лениво (importlib), чтобы ``import ... backend`` не тянул
все схемы процессов.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["configs"]


def __getattr__(name: str) -> Any:
    if name == "configs":
        return importlib.import_module(".configs", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
