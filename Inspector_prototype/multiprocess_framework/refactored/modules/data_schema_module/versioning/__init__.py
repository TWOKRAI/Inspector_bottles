"""
Система версионирования для моделей данных.

Опциональный модуль для управления версиями конфигураций.
"""

from .version_manager import VersionManager, VersionInfo

__all__ = [
    'VersionManager',
    'VersionInfo',
]


