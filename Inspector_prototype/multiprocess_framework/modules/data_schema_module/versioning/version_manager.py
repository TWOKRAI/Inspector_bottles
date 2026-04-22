"""
Система версионирования для моделей данных.

Упрощенная версия с dependency injection для StorageManager.
Версионирование - опциональное дополнение, а не обязательная зависимость.
"""

import time
from typing import Dict, Any, Optional, List

from ..core.interfaces import IVersionManager, IStorageManager
from ..models.base import BaseManagerModel
from ..registry.schema_registry import SchemaManager


class VersionInfo:
    """Информация о версии."""
    
    def __init__(
        self,
        version: int,
        data: Dict[str, Any],
        timestamp: float,
        comment: Optional[str] = None,
        author: Optional[str] = None,
        tags: Optional[List[str]] = None
    ):
        self.version = version
        self.data = data
        self.timestamp = timestamp
        self.comment = comment
        self.author = author
        self.tags = tags or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертировать в словарь."""
        return {
            "version": self.version,
            "data": self.data,
            "timestamp": self.timestamp,
            "comment": self.comment,
            "author": self.author,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VersionInfo':
        """Создать из словаря."""
        return cls(
            version=data["version"],
            data=data["data"],
            timestamp=data["timestamp"],
            comment=data.get("comment"),
            author=data.get("author"),
            tags=data.get("tags", [])
        )


class VersionManager(IVersionManager):
    """
    Менеджер версий для моделей данных.
    
    Управляет историей версий конфигураций менеджеров и произвольных документов
    (например рецептов). Один механизм версий для менеджеров и для scope="recipe".
    """
    
    VERSIONS_KEY = 'component_managers_versions'
    DOCUMENTS_KEY = 'documents_versions'  # scope -> name -> { current_version, versions }
    MAX_VERSIONS = 100
    
    def __init__(self, storage_manager: Optional[IStorageManager] = None):
        """
        Инициализация менеджера версий.
        
        Args:
            storage_manager: StorageManager для работы с ProcessData (опционально)
        """
        self.storage_manager = storage_manager
        self.schema_registry = SchemaManager.get_instance()
    
    def _get_process_data(self, process_name: Optional[str] = None) -> Optional[Any]:
        """Получить ProcessData процесса через StorageManager."""
        if not self.storage_manager:
            return None
        
        # Используем внутренний метод StorageManager для доступа к ProcessData
        return self.storage_manager._get_process_data(process_name)  # type: ignore
    
    def create_version(
        self,
        manager_model: BaseManagerModel,
        comment: Optional[str] = None,
        author: Optional[str] = None,
        tags: Optional[List[str]] = None,
        process_name: Optional[str] = None
    ) -> int:
        """
        Создать новую версию модели.
        
        Args:
            manager_model: Pydantic модель менеджера
            comment: Комментарий к версии
            author: Автор версии
            tags: Метки версии
            process_name: Имя процесса (опционально)
            
        Returns:
            Номер новой версии
        """
        process_data = self._get_process_data(process_name)
        if not process_data:
            return 0
        
        # Инициализируем структуру если её нет
        if self.VERSIONS_KEY not in process_data.custom:
            process_data.custom[self.VERSIONS_KEY] = {}
        
        versions_dict = process_data.custom[self.VERSIONS_KEY]
        manager_type = manager_model.component_class
        manager_name = manager_model.name
        
        # Инициализируем менеджера если его нет
        if manager_type not in versions_dict:
            versions_dict[manager_type] = {}
        
        if manager_name not in versions_dict[manager_type]:
            versions_dict[manager_type][manager_name] = {
                "current_version": 0,
                "versions": {}
            }
        
        manager_versions = versions_dict[manager_type][manager_name]
        
        # Получаем текущую версию
        current_version = manager_versions.get("current_version", 0)
        new_version = current_version + 1
        
        # Создаем информацию о версии
        version_info = VersionInfo(
            version=new_version,
            data=manager_model.model_dump(),
            timestamp=time.time(),
            comment=comment,
            author=author,
            tags=tags
        )
        
        # Добавляем версию
        if "versions" not in manager_versions:
            manager_versions["versions"] = {}
        
        manager_versions["versions"][str(new_version)] = version_info.to_dict()
        
        # Обновляем текущую версию
        manager_versions["current_version"] = new_version
        
        # Очищаем старые версии если превышен лимит
        self._cleanup_old_versions(
            manager_versions["versions"],
            manager_type,
            manager_name,
            process_name
        )
        
        process_data.update_timestamp()
        return new_version
    
    def get_current_version(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None
    ) -> int:
        """Получить текущую версию менеджера."""
        process_data = self._get_process_data(process_name)
        if not process_data:
            return 0
        
        versions_dict = process_data.custom.get(self.VERSIONS_KEY, {})
        manager_versions = versions_dict.get(manager_type, {}).get(manager_name, {})
        
        return manager_versions.get("current_version", 0)
    
    def get_version(
        self,
        manager_type: str,
        manager_name: str,
        version: int,
        process_name: Optional[str] = None
    ) -> Optional[BaseManagerModel]:
        """Получить модель по версии."""
        process_data = self._get_process_data(process_name)
        if not process_data:
            return None
        
        versions_dict = process_data.custom.get(self.VERSIONS_KEY, {})
        manager_versions = versions_dict.get(manager_type, {}).get(manager_name, {})
        versions = manager_versions.get("versions", {})
        
        version_data = versions.get(str(version))
        if not version_data:
            return None
        
        version_info = VersionInfo.from_dict(version_data)
        
        # Восстанавливаем модель из данных версии
        schema = self.schema_registry.get_schema(manager_type)
        if schema:
            return schema(**version_info.data)
        
        # Если схемы нет, используем BaseManagerModel
        return BaseManagerModel(**version_info.data)
    
    def rollback(
        self,
        manager_type: str,
        manager_name: str,
        target_version: int,
        process_name: Optional[str] = None,
        create_new_version: bool = True,
        comment: Optional[str] = None
    ) -> bool:
        """Откатиться к указанной версии."""
        # Получаем модель по версии
        model = self.get_version(
            manager_type,
            manager_name,
            target_version,
            process_name
        )
        
        if not model:
            return False
        
        # Обновляем текущую модель через StorageManager
        if not self.storage_manager:
            return False
        
        if create_new_version:
            # Создаем новую версию с данными отката
            self.create_version(
                model,
                comment=comment or f"Rollback to version {target_version}",
                process_name=process_name
            )
        else:
            # Просто обновляем текущую версию
            self.storage_manager.update_manager_model(model, process_name)
            
            # Обновляем текущую версию в истории
            process_data = self._get_process_data(process_name)
            if process_data:
                versions_dict = process_data.custom.get(self.VERSIONS_KEY, {})
                manager_versions = versions_dict.get(manager_type, {}).get(manager_name, {})
                manager_versions["current_version"] = target_version
        
        return True
    
    def get_version_history(
        self,
        manager_type: str,
        manager_name: str,
        process_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Получить историю версий."""
        process_data = self._get_process_data(process_name)
        if not process_data:
            return []
        
        versions_dict = process_data.custom.get(self.VERSIONS_KEY, {})
        manager_versions = versions_dict.get(manager_type, {}).get(manager_name, {})
        versions = manager_versions.get("versions", {})
        
        # Конвертируем в список и сортируем по версии
        history = []
        for version_str, version_data in versions.items():
            version_info = VersionInfo.from_dict(version_data)
            history.append(version_info.to_dict())
        
        # Сортируем по версии (от новых к старым)
        history.sort(key=lambda x: x["version"], reverse=True)
        
        return history
    
    def compare_versions(
        self,
        manager_type: str,
        manager_name: str,
        version1: int,
        version2: int,
        process_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Сравнить две версии."""
        model1 = self.get_version(manager_type, manager_name, version1, process_name)
        model2 = self.get_version(manager_type, manager_name, version2, process_name)
        
        if not model1 or not model2:
            return {"error": "One or both versions not found"}
        
        # Простое сравнение через model_dump()
        data1 = model1.model_dump()
        data2 = model2.model_dump()
        
        # Находим различия
        differences = {}
        all_keys = set(data1.keys()) | set(data2.keys())
        
        for key in all_keys:
            val1 = data1.get(key)
            val2 = data2.get(key)
            
            if val1 != val2:
                differences[key] = {
                    "old": val1,
                    "new": val2
                }
        
        return {
            "version1": version1,
            "version2": version2,
            "differences": differences
        }
    
    def _cleanup_old_versions(
        self,
        versions: Dict[str, Dict],
        manager_type: str,
        manager_name: str,
        process_name: Optional[str]
    ):
        """Удалить старые версии если превышен лимит."""
        if len(versions) <= self.MAX_VERSIONS:
            return
        
        # Сортируем версии по номеру
        sorted_versions = sorted(
            versions.items(),
            key=lambda x: int(x[0])
        )
        
        # Находим версии без меток для удаления
        versions_to_remove = []
        for version_str, version_data in sorted_versions:
            version_info = VersionInfo.from_dict(version_data)
            
            # Не удаляем версии с метками
            if version_info.tags:
                continue
            
            versions_to_remove.append(version_str)
            
            # Удаляем пока не достигнем лимита
            if len(versions) - len(versions_to_remove) <= self.MAX_VERSIONS:
                break
        
        # Удаляем версии
        for version_str in versions_to_remove:
            del versions[version_str]

    # -------------------------------------------------------------------------
    # Документы (рецепты и др.): save_document / get_document
    # -------------------------------------------------------------------------

    def save_document(
        self,
        scope: str,
        name: str,
        data: Dict[str, Any],
        comment: Optional[str] = None,
        process_name: Optional[str] = None,
    ) -> int:
        """
        Сохранить версию произвольного документа (например рецепта).
        Тот же формат версий (VersionInfo с data), тот же лимит MAX_VERSIONS.

        Args:
            scope: Область (например "recipe").
            name: Имя документа (например recipe_id).
            data: Словарь данных (снимок регистров и т.д.).
            comment: Комментарий к версии.
            process_name: Имя процесса (опционально).

        Returns:
            Номер новой версии.
        """
        process_data = self._get_process_data(process_name)
        if not process_data:
            return 0

        if self.DOCUMENTS_KEY not in process_data.custom:
            process_data.custom[self.DOCUMENTS_KEY] = {}

        docs = process_data.custom[self.DOCUMENTS_KEY]
        if scope not in docs:
            docs[scope] = {}
        if name not in docs[scope]:
            docs[scope][name] = {"current_version": 0, "versions": {}}

        doc_versions = docs[scope][name]
        current_version = doc_versions.get("current_version", 0)
        new_version = current_version + 1

        version_info = VersionInfo(
            version=new_version,
            data=data,
            timestamp=time.time(),
            comment=comment,
            author=None,
            tags=None,
        )
        if "versions" not in doc_versions:
            doc_versions["versions"] = {}
        doc_versions["versions"][str(new_version)] = version_info.to_dict()
        doc_versions["current_version"] = new_version

        # Та же логика ограничения числа версий, что и для менеджеров (с учётом тегов)
        self._cleanup_old_versions(
            doc_versions["versions"],
            scope,
            name,
            process_name,
        )

        process_data.update_timestamp()
        return new_version

    def get_document(
        self,
        scope: str,
        name: str,
        version: Optional[int] = None,
        process_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить документ по scope и name, опционально по версии.

        Args:
            scope: Область (например "recipe").
            name: Имя документа.
            version: Номер версии; если None — возвращается текущая версия.
            process_name: Имя процесса (опционально).

        Returns:
            Словарь data или None.
        """
        process_data = self._get_process_data(process_name)
        if not process_data:
            return None

        docs = process_data.custom.get(self.DOCUMENTS_KEY, {})
        doc_versions = docs.get(scope, {}).get(name, {})
        versions = doc_versions.get("versions", {})
        current = doc_versions.get("current_version", 0)

        ver = version if version is not None else current
        version_data = versions.get(str(ver))
        if not version_data:
            return None

        version_info = VersionInfo.from_dict(version_data)
        return version_info.data


