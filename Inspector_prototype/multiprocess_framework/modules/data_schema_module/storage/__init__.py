"""
Хранение данных: StorageManager (ProcessData), FileStorage (файловая система).

StorageManager — хранение данных менеджеров/компонентов в ProcessData
                 (для многопроцессорного взаимодействия).

FileStorage    — персистентное хранение RegistersContainer в JSON-файлах.
                 Реализует IRegisterStorage. Для других бэкендов (SQLite, Redis)
                 реализуйте тот же интерфейс: load / save / exists / delete.
"""
from .storage_manager import StorageManager
from ..serialization.file_storage import FileStorage

# Опциональный импорт ProcessDataContainer
try:
    from .process_data_container import ProcessDataContainer
    _has_container = True
except ImportError:
    _has_container = False

__all__ = [
    'StorageManager',
    'FileStorage',
]

if _has_container:
    __all__.append('ProcessDataContainer')


