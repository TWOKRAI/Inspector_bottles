# -*- coding: utf-8 -*-
"""
Контракты `registry/` — реестр схем.

- `ISchemaRegistry` — современный канон (используется в `SchemaRegistry`).
- `ISchemaManager` — backward-compat для legacy-кода (методы `get_schema`/`has_schema`).

Корневой [data_schema_module/interfaces.py](../interfaces.py) реэкспортирует
эти контракты для обратной совместимости (ADR-DS-005).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type


class ISchemaRegistry(ABC):
    """
    Интерфейс реестра схем.

    Реализация: SchemaRegistry (registry/schema_registry.py).
    Не Singleton — используйте get_default_registry() для глобального экземпляра
    или создайте SchemaRegistry() для изолированного (в тестах).
    """

    @abstractmethod
    def register(self, name: str, schema_class: Type) -> bool:
        """Зарегистрировать схему под именем."""
        ...

    @abstractmethod
    def get(self, name: str) -> Optional[Type]:
        """Получить класс схемы по имени."""
        ...

    @abstractmethod
    def has(self, name: str) -> bool:
        """Проверить наличие схемы."""
        ...

    @abstractmethod
    def list_schemas(self) -> List[str]:
        """Список всех зарегистрированных имён."""
        ...

    @abstractmethod
    def unregister(self, name: str) -> bool:
        """Удалить схему из реестра."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Очистить реестр."""
        ...


class ISchemaManager(ABC):
    """
    Backward-compatible интерфейс реестра схем (старое имя до канона ISchemaRegistry).

    Используйте ISchemaRegistry для нового кода.
    Отличие от ISchemaRegistry: методы называются get_schema/has_schema/create_instance.
    """

    @abstractmethod
    def register(self, schema_name: str, schema_class: Type) -> bool: ...

    @abstractmethod
    def get_schema(self, schema_name: str) -> Optional[Type]: ...

    @abstractmethod
    def has_schema(self, schema_name: str) -> bool: ...

    @abstractmethod
    def create_instance(
        self, schema_name: str, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Any: ...

    @abstractmethod
    def get_defaults(self, schema_name: str) -> Dict[str, Any]: ...

    @abstractmethod
    def validate(
        self, schema_name: str, data: Dict[str, Any]
    ) -> Tuple[bool, Optional[Any], Optional[str]]: ...

    @abstractmethod
    def list_schemas(self) -> List[str]: ...

    @abstractmethod
    def unregister(self, schema_name: str) -> bool: ...

    @abstractmethod
    def clear(self) -> None: ...


__all__ = [
    "ISchemaRegistry",
    "ISchemaManager",
]
