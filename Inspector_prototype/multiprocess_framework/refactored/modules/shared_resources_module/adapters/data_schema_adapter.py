"""
DataSchemaAdapter — тонкий адаптер для data_schema_module.

Предоставляет доступ к StorageManager через SharedResourcesManager.
Ленивый импорт: data_schema_module опционален.
"""

from typing import Optional, Any


class DataSchemaAdapter:
    """
    Адаптер для работы с data_schema_module.

    Graceful degradation: возвращает None если модуль недоступен.
    """

    def __init__(self, shared_resources_manager: Any) -> None:
        self._srm = shared_resources_manager
        self._data_manager: Optional[Any] = None

    def get_data_manager(self) -> Optional[Any]:
        """Получить StorageManager (ленивая инициализация)."""
        if self._data_manager is None:
            try:
                from ....data_schema_module.extensions.storage_manager import StorageManager
                self._data_manager = StorageManager(shared_resources=self._srm)
            except ImportError:
                return None
        return self._data_manager

    @property
    def data_manager(self) -> Optional[Any]:
        return self.get_data_manager()

    def is_available(self) -> bool:
        return self.get_data_manager() is not None
