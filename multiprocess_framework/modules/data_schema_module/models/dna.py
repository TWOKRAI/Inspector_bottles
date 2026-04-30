"""
Модели для хранения полной ДНК компонентов.

ДНК компонента включает всю информацию, необходимую для его полного воссоздания:
- Путь к классу и модулю
- Ссылки на ресурсы (queues, events, shared memory)
- Иерархия компонентов
- Метаданные о расположении
- Параметры создания
"""

from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from enum import Enum

from .base import BaseComponentModel
from ..core.reference import DataReference
from .types import ComponentType


class ResourceType(str, Enum):
    """Типы ресурсов в системе."""
    QUEUE = "queue"
    EVENT = "event"
    SHARED_MEMORY = "shared_memory"
    LOCK = "lock"
    SEMAPHORE = "semaphore"
    PIPE = "pipe"
    MANAGER = "manager"
    PROCESS = "process"
    COMPONENT = "component"
    CUSTOM = "custom"


class ResourceReference(BaseModel):
    """
    Ссылка на ресурс системы (queue, event, shared memory и т.д.).
    
    Хранит информацию о ресурсе без самого объекта (который не сериализуется).
    """
    
    resource_type: ResourceType
    resource_id: str  # Уникальный идентификатор ресурса
    resource_name: str  # Имя ресурса
    ref_id: Optional[str] = None  # ID для DataReference
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def to_reference(self) -> DataReference:
        """Преобразовать в DataReference."""
        ref_id = self.ref_id or f"{self.resource_type.value}:{self.resource_id}"
        return DataReference(ref_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        return {
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "ref_id": self.ref_id,
            "metadata": self.metadata
        }


class ComponentLocation(BaseModel):
    """
    Информация о расположении компонента.
    
    Хранит пути к модулю, классу, файлам конфигурации и т.д.
    """
    
    module_path: str  # Путь к модулю (например, "logger_module.core.logger_manager")
    class_name: str  # Имя класса (например, "LoggerManager")
    file_path: Optional[str] = None  # Путь к файлу с кодом
    config_path: Optional[str] = None  # Путь к файлу конфигурации
    storage_path: Optional[str] = None  # Путь к хранилищу данных
    package_path: Optional[str] = None  # Путь к пакету
    
    def get_full_class_path(self) -> str:
        """Получить полный путь к классу."""
        return f"{self.module_path}.{self.class_name}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        return {
            "module_path": self.module_path,
            "class_name": self.class_name,
            "file_path": self.file_path,
            "config_path": self.config_path,
            "storage_path": self.storage_path,
            "package_path": self.package_path,
            "full_class_path": self.get_full_class_path()
        }


class ComponentHierarchy(BaseModel):
    """
    Иерархия компонентов.
    
    Хранит информацию о родительских и дочерних компонентах.
    """
    
    parent_id: Optional[str] = None  # ID родительского компонента
    parent_type: Optional[str] = None  # Тип родительского компонента
    children_ids: List[str] = Field(default_factory=list)  # ID дочерних компонентов
    children_types: List[str] = Field(default_factory=list)  # Типы дочерних компонентов
    level: int = 0  # Уровень в иерархии (0 - корневой)
    path: List[str] = Field(default_factory=list)  # Путь от корня до компонента
    
    def add_child(self, child_id: str, child_type: str):
        """Добавить дочерний компонент."""
        if child_id not in self.children_ids:
            self.children_ids.append(child_id)
            self.children_types.append(child_type)
    
    def remove_child(self, child_id: str):
        """Удалить дочерний компонент."""
        if child_id in self.children_ids:
            idx = self.children_ids.index(child_id)
            self.children_ids.pop(idx)
            self.children_types.pop(idx)
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        return {
            "parent_id": self.parent_id,
            "parent_type": self.parent_type,
            "children_ids": self.children_ids,
            "children_types": self.children_types,
            "level": self.level,
            "path": self.path
        }


