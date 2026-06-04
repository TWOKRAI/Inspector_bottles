"""Database plugin — хранение результатов детекции в SQLite (через Services/sql)."""

from .config import DatabasePluginConfig
from .plugin import DatabasePlugin
from .registers import DatabaseRegisters
from .schemas import DetectionSchema

__all__ = [
    "DatabasePlugin",
    "DatabasePluginConfig",
    "DatabaseRegisters",
    "DetectionSchema",
]
