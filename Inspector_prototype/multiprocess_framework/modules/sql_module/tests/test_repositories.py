"""Тесты GenericRepository."""
import pytest
from pydantic import BaseModel

from sql_module import SQLManager, SQLManagerConfig


class UserSchema(BaseModel):
    id: int | None = None
    name: str


class TestGenericRepository:
    def test_insert_find_delete(self, sql_manager):
        sql_manager.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
        )
        repo = sql_manager.get_repository(UserSchema, table_name="users")
        user = UserSchema(name="Alice")
        inserted = repo.insert(user)
        assert inserted.name == "Alice"
        found = repo.find_by_id(1)
        assert found is not None
        assert found.name == "Alice"
        assert repo.delete(1)
        assert repo.find_by_id(1) is None