class ComponentDNA(BaseComponentModel):
    """
    Полная ДНК компонента - вся информация для его воссоздания.
    
    Расширяет BaseComponentModel дополнительными полями:
    - Расположение (пути к модулям, классам, файлам)
    - Ресурсы (ссылки на queues, events, shared memory)
    - Иерархия (родители, дети)
    - Параметры создания
    - Метаданные о структуре
    """
    
    # Расположение компонента
    location: ComponentLocation
    
    # Ресурсы компонента
    resources: Dict[str, ResourceReference] = Field(default_factory=dict)
    # Ключи: "input_queue", "output_queue", "control_event", "data_memory" и т.д.
    
    # Иерархия компонентов
    hierarchy: ComponentHierarchy = Field(default_factory=ComponentHierarchy)
    
    # Параметры создания компонента
    creation_params: Dict[str, Any] = Field(default_factory=dict)
    # Параметры, которые были переданы при создании компонента
    
    # Дополнительные метаданные
    dna_metadata: Dict[str, Any] = Field(default_factory=dict)
    # Дополнительная информация: зависимости, требования, ограничения и т.д.
    
    def add_resource(
        self,
        name: str,
        resource_type: ResourceType,
        resource_id: str,
        resource_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Добавить ссылку на ресурс.
        
        Args:
            name: Имя ресурса в компоненте (например, "input_queue")
            resource_type: Тип ресурса
            resource_id: Уникальный ID ресурса
            resource_name: Имя ресурса
            metadata: Дополнительные метаданные
        """
        self.resources[name] = ResourceReference(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            metadata=metadata or {}
        )
        self.update_timestamp()
    
    def remove_resource(self, name: str):
        """Удалить ссылку на ресурс."""
        if name in self.resources:
            del self.resources[name]
            self.update_timestamp()
    
    def get_resource(self, name: str) -> Optional[ResourceReference]:
        """Получить ссылку на ресурс."""
        return self.resources.get(name)
    
    def set_parent(self, parent_id: str, parent_type: str):
        """Установить родительский компонент."""
        self.hierarchy.parent_id = parent_id
        self.hierarchy.parent_type = parent_type
        self.hierarchy.level = self.hierarchy.level + 1 if self.hierarchy.parent_id else 0
        self.update_timestamp()
    
    def add_child(self, child_id: str, child_type: str):
        """Добавить дочерний компонент."""
        self.hierarchy.add_child(child_id, child_type)
        self.update_timestamp()
    
    def get_full_info(self) -> Dict[str, Any]:
        """
        Получить полную информацию о компоненте (ДНК).
        
        Returns:
            Словарь со всей информацией о компоненте
        """
        return {
            "component": {
                "type": self.component_type.value,
                "class": self.component_class,
                "name": self.name,
                "status": self.status,
            },
            "location": self.location.to_dict(),
            "resources": {
                name: ref.to_dict() 
                for name, ref in self.resources.items()
            },
            "hierarchy": self.hierarchy.to_dict(),
            "creation_params": self.creation_params,
            "metadata": self.metadata,
            "dna_metadata": self.dna_metadata,
            "timestamps": {
                "version": self.version,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        }
    
    def clone(self, new_name: Optional[str] = None, **overrides) -> "ComponentDNA":
        """
        Клонировать компонент с изменениями.
        
        Args:
            new_name: Новое имя компонента
            **overrides: Переопределения полей
            
        Returns:
            Новый экземпляр ComponentDNA
        """
        data = self.model_dump()
        
        # Обновляем имя если указано
        if new_name:
            data["name"] = new_name
        
        # Применяем переопределения
        data.update(overrides)
        
        # Обновляем временные метки
        import time
        data["version"] = time.time()
        data["created_at"] = time.time()
        data["updated_at"] = time.time()
        
        # Сбрасываем иерархию для нового компонента
        data["hierarchy"] = ComponentHierarchy().model_dump()
        
        return ComponentDNA(**data)
    
    def can_recreate(self) -> bool:
        """
        Проверить, можно ли воссоздать компонент по ДНК.
        
        Returns:
            True если достаточно информации для воссоздания
        """
        # Проверяем наличие обязательной информации
        if not self.location.module_path or not self.location.class_name:
            return False
        
        # Проверяем наличие основных полей
        if not self.component_class or not self.name:
            return False
        
        return True
    
    def get_recreation_info(self) -> Dict[str, Any]:
        """
        Получить информацию для воссоздания компонента.
        
        Returns:
            Словарь с информацией для создания экземпляра
        """
        return {
            "class_path": self.location.get_full_class_path(),
            "class_name": self.location.class_name,
            "module_path": self.location.module_path,
            "creation_params": self.creation_params,
            "resources": {
                name: ref.to_dict()
                for name, ref in self.resources.items()
            },
            "config": self.metadata.get("config", {}),
        }

