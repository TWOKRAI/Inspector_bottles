# -*- coding: utf-8 -*-
"""
SchemaRegistry — реестр Pydantic схем (без Singleton).

Ключевые решения:
    - SchemaRegistry — обычный класс, не Singleton. Создавайте изолированные
      экземпляры в тестах: registry = SchemaRegistry()
    - get_default_registry() — возвращает глобальный экземпляр (удобство)
    - register_schema() — декоратор, использует default registry если не указан
    - SchemaManager — backward-compatible alias для SchemaRegistry

Backward compatibility:
    SchemaManager.get_instance()  →  get_default_registry()
    @register_schema("Name")      →  без изменений (использует default registry)
"""

from __future__ import annotations

import time
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..core.exceptions import (
    InvalidParameterError,
    SchemaNotFoundError,
    SchemaRegistrationError,
    SchemaValidationError,
)
from .interfaces import ISchemaManager

try:
    from ..extensions.metrics import increment_metric, record_timing
except ImportError:

    def increment_metric(*args: Any, **kwargs: Any) -> None:
        pass

    def record_timing(*args: Any, **kwargs: Any) -> None:
        pass


class SchemaRegistry(ISchemaManager):
    """
    Реестр Pydantic схем.

    Хранит зарегистрированные модели и предоставляет методы для создания
    экземпляров с дефолтными значениями.

    Не Singleton — для изолированного тестирования создайте новый экземпляр:
        registry = SchemaRegistry()

    Для глобального экземпляра используйте:
        registry = get_default_registry()
    """

    def __init__(self) -> None:
        self._schemas: Dict[str, Type[BaseModel]] = {}
        self._lock = RLock()

    # =========================================================================
    # ISchemaManager (backward compat interface)
    # =========================================================================

    def register(self, schema_name: str, schema_class: Type[BaseModel]) -> bool:
        """
        Зарегистрировать схему (Pydantic модель).

        Raises:
            InvalidParameterError: Если schema_name пустой или None
            SchemaRegistrationError: Если schema_class не является BaseModel
        """
        if not schema_name or not isinstance(schema_name, str):
            raise InvalidParameterError(
                "schema_name",
                schema_name,
                "должно быть непустой строкой",
            )

        if not isinstance(schema_class, type):
            raise InvalidParameterError(
                "schema_class",
                schema_class,
                "должен быть классом",
            )

        with self._lock:
            if not issubclass(schema_class, BaseModel):
                raise SchemaRegistrationError(
                    schema_name,
                    f"Схема должна быть подклассом BaseModel, получен {type(schema_class)}",
                    schema_class,
                )
            self._schemas[schema_name] = schema_class
            increment_metric("data_schema.schema_registered", {"schema_name": schema_name})
            return True

    def get_schema(self, schema_name: str) -> Optional[Type[BaseModel]]:
        """Получить зарегистрированную схему по имени."""
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
        **kwargs: Any,
    ) -> BaseModel:
        """
        Создать экземпляр модели с дефолтными значениями из схемы.

        Raises:
            InvalidParameterError: Если schema_name невалиден
            SchemaNotFoundError: Если схема не найдена
            SchemaValidationError: Если ошибка валидации
        """
        if not schema_name or not isinstance(schema_name, str):
            raise InvalidParameterError(
                "schema_name",
                schema_name,
                "должно быть непустой строкой",
            )

        schema = self.get_schema(schema_name)
        if schema is None:
            raise SchemaNotFoundError(schema_name, self.list_schemas())

        init_data: Dict[str, Any] = {}
        if data is not None:
            if not isinstance(data, dict):
                raise InvalidParameterError("data", data, "должен быть словарем")
            init_data.update(data)
        if kwargs:
            init_data.update(kwargs)

        start_time = time.time()
        try:
            instance = schema(**init_data) if init_data else schema()
            duration = time.time() - start_time
            record_timing("data_schema.instance_created", duration, {"schema_name": schema_name})
            increment_metric("data_schema.instances_created", {"schema_name": schema_name})
            return instance
        except ValidationError as e:
            duration = time.time() - start_time
            record_timing(
                "data_schema.instance_creation_failed",
                duration,
                {"schema_name": schema_name},
            )
            increment_metric("data_schema.creation_errors", {"schema_name": schema_name})
            raise SchemaValidationError(schema_name, e.errors(), init_data) from e

    def get_defaults(self, schema_name: str) -> Dict[str, Any]:
        """Получить дефолтные значения схемы."""
        schema = self.get_schema(schema_name)
        if schema is None:
            return {}
        return schema().model_dump()

    def validate(
        self,
        schema_name: str,
        data: Dict[str, Any],
    ) -> Tuple[bool, Optional[BaseModel], Optional[str]]:
        """Валидировать данные по схеме."""
        if not schema_name or not isinstance(schema_name, str):
            return False, None, "Неверный параметр schema_name: должно быть непустой строкой"

        if not isinstance(data, dict):
            return False, None, "Неверный параметр data: должен быть словарем"

        schema = self.get_schema(schema_name)
        if schema is None:
            available = self.list_schemas()
            available_str = ", ".join(available[:10]) if available else "нет доступных"
            return False, None, f"Схема {schema_name} не найдена. Доступные: {available_str}"

        try:
            instance = schema(**data)
            return True, instance, None
        except ValidationError as e:
            error_msg = "; ".join(
                [
                    f"{'.'.join(str(loc) for loc in err.get('loc', []))}: {err.get('msg', 'Unknown error')}"
                    for err in e.errors()
                ]
            )
            return False, None, error_msg

    def list_schemas(self) -> List[str]:
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

    def clear(self) -> None:
        """Очистить все зарегистрированные схемы."""
        with self._lock:
            self._schemas.clear()

    def validate_recipe(
        self,
        snapshot: Dict[str, Any],
        register_names: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Валидировать снимок рецепта (dict по имени регистра -> data).

        Args:
            snapshot: Словарь {register_name: data_dict}.
            register_names: Если задан, проверяются только эти ключи; иначе все ключи snapshot.

        Returns:
            (True, None) при успехе; (False, error_message) при ошибке.
        """
        if not isinstance(snapshot, dict):
            return False, "snapshot должен быть словарем"
        keys = register_names if register_names is not None else list(snapshot.keys())
        for name in keys:
            if name not in snapshot:
                continue
            schema = self.get_schema(name)
            if schema is None:
                continue
            ok, _, err = self.validate(name, snapshot[name])
            if not ok:
                return False, f"Регистр {name}: {err}"
        return True, None

    # =========================================================================
    # Backward compatibility: Singleton-style access
    # =========================================================================

    _global_instance: Optional["SchemaRegistry"] = None
    _global_lock = RLock()

    @classmethod
    def get_instance(cls) -> "SchemaRegistry":
        """
        Backward-compatible метод получения глобального экземпляра.

        Предпочтительный способ: get_default_registry()
        """
        return get_default_registry()


# =============================================================================
# Глобальный экземпляр и удобные функции
# =============================================================================

_default_registry: Optional[SchemaRegistry] = None
_default_registry_lock = RLock()


def get_default_registry() -> SchemaRegistry:
    """
    Получить глобальный экземпляр SchemaRegistry.

    Создаётся лениво при первом вызове. Потокобезопасно.
    Для изолированного тестирования создайте SchemaRegistry() напрямую.
    """
    global _default_registry
    if _default_registry is None:
        with _default_registry_lock:
            if _default_registry is None:
                _default_registry = SchemaRegistry()
    return _default_registry


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def register_schema(
    schema_name: Optional[str] = None,
    auto_register: bool = True,
    registry: Optional[SchemaRegistry] = None,
) -> Callable[[Type[_ModelT]], Type[_ModelT]]:
    """
    Декоратор для автоматической регистрации Pydantic моделей.

    Args:
        schema_name:   Имя схемы (если None, используется имя класса)
        auto_register: Автоматически зарегистрировать при импорте
        registry:      Реестр для регистрации (если None — default registry)

    Example:
        @register_schema("LoggerConfig")
        class LoggerConfig(BaseModel):
            log_level: str = "INFO"

        # Для изолированного тестирования:
        my_registry = SchemaRegistry()

        @register_schema("TestConfig", registry=my_registry)
        class TestConfig(BaseModel):
            value: int = 0
    """

    def decorator(model_class: Type[_ModelT]) -> Type[_ModelT]:
        name = schema_name if schema_name is not None else model_class.__name__

        if auto_register:
            target_registry = registry if registry is not None else get_default_registry()
            target_registry.register(name, model_class)

        model_class._schema_name = name  # type: ignore
        return model_class

    return decorator


# =============================================================================
# Backward compatibility alias
# =============================================================================

# SchemaManager — старое имя. Используйте SchemaRegistry для нового кода.
SchemaManager = SchemaRegistry
