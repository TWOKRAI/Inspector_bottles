# -*- coding: utf-8 -*-
"""
GenericRepository — CRUD репозиторий по схеме.

Зависит от ISyncEngineAdapter и ISchemaMapper.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from Services.sql.interfaces import ISchemaMapper, ISyncEngineAdapter

T = TypeVar("T")
ID = TypeVar("ID", int, str)


class GenericRepository:
    """Generic репозиторий: find_by_id, insert, update, delete, insert_many, update_many, find_by."""

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
        self._meta = meta
        self._table_name = table_name or meta.get("table_name", schema_class.__name__.lower())
        self._id_column = id_column
        if meta.get("primary_key"):
            self._id_column = meta["primary_key"][0]
        self._readonly_fields = {
            name for name, col in self._meta.get("columns", {}).items()
            if col.get("readonly")
        }

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
        """Обновить сущность по ID. Readonly поля пропускаются."""
        row = self._mapper.entity_to_row(entity)
        pk_name = self._id_column
        row = {k: v for k, v in row.items() if k not in self._readonly_fields}
        if not row or (len(row) == 1 and pk_name in row):
            raise ValueError("All non-key fields are readonly, cannot update")
        set_clause = ", ".join(f'"{k}" = :{k}' for k in row.keys() if k != pk_name)
        sql = f'UPDATE "{self._table_name}" SET {set_clause} WHERE "{pk_name}" = :id'
        params = {k: v for k, v in row.items() if k != pk_name}
        params["id"] = id
        self._adapter.execute(sql, params)
        row[pk_name] = id
        return self._schema_class.model_validate(row)

    def delete(self, id: ID) -> bool:
        """Удалить сущность по ID."""
        sql = f'DELETE FROM "{self._table_name}" WHERE "{self._id_column}" = :id'
        count = self._adapter.execute(sql, {"id": id})
        return count > 0

    def insert_many(self, entities: List[T]) -> List[T]:
        """Вставить список сущностей (batch). Возвращает список вставленных."""
        if not entities:
            return []
        rows = [self._mapper.entity_to_row(e) for e in entities]
        cols = list(rows[0].keys())
        col_sql = ", ".join(f'"{c}"' for c in cols)
        results = []
        for i, row in enumerate(rows):
            params = {f"_{c}_{i}": row[c] for c in cols}
            placeholders = ", ".join(f":_{c}_{i}" for c in cols)
            sql = f'INSERT INTO "{self._table_name}" ({col_sql}) VALUES ({placeholders})'
            self._adapter.execute(sql, params)
            results.append(self._schema_class.model_validate(row))
        return results

    def update_many(self, updates: List[Tuple[Any, T]]) -> int:
        """Обновить список сущностей. updates — список (id, entity).
        Возвращает количество обновлённых записей."""
        count = 0
        for id_val, entity in updates:
            self.update(id_val, entity)
            count += 1
        return count

    def find_by(self, **kwargs: Any) -> List[T]:
        """Найти сущности по произвольным условиям (AND). Без аргументов — все записи."""
        if not kwargs:
            sql = f'SELECT * FROM "{self._table_name}"'
            rows = self._adapter.query(sql)
            return [self._mapper.row_to_entity(r, self._schema_class) for r in rows]

        conditions = []
        params: Dict[str, Any] = {}
        for i, (col, val) in enumerate(kwargs.items()):
            param_name = f"_fb{i}"
            conditions.append(f'"{col}" = :{param_name}')
            params[param_name] = val

        sql = f'SELECT * FROM "{self._table_name}" WHERE {" AND ".join(conditions)}'
        rows = self._adapter.query(sql, params)
        return [self._mapper.row_to_entity(r, self._schema_class) for r in rows]


def _default_mapper() -> ISchemaMapper:
    from Services.sql.adapters.schema_mapper import SchemaBaseMapper

    return SchemaBaseMapper()
