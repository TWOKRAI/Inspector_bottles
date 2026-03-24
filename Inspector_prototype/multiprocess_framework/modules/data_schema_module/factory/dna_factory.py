"""
Фабрика для работы с полной ДНК компонентов.

Предоставляет методы для создания компонентов с полной ДНК и воссоздания по ДНК.
"""

from typing import Dict, Any, Optional, Type, Union
import importlib
import inspect
from pathlib import Path

from ..models.dna import (
    ComponentDNA,
    ComponentLocation,
    ResourceReference,
    ResourceType,
    ComponentHierarchy
)
from ..models.base import BaseComponentModel, BaseManagerModel
from ..models.types import ComponentType
from .model_factory import ModelFactory
from ..registry.schema_registry import SchemaManager
from ..core.exceptions import InvalidParameterError, SchemaNotFoundError


class DNAFactory:
    """
    Фабрика для работы с полной ДНК компонентов.
    
    Позволяет создавать компоненты с полной информацией о расположении,
    ресурсах и иерархии, а также воссоздавать компоненты по их ДНК.
    """
    
    @staticmethod
    def create_dna_from_class(
        component_class: Type[BaseComponentModel],
        component_name: str,
        creation_params: Optional[Dict[str, Any]] = None,
        resources: Optional[Dict[str, Dict[str, Any]]] = None,
        parent_id: Optional[str] = None,
        parent_type: Optional[str] = None,
        **kwargs
    ) -> ComponentDNA:
        """
        Создать ДНК компонента из класса.
        
        Автоматически определяет расположение класса (модуль, файл и т.д.).
        
        Args:
            component_class: Класс компонента
            component_name: Имя компонента
            creation_params: Параметры создания компонента
            resources: Ресурсы компонента {name: {type, id, name, ...}}
            parent_id: ID родительского компонента
            parent_type: Тип родительского компонента
            **kwargs: Дополнительные параметры
            
        Returns:
            ComponentDNA с полной информацией
            
        Example:
            dna = DNAFactory.create_dna_from_class(
                LoggerManager,
                "main_logger",
                creation_params={"log_level": "DEBUG"},
                resources={
                    "input_queue": {
                        "type": ResourceType.QUEUE,
                        "id": "queue:logger:input",
                        "name": "logger_input_queue"
                    }
                }
            )
        """
        # Определяем расположение класса
        module = inspect.getmodule(component_class)
        if not module:
            raise InvalidParameterError(
                "component_class",
                component_class,
                "не удалось определить модуль класса"
            )
        
        module_path = module.__name__
        class_name = component_class.__name__
        
        # Пытаемся определить путь к файлу
        file_path = None
        try:
            if hasattr(module, '__file__') and module.__file__:
                file_path = str(Path(module.__file__).resolve())
        except Exception:
            pass
        
        # Определяем тип компонента
        component_type = ComponentType.MANAGER
        if issubclass(component_class, BaseManagerModel):
            component_type = ComponentType.MANAGER
        elif hasattr(component_class, 'component_type'):
            component_type = getattr(component_class, 'component_type', ComponentType.COMPONENT)
        
        # Создаем расположение
        location = ComponentLocation(
            module_path=module_path,
            class_name=class_name,
            file_path=file_path
        )
        
        # Создаем иерархию
        hierarchy = ComponentHierarchy(
            parent_id=parent_id,
            parent_type=parent_type,
            level=1 if parent_id else 0
        )
        
        # Создаем базовую модель через DataFactory
        base_data = {
            "component_class": class_name,
            "name": component_name,
            "component_type": component_type,
            **kwargs
        }
        
        # Создаем ComponentDNA
        dna = ComponentDNA(
            component_type=component_type,
            component_class=class_name,
            name=component_name,
            location=location,
            hierarchy=hierarchy,
            creation_params=creation_params or {},
            metadata=kwargs.get("metadata", {})
        )
        
        # Добавляем ресурсы
        if resources:
            for name, res_info in resources.items():
                dna.add_resource(
                    name=name,
                    resource_type=res_info.get("type", ResourceType.CUSTOM),
                    resource_id=res_info.get("id", f"{name}:{component_name}"),
                    resource_name=res_info.get("name", name),
                    metadata=res_info.get("metadata", {})
                )
        
        return dna
    
    @staticmethod
    def create_dna_from_instance(
        instance: BaseComponentModel,
        resources: Optional[Dict[str, Dict[str, Any]]] = None,
        **kwargs
    ) -> ComponentDNA:
        """
        Создать ДНК из существующего экземпляра компонента.
        
        Args:
            instance: Экземпляр компонента
            resources: Ресурсы компонента
            **kwargs: Дополнительные параметры
            
        Returns:
            ComponentDNA с информацией из экземпляра
        """
        # Определяем класс
        component_class = type(instance)
        
        # Получаем данные из экземпляра
        instance_data = instance.model_dump()
        
        # Определяем расположение
        module = inspect.getmodule(component_class)
        module_path = module.__name__ if module else "unknown"
        class_name = component_class.__name__
        
        file_path = None
        try:
            if module and hasattr(module, '__file__') and module.__file__:
                file_path = str(Path(module.__file__).resolve())
        except Exception:
            pass
        
        location = ComponentLocation(
            module_path=module_path,
            class_name=class_name,
            file_path=file_path
        )
        
        # Создаем ДНК
        dna = ComponentDNA(
            component_type=instance.component_type,
            component_class=instance.component_class,
            name=instance.name,
            status=instance.status,
            metadata=instance.metadata,
            version=instance.version,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            location=location,
            creation_params=kwargs.get("creation_params", {}),
            **kwargs
        )
        
        # Добавляем ресурсы
        if resources:
            for name, res_info in resources.items():
                dna.add_resource(
                    name=name,
                    resource_type=res_info.get("type", ResourceType.CUSTOM),
                    resource_id=res_info.get("id", f"{name}:{instance.name}"),
                    resource_name=res_info.get("name", name),
                    metadata=res_info.get("metadata", {})
                )
        
        return dna
    
    @staticmethod
    def recreate_from_dna(dna: ComponentDNA) -> BaseComponentModel:
        """
        Воссоздать компонент по его ДНК.
        
        Args:
            dna: ComponentDNA с полной информацией
            
        Returns:
            Экземпляр компонента
            
        Raises:
            InvalidParameterError: Если недостаточно информации для воссоздания
        """
        if not dna.can_recreate():
            raise InvalidParameterError(
                "dna",
                dna,
                "недостаточно информации для воссоздания компонента"
            )
        
        # Импортируем класс
        try:
            module = importlib.import_module(dna.location.module_path)
            component_class = getattr(module, dna.location.class_name)
        except (ImportError, AttributeError) as e:
            raise InvalidParameterError(
                "dna.location",
                dna.location.to_dict(),
                f"не удалось импортировать класс: {e}"
            )
        
        # Регистрируем схему если нужно
        registry = SchemaManager.get_instance()
        schema_name = dna.component_class
        if not registry.has_schema(schema_name):
            registry.register(schema_name, component_class)
        
        # Создаем экземпляр с параметрами из ДНК
        creation_data = {
            "component_class": dna.component_class,
            "name": dna.name,
            "component_type": dna.component_type,
            **dna.creation_params,
            **dna.metadata
        }
        
        # Используем DataFactory для создания
        if issubclass(component_class, BaseManagerModel):
            return ModelFactory.create_manager(
                manager_class=schema_name,
                manager_name=dna.name,
                data=creation_data,
                auto_register=False
            )
        else:
            return ModelFactory.from_dict(creation_data, schema_name=schema_name)
    
    @staticmethod
    def clone_component(
        source_dna: ComponentDNA,
        new_name: str,
        **overrides
    ) -> ComponentDNA:
        """
        Клонировать компонент с изменениями.
        
        Args:
            source_dna: ДНК исходного компонента
            new_name: Новое имя компонента
            **overrides: Переопределения полей
            
        Returns:
            Новая ComponentDNA
        """
        return source_dna.clone(new_name=new_name, **overrides)
    
    @staticmethod
    def get_component_tree(dna: ComponentDNA, all_dnas: Dict[str, ComponentDNA]) -> Dict[str, Any]:
        """
        Получить дерево компонентов начиная с данного.
        
        Args:
            dna: Корневой компонент
            all_dnas: Словарь всех ДНК {component_id: ComponentDNA}
            
        Returns:
            Дерево компонентов
        """
        tree = {
            "component": {
                "id": dna.name,
                "type": dna.component_class,
                "name": dna.name,
                "status": dna.status
            },
            "location": dna.location.to_dict(),
            "children": []
        }
        
        # Добавляем дочерние компоненты
        for child_id in dna.hierarchy.children_ids:
            if child_id in all_dnas:
                child_dna = all_dnas[child_id]
                child_tree = DNAFactory.get_component_tree(child_dna, all_dnas)
                tree["children"].append(child_tree)
        
        return tree
    
    @staticmethod
    def get_storage_info(dna: ComponentDNA) -> Dict[str, Any]:
        """
        Получить информацию о хранилище компонента.
        
        Args:
            dna: ComponentDNA компонента
            
        Returns:
            Информация о том, где и как хранится компонент
        """
        return {
            "component_id": f"{dna.component_class}:{dna.name}",
            "storage_locations": {
                "schema_registry": f"SchemaManager['{dna.component_class}']",
                "process_data": f"ProcessData.custom['component_managers']['{dna.component_class}']['{dna.name}']",
                "file_path": dna.location.file_path,
                "config_path": dna.location.config_path,
                "storage_path": dna.location.storage_path,
            },
            "class_location": {
                "module": dna.location.module_path,
                "class": dna.location.class_name,
                "full_path": dna.location.get_full_class_path(),
                "file": dna.location.file_path
            },
            "resources": {
                name: {
                    "type": ref.resource_type.value,
                    "id": ref.resource_id,
                    "name": ref.resource_name,
                    "storage": f"SharedResources.{ref.resource_type.value}s['{ref.resource_id}']"
                }
                for name, ref in dna.resources.items()
            }
        }

