"""
DataSchemaAdapter — тонкий мост к data_schema_module.

Делегирует в data_schema_module.storage.StorageManager.
Не содержит схемной логики, валидации или типов — всё в data_schema_module.
Ленивый импорт: data_schema_module опционален (graceful degradation).
"""

from typing import Optional, Any


class DataSchemaAdapter:
    """
    Мост к StorageManager из data_schema_module.

    Предоставляет доступ к хранению ComponentDNA и manager-моделей в ProcessData.custom.
    Вся логика схем, валидации, RegisterBase — в data_schema_module.
    Graceful degradation: возвращает None если data_schema_module недоступен.
    """

    def __init__(self, shared_resources_manager: Any) -> None:
        self._srm = shared_resources_manager
        self._data_manager: Optional[Any] = None

    def get_data_manager(self) -> Optional[Any]:
        """Получить StorageManager (ленивая инициализация)."""
        if self._data_manager is None:
            try:
                from ....data_schema_module.storage.storage_manager import StorageManager
                self._data_manager = StorageManager(shared_resources=self._srm)
            except ImportError:
                return None
        return self._data_manager

    @property
    def data_manager(self) -> Optional[Any]:
        return self.get_data_manager()

    def is_available(self) -> bool:
        return self.get_data_manager() is not None
