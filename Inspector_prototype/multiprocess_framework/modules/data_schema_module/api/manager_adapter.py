"""
Адаптер для работы с данными менеджера.

Упрощенная версия с опциональным версионированием через dependency injection.
"""

from typing import Any, Optional, Dict, List

from ..storage.storage_manager import StorageManager
from ..models.base import BaseManagerModel
from ..core.helpers import get_nested_value, set_nested_value


class ManagerDataAdapter:
    """
    Адаптер для работы с данными менеджера.
    
    Предоставляет удобный доступ к данным через Pydantic модели.
    Автоматически синхронизирует модель с ProcessData.
    Версионирование опционально через dependency injection.
    """
    
    def __init__(
        self,
        manager_instance: Any,
        process: Any,
        shared_resources: Optional[Any] = None,
        version_manager: Optional[Any] = None
    ):
        """
        Инициализация адаптера.
        
        Args:
            manager_instance: Экземпляр менеджера
            process: Объект процесса (должен иметь атрибут .name)
            shared_resources: SharedResourcesManager (опционально)
            version_manager: VersionManager (опционально, для версионирования)
        """
        self.manager = manager_instance
        self.process = process
        self.process_name = getattr(process, 'name', None) if process else None
        self.storage = StorageManager.get_instance(shared_resources)
        
        # Определяем тип и имя менеджера
        self.manager_type = type(manager_instance).__name__
        self.manager_name = getattr(manager_instance, 'name', self.manager_type.lower())
        
        # Кэш модели (создается при первом обращении)
        self._model_cache: Optional[BaseManagerModel] = None
        
        # Менеджер версий (опционально)
        self.version_manager = version_manager
        self._auto_versioning = version_manager is not None
    
    @property
    def model(self) -> Optional[BaseManagerModel]:
        """
        Получить модель менеджера.
        
        Создается из dict при первом обращении, затем кэшируется.
        
        Returns:
            Pydantic модель менеджера или None
        """
        if self._model_cache is None:
            self._model_cache = self.storage.get_manager_model(
                self.manager_name,
                self.manager_type,
                self.process_name
            )
        return self._model_cache
    
    @property
    def config(self) -> Dict[str, Any]:
        """Доступ к конфигурации менеджера."""
        model = self.model
        return model.config if model else {}
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """
        Получить значение конфигурации по точечной нотации.
        
        Args:
            key: Ключ конфигурации (поддерживает точечную нотацию)
            default: Значение по умолчанию
            
        Returns:
            Значение конфигурации или default
        """
        return get_nested_value(self.config, key, default)
    
    def set_config(self, key: str, value: Any):
        """Установить значение конфигурации."""
        model = self.model
        if not model:
            return
        
        set_nested_value(model.config, key, value)
        model.update_timestamp()
        self.save()
    
    def update_config(self, config: Dict[str, Any]):
        """Обновить конфигурацию менеджера."""
        model = self.model
        if not model:
            return
        
        model.config.update(config)
        model.update_timestamp()
        self.save()
    
    def save(self, create_version: Optional[bool] = None):
        """
        Сохранить модель в ProcessData.
        
        Синхронизирует модель с dict в ProcessData.custom.
        Автоматически создает версию если включено автоматическое версионирование.
        
        Args:
            create_version: Создать версию (None = использовать auto_versioning)
        """
        if self._model_cache:
            # Сохраняем модель
            self.storage.update_manager_model(
                self._model_cache,
                self.process_name
            )
            
            # Создаем версию если нужно
            if self.version_manager:
                if create_version is None:
                    create_version = self._auto_versioning
                
                if create_version:
                    self.version_manager.create_version(
                        self._model_cache,
                        process_name=self.process_name
                    )
    
    def reload(self):
        """Перезагрузить модель из ProcessData."""
        self._model_cache = None
        return self.model
    
    def get_status(self) -> Optional[str]:
        """Получить статус менеджера."""
        model = self.model
        return model.status if model else None
    
    def set_status(self, status: str):
        """Установить статус менеджера."""
        model = self.model
        if model:
            model.update_status(status)
            self.save()
    
    def update_stats(self, **kwargs):
        """Обновить статистику менеджера."""
        model = self.model
        if model:
            model.update_stats(**kwargs)
            self.save()
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику менеджера."""
        model = self.model
        return model.stats if model else {}
    
    # ========================================================================
    # Методы версионирования (только если version_manager установлен)
    # ========================================================================
    
    def create_snapshot(
        self,
        comment: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> int:
        """
        Создать снимок текущего состояния.
        
        Работает только если version_manager установлен.
        
        Args:
            comment: Комментарий к снимку
            tags: Метки снимка
            
        Returns:
            Номер версии снимка или 0 если версионирование недоступно
        """
        if not self.version_manager:
            return 0
        
        if not self._model_cache:
            self._model_cache = self.model
        
        if not self._model_cache:
            return 0
        
        return self.version_manager.create_version(
            self._model_cache,
            comment=comment or "Snapshot",
            tags=tags or [],
            process_name=self.process_name
        )
    
    def rollback_to_version(
        self,
        version: int,
        create_new_version: bool = True,
        comment: Optional[str] = None
    ) -> bool:
        """
        Откатиться к указанной версии.
        
        Работает только если version_manager установлен.
        
        Args:
            version: Номер версии для отката
            create_new_version: Создать новую версию с откатом
            comment: Комментарий к откату
            
        Returns:
            True если откат успешен
        """
        if not self.version_manager:
            return False
        
        success = self.version_manager.rollback(
            self.manager_type,
            self.manager_name,
            version,
            self.process_name,
            create_new_version=create_new_version,
            comment=comment
        )
        
        if success:
            # Перезагружаем модель после отката
            self.reload()
        
        return success
    
    def get_version_history(self) -> List[Dict[str, Any]]:
        """
        Получить историю версий.
        
        Работает только если version_manager установлен.
        """
        if not self.version_manager:
            return []
        
        return self.version_manager.get_version_history(
            self.manager_type,
            self.manager_name,
            self.process_name
        )
    
    def get_version(self, version: int) -> Optional[BaseManagerModel]:
        """Получить модель по версии."""
        if not self.version_manager:
            return None
        
        return self.version_manager.get_version(
            self.manager_type,
            self.manager_name,
            version,
            self.process_name
        )
    
    def compare_versions(
        self,
        version1: int,
        version2: int
    ) -> Dict[str, Any]:
        """Сравнить две версии."""
        if not self.version_manager:
            return {"error": "Versioning not available"}
        
        return self.version_manager.compare_versions(
            self.manager_type,
            self.manager_name,
            version1,
            version2,
            self.process_name
        )
    
    def get_current_version(self) -> int:
        """Получить текущую версию."""
        if not self.version_manager:
            return 0
        
        return self.version_manager.get_current_version(
            self.manager_type,
            self.manager_name,
            self.process_name
        )
    
    def enable_auto_versioning(self, enable: bool = True):
        """Включить/выключить автоматическое версионирование."""
        if self.version_manager:
            self._auto_versioning = enable
    
    def disable_auto_versioning(self):
        """Выключить автоматическое версионирование."""
        self._auto_versioning = False


