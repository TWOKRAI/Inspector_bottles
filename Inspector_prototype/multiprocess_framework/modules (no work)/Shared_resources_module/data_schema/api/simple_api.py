"""
Упрощенный API для простых случаев использования.

Предоставляет простые функции для тех, кому не нужна вся мощь модуля.
"""

from typing import Dict, Any, Optional, Type, TypeVar
from pydantic import BaseModel
from ..registry.schema_registry import SchemaRegistry, register_schema
from ..factory.model_factory import ModelFactory
from ..models.base import BaseManagerModel, BaseComponentModel

T = TypeVar('T', bound=BaseModel)


def create_config(
    model_class: Type[T],
    data: Optional[Dict[str, Any]] = None,
    auto_register: bool = False
) -> T:
    """
    Упрощенное создание конфигурации.
    
    Автоматически регистрирует схему и создает экземпляр.
    Для простых случаев без ProcessData.
    
    Args:
        model_class: Класс Pydantic модели
        data: Данные для инициализации
        auto_register: Автоматически зарегистрировать схему
        
    Returns:
        Экземпляр модели
        
    Example:
        class AppConfig(BaseModel):
            host: str = "localhost"
            port: int = 8080
        
        config = create_config(AppConfig, {"host": "0.0.0.0"})
    """
    schema_name = model_class.__name__
    registry = SchemaRegistry.get_instance()
    
    # Регистрируем схему если еще не зарегистрирована
    if not registry.has_schema(schema_name):
        registry.register(schema_name, model_class)
    
    # Создаем экземпляр
    if data:
        return registry.create_instance(schema_name, data)
    else:
        return registry.create_instance(schema_name)


def create_manager_config(
    model_class: Type[BaseManagerModel],
    manager_name: str,
    data: Optional[Dict[str, Any]] = None,
    auto_register_in_processdata: bool = False,
    process_name: Optional[str] = None,
    shared_resources: Optional[Any] = None
) -> BaseManagerModel:
    """
    Упрощенное создание конфигурации менеджера.
    
    Args:
        model_class: Класс модели менеджера
        manager_name: Имя менеджера
        data: Данные для инициализации
        auto_register_in_processdata: Автоматически зарегистрировать в ProcessData
        process_name: Имя процесса
        shared_resources: SharedResourcesManager
        
    Returns:
        Экземпляр модели менеджера
        
    Example:
        class LoggerConfig(BaseManagerModel):
            log_level: str = "INFO"
        
        config = create_manager_config(
            LoggerConfig,
            "main_logger",
            {"log_level": "DEBUG"}
        )
    """
    manager_class = model_class.__name__
    registry = SchemaRegistry.get_instance()
    
    # Регистрируем схему если еще не зарегистрирована
    if not registry.has_schema(manager_class):
        registry.register(manager_class, model_class)
    
    # Используем ModelFactory для создания
    return ModelFactory.create_manager(
        manager_class=manager_class,
        manager_name=manager_name,
        data=data,
        auto_register=auto_register_in_processdata,
        process_name=process_name,
        shared_resources=shared_resources
    )


def get_config(
    schema_name: str,
    data: Optional[Dict[str, Any]] = None
) -> BaseModel:
    """
    Получить конфигурацию по имени схемы.
    
    Упрощенная версия для простых случаев.
    
    Args:
        schema_name: Имя схемы
        data: Данные для инициализации
        
    Returns:
        Экземпляр модели
        
    Example:
        config = get_config("AppConfig", {"host": "0.0.0.0"})
    """
    registry = SchemaRegistry.get_instance()
    return registry.create_instance(schema_name, data)


def config_from_dict(
    data: Dict[str, Any],
    schema_name: Optional[str] = None
) -> BaseModel:
    """
    Создать конфигурацию из словаря.
    
    Упрощенная версия create_from_dict.
    
    Args:
        data: Словарь с данными
        schema_name: Имя схемы (определяется из data если не указано)
        
    Returns:
        Экземпляр модели
        
    Example:
        config = config_from_dict({
            "component_class": "AppConfig",
            "host": "0.0.0.0",
            "port": 8080
        })
    """
    return ModelFactory.from_dict(data, schema_name)


# Декоратор для автоматического создания конфигураций
def auto_config(auto_register: bool = True):
    """
    Декоратор для автоматической регистрации и создания конфигураций.
    
    Args:
        auto_register: Автоматически регистрировать схему
        
    Example:
        @auto_config()
        class AppConfig(BaseModel):
            host: str = "localhost"
            port: int = 8080
        
        # Теперь можно использовать:
        config = AppConfig.create({"host": "0.0.0.0"})
    """
    def decorator(model_class: Type[T]) -> Type[T]:
        # Регистрируем схему
        if auto_register:
            schema_name = model_class.__name__
            registry = SchemaRegistry.get_instance()
            if not registry.has_schema(schema_name):
                registry.register(schema_name, model_class)
        
        # Добавляем метод create к классу
        @classmethod
        def create(cls, **kwargs):
            """Создать экземпляр конфигурации."""
            return create_config(cls, kwargs if kwargs else None)
        
        model_class.create = create  # type: ignore
        
        return model_class
    
    return decorator

