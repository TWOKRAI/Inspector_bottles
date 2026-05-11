# -*- coding: utf-8 -*-
"""
Контракты `serialization/` — конвертация и хранилище для контейнера.

- `IDataConverter` — конвертер моделей в dict/JSON/YAML (реализация: `converter.py`).
- `ISchemaStorage` — хранилище для `RegistersContainer` (реализация: `file_storage.py`).
- `IAsyncSchemaStorage` — async-версия для Redis/PostgreSQL/S3.
- `IRegisterStorage` / `IAsyncRegisterStorage` — backward-compat aliases.

Корневой [data_schema_module/interfaces.py](../interfaces.py) реэкспортирует
эти контракты для обратной совместимости (ADR-DS-005).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Type, runtime_checkable

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore[assignment]


class IDataConverter(ABC):
    """Интерфейс для конвертера данных (реализация: serialization/converter.py)."""

    @abstractmethod
    def model_to_dict(self, model: Any, **kwargs) -> Dict[str, Any]:
        """Конвертировать Pydantic модель в словарь."""
        ...

    @abstractmethod
    def dict_to_model(self, data: Dict[str, Any], model_class: Type, **kwargs) -> Any:
        """Конвертировать словарь в Pydantic модель."""
        ...

    @abstractmethod
    def model_to_json(self, model: Any, **kwargs) -> str:
        """Конвертировать Pydantic модель в JSON строку."""
        ...

    @abstractmethod
    def json_to_model(self, json_str: str, model_class: Type, **kwargs) -> Any:
        """Конвертировать JSON строку в Pydantic модель."""
        ...


@runtime_checkable
class ISchemaStorage(Protocol):
    """
    Протокол хранилища для RegistersContainer.

    Переименован из IRegisterStorage (старое имя — alias ниже).
    Позволяет менять бэкенд хранения без изменения бизнес-логики.

    Готовые реализации:
        FileStorage       — JSON-файлы (serialization/file_storage.py)

    Будущие реализации (реализуйте этот же протокол):
        SQLiteStorage     — локальная БД (offline-first)
        PostgreSQLStorage — серверная СУБД
        RedisStorage      — in-memory с персистентностью
        S3Storage         — облачное хранилище

    Пример реализации:

        class SQLiteStorage:
            def load(self, container_name: str) -> dict: ...
            def save(self, container_name: str, data: dict) -> None: ...
            def exists(self, container_name: str) -> bool: ...
            def delete(self, container_name: str) -> bool: ...
    """

    def load(self, container_name: str) -> Dict[str, Any]: ...

    def save(self, container_name: str, data: Dict[str, Any]) -> None: ...

    def exists(self, container_name: str) -> bool: ...

    def delete(self, container_name: str) -> bool: ...


@runtime_checkable
class IAsyncSchemaStorage(Protocol):
    """
    Async-версия ISchemaStorage для неблокирующих бэкендов.

    Переименован из IAsyncRegisterStorage (старое имя — alias ниже).
    Для использования с Redis, PostgreSQL, S3 и другими async-хранилищами.

    TODO: Интегрировать в RegistersContainer через async_save / async_load.
    """

    async def load(self, container_name: str) -> Dict[str, Any]: ...

    async def save(self, container_name: str, data: Dict[str, Any]) -> None: ...

    async def exists(self, container_name: str) -> bool: ...

    async def delete(self, container_name: str) -> bool: ...


# Backward compatibility aliases
IRegisterStorage = ISchemaStorage
IAsyncRegisterStorage = IAsyncSchemaStorage


__all__ = [
    "IDataConverter",
    "ISchemaStorage",
    "IAsyncSchemaStorage",
    "IRegisterStorage",
    "IAsyncRegisterStorage",
]
