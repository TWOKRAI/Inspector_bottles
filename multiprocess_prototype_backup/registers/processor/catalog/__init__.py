"""Каталог операций обработки."""

from .schemas import ProcessingOperationDef
from .loader import load_catalog, save_catalog

__all__ = ["ProcessingOperationDef", "load_catalog", "save_catalog"]
