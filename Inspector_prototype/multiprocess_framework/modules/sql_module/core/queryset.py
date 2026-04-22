# -*- coding: utf-8 -*-
"""QuerySet в стиле Django для SchemaBase.

Генерирует параметризованный SQL из цепочки вызовов методов.
Все значения параметризованы — SQL-injection невозможна.

Usage:
    qs = QuerySet(adapter, UserSchema, mapper, "users")
    users = qs.filter(age__gte=18).order_by("-score").limit(10).all()
"""
from __future__ import annotations

from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar

T = TypeVar("T")


class QuerySet(Generic[T]):
    """Immutable query builder. Каждый метод возвращает НОВЫЙ QuerySet.

    Поддерживает field lookups в стиле Django:
        field__eq, field__ne, field__gt, field__gte, field__lt, field__lte,
        field__in, field__like, field__isnull

    Terminal методы выполняют SQL через adapter:
        all(), first(), count(), values(), delete(), update()
    """

    _LOOKUPS = frozenset({
        "eq", "ne", "gt", "gte", "lt", "lte", "in", "like", "isnull",
    })

    _OP_MAP = {
        "eq": "=",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "like": "LIKE",
    }

    def __init__(
        self,
        adapter: Any,
        schema_class: Type[T],
        schema_mapper: Any,
        table_name: str,
    ) -> None:
        self._adapter = adapter
        self._schema_class = schema_class
        self._mapper = schema_mapper
        self._table_name = table_name
        self._filters: List[Tuple[str, str, Any]] = []  # (column, op, value)
        self._excludes: List[Tuple[str, str, Any]] = []
        self._order_fields: List[str] = []
        self._limit_val: Optional[int] = None
        self._offset_val: Optional[int] = None
        self._param_counter: int = 0

    # =========================================================================
    # Chaining методы — каждый возвращает НОВЫЙ QuerySet (immutable)
    # =========================================================================

    def filter(self, **kwargs: Any) -> QuerySet[T]:
        """Добавить WHERE условия.

        Lookups: field__eq, field__gt, field__gte, field__lt, field__lte,
                 field__ne, field__in, field__like, field__isnull.
        Простое имя поля — по умолчанию 'eq'.
        """
        qs = self._clone()
        for key, value in kwargs.items():
            column, op = self._parse_lookup(key)
            qs._filters.append((column, op, value))
        return qs

    def exclude(self, **kwargs: Any) -> QuerySet[T]:
        """Добавить WHERE NOT условия."""
        qs = self._clone()
        for key, value in kwargs.items():
            column, op = self._parse_lookup(key)
            qs._excludes.append((column, op, value))
        return qs

    def order_by(self, *fields: str) -> QuerySet[T]:
        """Установить ORDER BY. Префикс '-' для DESC.

        Пример: order_by("-score", "name")
        """
        qs = self._clone()
        qs._order_fields = list(fields)
        return qs

    def limit(self, n: int) -> QuerySet[T]:
        """Установить LIMIT clause."""
        qs = self._clone()
        qs._limit_val = int(n)
        return qs

    def offset(self, n: int) -> QuerySet[T]:
        """Установить OFFSET clause."""
        qs = self._clone()
        qs._offset_val = int(n)
        return qs

    # =========================================================================
    # Terminal методы — выполнить query
    # =========================================================================

    def all(self) -> List[T]:
        """Выполнить SELECT, вернуть schema экземпляры."""
        sql, params = self._build_select()
        rows = self._adapter.query(sql, params)
        return [self._mapper.row_to_entity(row, self._schema_class) for row in rows]

    def first(self) -> Optional[T]:
        """Выполнить SELECT с LIMIT 1."""
        qs = self.limit(1)
        results = qs.all()
        return results[0] if results else None

    def count(self) -> int:
        """Выполнить SELECT COUNT(*)."""
        sql, params = self._build_count()
        rows = self._adapter.query(sql, params)
        return rows[0].get("count", 0) if rows else 0

    def values(self) -> List[Dict[str, Any]]:
        """Выполнить SELECT, вернуть сырые dicts (Dict at Boundary)."""
        sql, params = self._build_select()
        return self._adapter.query(sql, params)

    def delete(self) -> int:
        """Выполнить DELETE с WHERE clauses. Возвращает rowcount."""
        sql, params = self._build_delete()
        return self._adapter.execute(sql, params)

    def update(self, **kwargs: Any) -> int:
        """Выполнить UPDATE SET ... WHERE .... Возвращает rowcount."""
        sql, params = self._build_update(kwargs)
        return self._adapter.execute(sql, params)

    # =========================================================================
    # Внутренние методы
    # =========================================================================

    def _clone(self) -> QuerySet[T]:
        """Deep copy для immutability."""
        qs = QuerySet(
            self._adapter, self._schema_class, self._mapper, self._table_name,
        )
        qs._filters = list(self._filters)
        qs._excludes = list(self._excludes)
        qs._order_fields = list(self._order_fields)
        qs._limit_val = self._limit_val
        qs._offset_val = self._offset_val
        qs._param_counter = self._param_counter
        return qs

    @staticmethod
    def _validate_column(name: str) -> str:
        """Валидировать, что имя колонки — безопасный SQL идентификатор."""
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
            raise ValueError(f"Invalid column name: {name!r}")
        return name

    def _parse_lookup(self, key: str) -> Tuple[str, str]:
        """Распарсить 'field__lookup' в (field_name, operator).

        Если нет lookup суффикса, по умолчанию 'eq'.
        """
        parts = key.rsplit("__", 1)
        if len(parts) == 2 and parts[1] in self._LOOKUPS:
            column = parts[0]
            lookup = parts[1]
        else:
            column = key
            lookup = "eq"
        self._validate_column(column)
        return column, lookup

    def _next_param(self) -> str:
        """Генерировать уникальное имя параметра: _p0, _p1, ..."""
        name = f"_p{self._param_counter}"
        self._param_counter += 1
        return name

    def _build_where(self) -> Tuple[str, Dict[str, Any]]:
        """Построить WHERE clause из filters и excludes."""
        clauses: List[str] = []
        params: Dict[str, Any] = {}

        for col, op, val in self._filters:
            clause, new_params = self._render_condition(col, op, val)
            clauses.append(clause)
            params.update(new_params)

        for col, op, val in self._excludes:
            clause, new_params = self._render_condition(col, op, val)
            clauses.append(f"NOT ({clause})")
            params.update(new_params)

        where = " AND ".join(clauses) if clauses else ""
        return where, params

    def _render_condition(
        self, col: str, op: str, val: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """Отрендерить одно условие в SQL фрагмент + params dict."""
        params: Dict[str, Any] = {}

        if op == "isnull":
            if val:
                return f'"{col}" IS NULL', params
            return f'"{col}" IS NOT NULL', params

        if op == "in":
            if not val:  # пустой список
                return "1=0", params
            placeholders = []
            for item in val:
                p = self._next_param()
                params[p] = item
                placeholders.append(f":{p}")
            return f'"{col}" IN ({", ".join(placeholders)})', params

        p = self._next_param()
        params[p] = val
        return f'"{col}" {self._OP_MAP[op]} :{p}', params

    def _build_select(self) -> Tuple[str, Dict[str, Any]]:
        """Построить полное SELECT выражение."""
        where, params = self._build_where()
        sql = f'SELECT * FROM "{self._table_name}"'
        if where:
            sql += f" WHERE {where}"
        if self._order_fields:
            order_parts = []
            for field in self._order_fields:
                if field.startswith("-"):
                    self._validate_column(field[1:])
                    order_parts.append(f'"{field[1:]}" DESC')
                else:
                    self._validate_column(field)
                    order_parts.append(f'"{field}" ASC')
            sql += " ORDER BY " + ", ".join(order_parts)
        if self._limit_val is not None:
            sql += f" LIMIT {self._limit_val}"
        if self._offset_val is not None:
            sql += f" OFFSET {self._offset_val}"
        return sql, params

    def _build_count(self) -> Tuple[str, Dict[str, Any]]:
        """Построить SELECT COUNT(*) выражение."""
        where, params = self._build_where()
        sql = f'SELECT COUNT(*) as count FROM "{self._table_name}"'
        if where:
            sql += f" WHERE {where}"
        return sql, params

    def _build_delete(self) -> Tuple[str, Dict[str, Any]]:
        """Построить DELETE выражение."""
        where, params = self._build_where()
        sql = f'DELETE FROM "{self._table_name}"'
        if where:
            sql += f" WHERE {where}"
        return sql, params

    def _build_update(self, values: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Построить UPDATE SET выражение."""
        where, params = self._build_where()
        set_parts = []
        for col, val in values.items():
            self._validate_column(col)
            p = self._next_param()
            params[p] = val
            set_parts.append(f'"{col}" = :{p}')
        sql = f'UPDATE "{self._table_name}" SET {", ".join(set_parts)}'
        if where:
            sql += f" WHERE {where}"
        return sql, params


class AsyncQuerySet(Generic[T]):
    """Async версия QuerySet. Тот же chaining API, async terminal методы.

    Usage:
        qs = AsyncQuerySet(async_adapter, UserSchema, mapper, "users")
        users = await qs.filter(age__gte=18).order_by("-score").limit(10).all()
    """

    def __init__(
        self,
        adapter: Any,
        schema_class: Type[T],
        schema_mapper: Any,
        table_name: str,
    ) -> None:
        self._qs = QuerySet(adapter, schema_class, schema_mapper, table_name)
        self._adapter = adapter
        self._schema_class = schema_class
        self._mapper = schema_mapper

    # Chaining — делегировать внутреннему QuerySet, обернуть результат

    def filter(self, **kwargs: Any) -> AsyncQuerySet[T]:
        new = AsyncQuerySet(self._adapter, self._schema_class, self._mapper, self._qs._table_name)
        new._qs = self._qs.filter(**kwargs)
        new._qs._adapter = self._adapter
        return new

    def exclude(self, **kwargs: Any) -> AsyncQuerySet[T]:
        new = AsyncQuerySet(self._adapter, self._schema_class, self._mapper, self._qs._table_name)
        new._qs = self._qs.exclude(**kwargs)
        new._qs._adapter = self._adapter
        return new

    def order_by(self, *fields: str) -> AsyncQuerySet[T]:
        new = AsyncQuerySet(self._adapter, self._schema_class, self._mapper, self._qs._table_name)
        new._qs = self._qs.order_by(*fields)
        new._qs._adapter = self._adapter
        return new

    def limit(self, n: int) -> AsyncQuerySet[T]:
        new = AsyncQuerySet(self._adapter, self._schema_class, self._mapper, self._qs._table_name)
        new._qs = self._qs.limit(n)
        new._qs._adapter = self._adapter
        return new

    def offset(self, n: int) -> AsyncQuerySet[T]:
        new = AsyncQuerySet(self._adapter, self._schema_class, self._mapper, self._qs._table_name)
        new._qs = self._qs.offset(n)
        new._qs._adapter = self._adapter
        return new

    # Async terminal методы

    async def all(self) -> List[T]:
        """Выполнить SELECT, вернуть schema экземпляры."""
        sql, params = self._qs._build_select()
        rows = await self._adapter.query(sql, params)
        return [self._mapper.row_to_entity(row, self._schema_class) for row in rows]

    async def first(self) -> Optional[T]:
        """Выполнить SELECT с LIMIT 1."""
        results = await self.limit(1).all()
        return results[0] if results else None

    async def count(self) -> int:
        """Выполнить SELECT COUNT(*)."""
        sql, params = self._qs._build_count()
        rows = await self._adapter.query(sql, params)
        return rows[0].get("count", 0) if rows else 0

    async def values(self) -> List[Dict[str, Any]]:
        """Выполнить SELECT, вернуть сырые dicts (Dict at Boundary)."""
        sql, params = self._qs._build_select()
        return await self._adapter.query(sql, params)

    async def delete(self) -> int:
        """Выполнить DELETE с WHERE clauses. Возвращает rowcount."""
        sql, params = self._qs._build_delete()
        return await self._adapter.execute(sql, params)

    async def update(self, **kwargs: Any) -> int:
        """Выполнить UPDATE SET ... WHERE .... Возвращает rowcount."""
        sql, params = self._qs._build_update(kwargs)
        return await self._adapter.execute(sql, params)
