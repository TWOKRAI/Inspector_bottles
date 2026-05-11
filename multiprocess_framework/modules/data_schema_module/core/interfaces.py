# -*- coding: utf-8 -*-
"""
Контракты домена `core/` — фундамент data_schema_module.

Эти Protocol/ABC описывают «что такое схема» с минимумом зависимостей:
- `ISchema` — то, что есть у любой схемы (model_dump, get_field_meta, update_field).
- `ISchemaAdapter` — адаптер схемы для модулей-потребителей (Dependency Inversion).
- `HasBuild` — Dict at Boundary protocol (ADR-008): любой объект с `build()`.
- `IDataValidator` — контракт валидатора (реализация: `core/validators.py`).

Корневой [data_schema_module/interfaces.py](../interfaces.py) реэкспортирует
эти контракты для обратной совместимости (ADR-DS-005).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type, runtime_checkable

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore[assignment]


@runtime_checkable
class ISchema(Protocol):
    """
    Протокол для любой схемы данных (RegisterBase / SchemaBase).

    Реализуется через RegisterMixin + Pydantic BaseModel.
    Используется для type hints в адаптерах и реестре.
    """

    def model_dump(self) -> Dict[str, Any]: ...

    @classmethod
    def get_field_meta(cls, field_name: str) -> Any: ...

    @classmethod
    def get_all_fields_meta(cls) -> Dict[str, Any]: ...

    def update_field(
        self, field_name: str, value: Any, access_level: int = 0
    ) -> Tuple[bool, Optional[str]]: ...

    def validate_field(
        self, field_name: str, value: Any, access_level: int = 0
    ) -> Tuple[bool, Optional[str]]: ...


@runtime_checkable
class ISchemaAdapter(Protocol):
    """
    Протокол адаптера схемы для потребляющих модулей.

    Адаптеры живут в потребляющих модулях (Dependency Inversion):
        config_module/adapters/schema_adapter.py  — Schema -> дерево параметров
        router_module/adapters/schema_adapter.py  — Schema -> маршруты
        process_manager_module/adapters/...       — Schema -> process config dict

    Пример реализации:

        class ConfigSchemaAdapter:
            def adapt(self, schema_class: Type[SchemaBase], **options) -> Dict[str, Any]:
                return {
                    name: {"default": meta.default, "description": meta.description}
                    for name, meta in schema_class.get_all_fields_meta().items()
                }

            def adapt_instance(self, instance: SchemaBase, **options) -> Dict[str, Any]:
                return instance.model_dump()
    """

    def adapt(self, schema_class: Type, **options) -> Dict[str, Any]: ...

    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]: ...


@runtime_checkable
class HasBuild(Protocol):
    """
    Протокол конфига с build() -> (name, dict).

    Реализуют Process1Config, Worker1Config, ErrorManagerConfig и др.
    Без зависимости от RegisterBase — любой объект с build() подходит.

    Пример:

        class MyConfig:
            def build(self) -> Tuple[str, Dict[str, Any]]:
                return "my_process", {"key": "value"}
    """

    def build(self) -> Tuple[str, Dict[str, Any]]: ...


class IDataValidator(ABC):
    """Интерфейс для валидатора данных (реализация: core/validators.py)."""

    @abstractmethod
    def validate(
        self,
        data: Dict[str, Any],
        model_class: Type,
        strict: bool = False,
    ) -> Tuple[bool, Optional[Any], Optional[str]]:
        """Валидировать данные по модели."""
        ...

    @abstractmethod
    def is_valid(
        self,
        data: Dict[str, Any],
        model_class: Type,
        strict: bool = False,
    ) -> bool:
        """Проверить валидность данных без создания экземпляра."""
        ...

    @abstractmethod
    def get_validation_errors(
        self,
        data: Dict[str, Any],
        model_class: Type,
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        """Получить список ошибок валидации."""
        ...


__all__ = [
    "ISchema",
    "ISchemaAdapter",
    "HasBuild",
    "IDataValidator",
]
