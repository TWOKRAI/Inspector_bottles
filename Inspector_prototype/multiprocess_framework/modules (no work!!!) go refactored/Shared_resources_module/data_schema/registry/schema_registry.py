"""
Реестр Pydantic схем (моделей).

Упрощенная версия без дублирования методов.
"""

from typing import Dict, Type, Optional, Any, Tuple
from threading import RLock
import time
from pydantic import BaseModel, ValidationError

from ..core.interfaces import ISchemaRegistry
from ..core.exceptions import (
    SchemaNotFoundError,
    SchemaValidationError,
    SchemaRegistrationError,
    InvalidParameterError
)
from ..core.metrics import increment_metric, record_timing


def register_schema(schema_name: Optional[str] = None, auto_register: bool = True):
    """
    Декоратор для автоматической регистрации Pydantic моделей в SchemaRegistry.
    
    Args:
        schema_name: Имя схемы (если None, используется имя класса)
        auto_register: Автоматически зарегистрировать при импорте
    
    Example:
        @register_schema("LoggerConfig")
        class LoggerConfig(BaseModel):
            log_level: str = "INFO"
    """
    def decorator(model_class: Type[BaseModel]) -> Type[BaseModel]:
        name = schema_name if schema_name is not None else model_class.__name__
        
        if auto_register:
            registry = SchemaRegistry.get_instance()
            registry.register(name, model_class)
        
        model_class._schema_name = name  # type: ignore
        return model_class
    
    return decorator


class SchemaRegistry(ISchemaRegistry):
    """
    Реестр Pydantic схем.
    
    Хранит зарегистрированные модели и предоставляет методы для создания
    экземпляров с дефолтными значениями.
    """
    
    _instance: Optional['SchemaRegistry'] = None
    _lock = RLock()
    
    def __init__(self):
        """Инициализация реестра."""
        self._schemas: Dict[str, Type[BaseModel]] = {}
    
    @classmethod
    def get_instance(cls) -> 'SchemaRegistry':
        """Получить глобальный экземпляр (Singleton)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def register(self, schema_name: str, schema_class: Type[BaseModel]) -> bool:
        """
        Зарегистрировать схему (Pydantic модель).
        
        Args:
            schema_name: Имя схемы (обычно имя класса)
            schema_class: Класс Pydantic модели
            
        Returns:
            True если регистрация успешна
            
        Raises:
            InvalidParameterError: Если schema_name пустой или None
            SchemaRegistrationError: Если schema_class не является BaseModel
        """
        if not schema_name or not isinstance(schema_name, str):
            raise InvalidParameterError(
                "schema_name",
                schema_name,
                "должно быть непустой строкой"
            )
        
        if not isinstance(schema_class, type):
            raise InvalidParameterError(
                "schema_class",
                schema_class,
                "должен быть классом"
            )
        
        with self._lock:
            if not issubclass(schema_class, BaseModel):
                raise SchemaRegistrationError(
                    schema_name,
                    f"Схема должна быть подклассом BaseModel, получен {type(schema_class)}",
                    schema_class
                )
            self._schemas[schema_name] = schema_class
            increment_metric("data_schema.schema_registered", {"schema_name": schema_name})
            return True
    
    def get_schema(self, schema_name: str) -> Optional[Type[BaseModel]]:
        """Получить зарегистрированную схему."""
        with self._lock:
            return self._schemas.get(schema_name)
    
    def has_schema(self, schema_name: str) -> bool:
        """Проверить наличие схемы."""
        with self._lock:
            return schema_name in self._schemas
    
    def create_instance(
        self,
        schema_name: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> BaseModel:
        """
        Создать экземпляр модели с дефолтными значениями из схемы.
        
        Args:
            schema_name: Имя схемы
            data: Данные для инициализации (опционально)
            **kwargs: Дополнительные поля для инициализации
            
        Returns:
            Экземпляр Pydantic модели
            
        Raises:
            InvalidParameterError: Если schema_name невалиден
            SchemaNotFoundError: Если схема не найдена
            SchemaValidationError: Если ошибка валидации
        """
        if not schema_name or not isinstance(schema_name, str):
            raise InvalidParameterError(
                "schema_name",
                schema_name,
                "должно быть непустой строкой"
            )
        
        schema = self.get_schema(schema_name)
        if schema is None:
            available = self.list_schemas()
            raise SchemaNotFoundError(schema_name, available)
        
        init_data = {}
        if data is not None:
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
            if init_data:
                instance = schema(**init_data)
            else:
                instance = schema()
            
            duration = time.time() - start_time
            record_timing("data_schema.instance_created", duration, {"schema_name": schema_name})
            increment_metric("data_schema.instances_created", {"schema_name": schema_name})
            
            return instance
        except ValidationError as e:
            duration = time.time() - start_time
            record_timing("data_schema.instance_creation_failed", duration, {"schema_name": schema_name})
            increment_metric("data_schema.creation_errors", {"schema_name": schema_name})
            raise SchemaValidationError(
                schema_name,
                e.errors(),
                init_data
            ) from e
    
    def get_defaults(self, schema_name: str) -> Dict[str, Any]:
        """Получить дефолтные значения схемы."""
        schema = self.get_schema(schema_name)
        if schema is None:
            return {}
        
        instance = schema()
        return instance.model_dump()
    
    def validate(
        self,
        schema_name: str,
        data: Dict[str, Any]
    ) -> Tuple[bool, Optional[BaseModel], Optional[str]]:
        """Валидировать данные по схеме."""
        if not schema_name or not isinstance(schema_name, str):
            return False, None, f"Неверный параметр schema_name: должно быть непустой строкой"
        
        if not isinstance(data, dict):
            return False, None, f"Неверный параметр data: должен быть словарем"
        
        schema = self.get_schema(schema_name)
        if schema is None:
            available = self.list_schemas()
            available_str = ", ".join(available[:10]) if available else "нет доступных"
            return False, None, f"Схема {schema_name} не найдена. Доступные: {available_str}"
        
        try:
            instance = schema(**data)
            return True, instance, None
        except ValidationError as e:
            error_msg = "; ".join([
                f"{'.'.join(str(loc) for loc in err.get('loc', []))}: {err.get('msg', 'Unknown error')}"
                for err in e.errors()
            ])
            return False, None, error_msg
    
    def list_schemas(self) -> list[str]:
        """Получить список всех зарегистрированных схем."""
        with self._lock:
            return list(self._schemas.keys())
    
    def unregister(self, schema_name: str) -> bool:
        """Удалить схему из реестра."""
        with self._lock:
            if schema_name in self._schemas:
                del self._schemas[schema_name]
                return True
            return False
    
    def clear(self):
        """Очистить все зарегистрированные схемы."""
        with self._lock:
            self._schemas.clear()


