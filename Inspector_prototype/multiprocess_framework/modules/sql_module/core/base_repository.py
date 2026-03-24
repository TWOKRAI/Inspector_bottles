# -*- coding: utf-8 -*-
"""
GenericRepository — CRUD репозиторий по схеме.

Зависит от ISyncEngineAdapter и ISchemaMapper.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Type, TypeVar

from sql_module.interfaces import ISchemaMapper, ISyncEngineAdapter

T = TypeVar("T")
ID = TypeVar("ID", int, str)


class GenericRepository:
    """Generic репозиторий: find_by_id, insert, update, delete."""

    def __init__(
        self,
        adapter: ISyncEngineAdapter,
        schema_class: Type[T],
        table_name: Optional[str] = None,
        id_column: str = "id",
        schema_mapper: Optional[ISchemaMapper] = None,
    ):
        self._adapter = adapter
        self._schema_class = schema_class
        self._mapper = schema_mapper or _default_mapper()
        meta = self._mapper.schema_to_table_meta(schema_class)
        self._table_name = table_name or meta.get("table_name", schema_class.__name__.lower())
        self._id_column = id_column
        if meta.get("primary_key"):
            self._id_column = meta["primary_key"][0]

    def find_by_id(self, id: ID) -> Optional[T]:
        """Найти сущность по ID."""
        sql = f'SELECT * FROM "{self._table_name}" WHERE "{self._id_column}" = :id'
        rows = self._adapter.query(sql, {"id": id})
        if not rows:
            return None
        return self._mapper.row_to_entity(rows[0], self._schema_class)

    def insert(self, entity: T) -> T:
        """Вставить сущность. Для auto-increment id вызывающий код может refetch."""
        row = self._mapper.entity_to_row(entity)
        cols = ", ".join(f'"{k}"' for k in row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        sql = f'INSERT INTO "{self._table_name}" ({cols}) VALUES ({placeholders})'
        self._adapter.execute(sql, row)
        return self._schema_class.model_validate(row)

    def update(self, id: ID, entity: T) -> T:
        """Обновить сущность по ID."""
        row = self._mapper.entity_to_row(entity)
        set_clause = ", ".join(f'"{k}" = :{k}' for k in row.keys() if k != self._id_column)
        sql = f'UPDATE "{self._table_name}" SET {set_clause} WHERE "{self._id_column}" = :id'
        params = {k: v for k, v in row.items() if k != self._id_column}
        params["id"] = id
        self._adapter.execute(sql, params)
        row[self._id_column] = id
        return self._schema_class.model_validate(row)

    def delete(self, id: ID) -> bool:
        """Удалить сущность по ID."""
        sql = f'DELETE FROM "{self._table_name}" WHERE "{self._id_column}" = :id'
        count = self._adapter.execute(sql, {"id": id})
        return count > 0


def _default_mapper() -> ISchemaMapper:
    from sql_module.adapters.schema_mapper import SchemaBaseMapper

    return SchemaBaseMapper()
