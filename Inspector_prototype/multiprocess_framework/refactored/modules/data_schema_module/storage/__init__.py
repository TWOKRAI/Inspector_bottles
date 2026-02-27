"""
Менеджер хранения данных компонентов.

Объединяет функциональность DataManager и ProcessDataContainer.
"""

from .storage_manager import StorageManager

# Опциональный импорт ProcessDataContainer
try:
    from .process_data_container import ProcessDataContainer
    _has_container = True
except ImportError:
    _has_container = False

__all__ = [
    'StorageManager',
]

if _has_container:
    __all__.append('ProcessDataContainer')


