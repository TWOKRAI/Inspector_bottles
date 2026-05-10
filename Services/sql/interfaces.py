# -*- coding: utf-8 -*-
"""
Публичные контракты sql_module.

Все интерфейсы — Protocol с @runtime_checkable для структурной типизации
и моков в тестах. Ядро модуля зависит только от этих интерфейсов.

Правило: внешние модули импортируют только из interfaces.py.
"""
from __future__ import annotations

from abc import abstractmethod
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Any, Dict, List, Optional, Protocol, Tuple, Type, TypeVar, runtime_checkable

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = object  # type: ignore[misc,assignment]


# =============================================================================
# Type Variables
# =============================================================================

T = TypeVar("T", bound=BaseModel)
ID = TypeVar("ID", int, str)


# =============================================================================
# IEngineAdapter — базовый и специализированные
# =============================================================================


@runtime_checkable
class IEngineAdapter(Protocol):
    """Базовый контракт адаптера движка БД."""

    @property
    def is_async(self) -> bool:
        """True если асинхронный режим."""

    def setup(self) -> bool:
        """Настроить и подключить engine. True — успех."""

    def dispose(self) -> None:
        """Освободить ресурсы пула соединений."""


@runtime_checkable
class ISyncEngineAdapter(IEngineAdapter, Protocol):
    """Синхронный адаптер: execute, query, connection context."""

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Выполнить DML. Возвращает количество затронутых строк."""

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Выполнить SELECT. Возвращает список dict (Dict at Boundary)."""

    def connection(self) -> AbstractContextManager[Any]:
        """Контекстный менеджер для ручного управления транзакциями."""


@runtime_checkable
class IAsyncEngineAdapter(IEngineAdapter, Protocol):
    """Асинхронный адаптер: async execute, query, connection context."""

    async def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Выполнить DML. Возвращает количество затронутых строк."""

    async def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Выполнить SELECT. Возвращает список dict (Dict at Boundary)."""

    def connection(self) -> AbstractAsyncContextManager[Any]:
        """Асинхронный контекстный менеджер для транзакций."""


# =============================================================================
# IRepository — Generic репозиторий
# =============================================================================


@runtime_checkable
class IRepository(Protocol[T, ID]):
    """Generic репозиторий: find_by_id, insert, update, delete.

    execute_raw — отдельный метод или специализированный репозиторий.
    """

    def find_by_id(self, id: ID) -> Optional[T]:
        """Найти сущность по ID."""

    def insert(self, entity: T) -> T:
        """Вставить сущность. Возвращает сущность с заполненным ID."""

    def update(self, id: ID, entity: T) -> T:
        """Обновить сущность по ID."""

    def delete(self, id: ID) -> bool:
        """Удалить сущность по ID. True если удалено."""

    def insert_many(self, entities: List[T]) -> List[T]:
        """Вставить список сущностей. Возвращает список вставленных."""

    def update_many(self, updates: List[Tuple[Any, T]]) -> int:
        """Обновить список сущностей. Возвращает количество обновлённых."""

    def find_by(self, **kwargs: Any) -> List[T]:
        """Найти сущности по условиям (AND). Без аргументов — все записи."""


# =============================================================================
# IUnitOfWork — транзакции spanning multiple tables
# =============================================================================


@runtime_checkable
class IUnitOfWork(Protocol):
    """Синхронный Unit of Work: commit, rollback, ленивые репозитории."""

    def __enter__(self) -> "IUnitOfWork":
        """Войти в контекст транзакции."""

    def __exit__(self, *args: Any) -> None:
        """Выйти из контекста."""

    def commit(self) -> None:
        """Зафиксировать транзакцию."""

    def rollback(self) -> None:
        """Откатить транзакцию."""


@runtime_checkable
class IAsyncUnitOfWork(Protocol):
    """Асинхронный Unit of Work."""

    async def __aenter__(self) -> "IAsyncUnitOfWork":
        """Войти в контекст транзакции."""

    async def __aexit__(self, *args: Any) -> None:
        """Выйти из контекста."""

    async def commit(self) -> None:
        """Зафиксировать транзакцию."""

    async def rollback(self) -> None:
        """Откатить транзакцию."""


# =============================================================================
# ISchemaMapper — адаптер SchemaBase <-> SQLAlchemy
# =============================================================================


@runtime_checkable
class ISchemaMapper(Protocol):
    """Адаптер: schema_class <-> table_meta.

    Плагин — можно заменить на SQLModel, ORM без изменения GenericRepository.
    """

    def schema_to_table_meta(self, schema_class: Type[Any]) -> Dict[str, Any]:
        """Преобразовать класс схемы в метаданные таблицы (колонки, типы)."""

    def row_to_entity(self, row: Dict[str, Any], schema_class: Type[T]) -> T:
        """Преобразовать строку БД в сущность."""

    def entity_to_row(self, entity: T) -> Dict[str, Any]:
        """Преобразовать сущность в словарь для INSERT/UPDATE."""


# =============================================================================
# ISQLManager — контракт менеджера
# =============================================================================


@runtime_checkable
class ISQLManager(Protocol):
    """Контракт SQL-менеджера.

    execute, query — низкоуровневые операции.
    uow() — транзакции spanning multiple tables.
    get_repository — репозиторий по схеме.
    execute_command — для CommandManager (Dict at Boundary).
    """

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Выполнить DML. Возвращает количество затронутых строк."""

    def query(
        self, sql: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Выполнить SELECT. Возвращает список dict (Dict at Boundary)."""

    def uow(self) -> IUnitOfWork:
        """Контекстный менеджер для транзакций (sync)."""

    def uow_async(self) -> IAsyncUnitOfWork:
        """Асинхронный Unit of Work."""

    def get_repository(self, schema_class: Type[T]) -> IRepository[T, ID]:
        """Получить репозиторий по классу схемы."""

    def execute_command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Обработать команду от CommandManager. Dict at Boundary."""

    def create_tables(self, schema_classes: list, dialect: Optional[str] = None) -> int:
        """Автоматически создать таблицы из списка SchemaBase-классов.
        Возвращает количество выполненных DDL-операторов."""

    def objects(self, schema_class: type) -> Any:
        """Получить QuerySet для Django-style chained queries."""
