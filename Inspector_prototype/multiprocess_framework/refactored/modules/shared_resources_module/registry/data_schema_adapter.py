"""
Адаптер для data_schema модуля.

Предоставляет удобный доступ к data_schema через SharedResourcesManager.
data_schema вынесен как отдельный модуль, но доступен через этот адаптер.
"""

from typing import Optional, Any


class DataSchemaAdapter:
    """
    Адаптер для работы с data_schema модулем.
    
    Предоставляет удобный доступ к data_schema через SharedResourcesManager.
    data_schema вынесен как отдельный модуль для переиспользования.
    
    Пример использования:
        shared_resources = SharedResourcesManager()
        data_manager = shared_resources.get_data_manager()
        # или
        data_manager = shared_resources.data_manager
    """
    
    def __init__(self, shared_resources_manager):
        """
        Инициализация адаптера.
        
        Args:
            shared_resources_manager: SharedResourcesManager для доступа к data_schema
        """
        self.shared_resources = shared_resources_manager
        self._data_manager = None
    
    def get_data_manager(self):
        """
        Получить DataManager для работы с данными компонентов (из data_schema).
        
        Returns:
            DataManager экземпляр или None если модуль не доступен
        
        Note:
            data_schema должен быть установлен как отдельный модуль.
            Импорт выполняется динамически для избежания циклических зависимостей.
        """
        if self._data_manager is None:
            try:
                # Импорт из нового отдельного модуля data_schema_module
                from ...data_schema_module import StorageManager
                # Создаем экземпляр StorageManager с ссылкой на shared_resources
                self._data_manager = StorageManager(shared_resources=self.shared_resources)
            except ImportError:
                # Fallback: пытаемся импортировать из старого места (для обратной совместимости)
                try:
                    from ....modules.Shared_resources_module.data_schema import StorageManager
                    self._data_manager = StorageManager(shared_resources=self.shared_resources)
                except ImportError:
                    # Модуль не доступен
                    return None
        
        return self._data_manager
    
    @property
    def data_manager(self):
        """
        Получить DataManager (из data_schema модуля).
        
        Returns:
            DataManager или None если модуль не доступен
        """
        return self.get_data_manager()
    
    def is_available(self) -> bool:
        """
        Проверить доступность data_schema модуля.
        
        Returns:
            bool: True если модуль доступен
        """
        return self.get_data_manager() is not None

