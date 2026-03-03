"""
Единая фабрика для создания моделей данных.

Консолидирует все способы создания моделей в один простой API.
"""

from typing import Dict, Any, Optional, TypeVar, Type, Union
import time

from ..registry.schema_registry import SchemaRegistry
from ..models.base import BaseManagerModel, BaseComponentModel
from ..models.types import ComponentType
from ..core.exceptions import (
    SchemaNotFoundError,
    SchemaValidationError,
    InvalidParameterError
)
from ..core.metrics import record_timing, increment_metric

T = TypeVar('T', bound=BaseManagerModel)


class ModelFactory:
    """
    Единая фабрика для создания моделей данных.
    
    Консолидирует все способы создания моделей в три основных метода:
    - create() - основной метод создания любой модели
    - create_manager() - специализированный метод для менеджеров
    - from_dict() - создание из словаря
    """
    
    @staticmethod
    def create(
        schema_name: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Union[BaseManagerModel, BaseComponentModel]:
        """
        Основной метод создания модели.
        
        Создает экземпляр Pydantic модели с дефолтными значениями из схемы.
        
        Args:
            schema_name: Имя схемы (должно быть зарегистрировано)
            data: Данные для инициализации (опционально)
            **kwargs: Дополнительные поля для инициализации
            
        Returns:
            Pydantic модель
            
        Example:
            # Простая модель
            config = ModelFactory.create("AppConfig", {"host": "0.0.0.0"})
            
            # Модель менеджера
            manager = ModelFactory.create(
                "LoggerManager",
                name="logger_main",
                config={"log_level": "DEBUG"}
            )
        """
        if not schema_name or not isinstance(schema_name, str):
            raise InvalidParameterError(
                "schema_name",
                schema_name,
                "должно быть непустой строкой"
            )
        
        registry = SchemaRegistry.get_instance()
        
        init_data = {}
        if data:
            if not isinstance(data, dict):
                raise InvalidParameterError(
                    "data",
                    data,
                    "должен быть словарем"
                )
            init_data.update(data)
        if kwargs:
            init_data.update(kwargs)
        
        start_time = time.time()
        try:
            instance = registry.create_instance(schema_name, init_data)
            duration = time.time() - start_time
            
            record_timing("data_schema.factory.create", duration, {
                "schema_name": schema_name
            })
            increment_metric("data_schema.factory.models_created", {
                "schema_name": schema_name
            })
            
            return instance
        except Exception as e:
            duration = time.time() - start_time
            record_timing("data_schema.factory.create_failed", duration, {
                "schema_name": schema_name
            })
            increment_metric("data_schema.factory.creation_errors", {
                "schema_name": schema_name,
                "error_type": type(e).__name__
            })
            raise
    
    @staticmethod
    def create_manager(
        manager_class: str,
        manager_name: str,
        data: Optional[Dict[str, Any]] = None,
        auto_register: bool = True,
        process_name: Optional[str] = None,
        shared_resources: Optional[Any] = None
    ) -> BaseManagerModel:
        """
        Создать модель менеджера.
        
        Специализированный метод для создания менеджеров с автоматической
        регистрацией в ProcessData при необходимости.
        
        Args:
            manager_class: Имя класса менеджера (должно быть зарегистрировано)
            manager_name: Имя менеджера
            data: Данные для инициализации (опционально)
            auto_register: Автоматически зарегистрировать в ProcessData
            process_name: Имя процесса (для автоматической регистрации)
            shared_resources: SharedResourcesManager (опционально)
            
        Returns:
            Pydantic модель менеджера
            
        Example:
            manager = ModelFactory.create_manager(
                "LoggerManager",
                "logger_main",
                data={"config": {"log_level": "DEBUG"}},
                auto_register=True,
                process_name="VisionProcess"
            )
        """
        if not manager_class or not isinstance(manager_class, str):
            raise InvalidParameterError(
                "manager_class",
                manager_class,
                "должно быть непустой строкой"
            )
        
        if not manager_name or not isinstance(manager_name, str):
            raise InvalidParameterError(
                "manager_name",
                manager_name,
                "должно быть непустой строкой"
            )
        
        if data is not None and not isinstance(data, dict):
            raise InvalidParameterError(
                "data",
                data,
                "должен быть словарем или None"
            )
        
        # Подготавливаем данные
        init_data = {}
        if data:
            init_data.update(data)
        
        # Устанавливаем обязательные поля
        init_data['component_class'] = manager_class
        init_data['name'] = manager_name
        init_data['component_type'] = ComponentType.MANAGER
        
        # Создаем модель
        manager_model = ModelFactory.create(manager_class, init_data)
        
        if not isinstance(manager_model, BaseManagerModel):
            raise SchemaValidationError(
                manager_class,
                [{"msg": "Модель должна быть экземпляром BaseManagerModel"}],
                init_data
            )
        
        # Автоматическая регистрация в ProcessData
        if auto_register:
            from ..storage import StorageManager
            storage = StorageManager.get_instance(shared_resources)
            storage.register_manager(manager_model, process_name)
            increment_metric("data_schema.factory.managers_registered", {
                "manager_class": manager_class
            })
        
        return manager_model
    
    @staticmethod
    def from_dict(
        data: Dict[str, Any],
        schema_name: Optional[str] = None
    ) -> Union[BaseManagerModel, BaseComponentModel]:
        """
        Создать модель из словаря.
        
        Определяет схему из данных или использует указанную.
        
        Args:
            data: Словарь с данными
            schema_name: Имя схемы (определяется из data если не указано)
            
        Returns:
            Pydantic модель
            
        Example:
            model = ModelFactory.from_dict({
                "component_class": "LoggerManager",
                "name": "logger_main",
                "config": {"log_level": "DEBUG"}
            })
        """
        if not isinstance(data, dict):
            raise InvalidParameterError(
                "data",
                data,
                "должен быть словарем"
            )
        
        # Определяем схему
        if schema_name is None:
            schema_name = data.get('component_class', 'BaseManagerModel')
        
        if not schema_name or not isinstance(schema_name, str):
            raise InvalidParameterError(
                "schema_name",
                schema_name,
                "должно быть непустой строкой"
            )
        
        registry = SchemaRegistry.get_instance()
        schema_class = registry.get_schema(schema_name)
        
        if schema_class is None:
            available = registry.list_schemas()
            raise SchemaNotFoundError(schema_name, available)
        
        # Если схема наследуется от BaseManagerModel, добавляем обязательные поля
        init_data = data.copy()
        if issubclass(schema_class, BaseManagerModel):
            if 'component_type' not in init_data:
                init_data['component_type'] = ComponentType.MANAGER
            if 'component_class' not in init_data:
                init_data['component_class'] = schema_name
        
        start_time = time.time()
        try:
            instance = registry.create_instance(schema_name, init_data)
            duration = time.time() - start_time
            
            record_timing("data_schema.factory.from_dict", duration, {
                "schema_name": schema_name
            })
            increment_metric("data_schema.factory.instances_from_dict", {
                "schema_name": schema_name
            })
            
            return instance
        except Exception as e:
            duration = time.time() - start_time
            record_timing("data_schema.factory.from_dict_failed", duration, {
                "schema_name": schema_name
            })
            increment_metric("data_schema.factory.dict_creation_errors", {
                "schema_name": schema_name,
                "error_type": type(e).__name__
            })
            raise

