"""Тесты GenericRepository."""

import pytest
from typing import Annotated, Optional
from pydantic import BaseModel

from multiprocess_framework.modules.data_schema_module import SchemaBase, FieldMeta


class UserSchema(BaseModel):
    id: int | None = None
    name: str


# Схема с readonly-полем для Task 7.5
class ReadonlySchema(SchemaBase):
    class SQLMeta:
        table_name = "readonly_test"

    id: Optional[int] = None
    name: str = ""
    locked: Annotated[str, FieldMeta("Locked field", readonly=True)] = "fixed"


# Схема с age для find_by multi-field
class PersonSchema(SchemaBase):
    class SQLMeta:
        table_name = "persons"

    id: Optional[int] = None
    name: str = ""
    age: int = 0


class TestGenericRepository:
    def test_insert_find_delete(self, sql_manager):
        sql_manager.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        repo = sql_manager.get_repository(UserSchema, table_name="users")
        user = UserSchema(name="Alice")
        inserted = repo.insert(user)
        assert inserted.name == "Alice"
        found = repo.find_by_id(1)
        assert found is not None
        assert found.name == "Alice"
        assert repo.delete(1)
        assert repo.find_by_id(1) is None


class TestReadonlyAndBulkRepository:
    """Task 7.5 — тесты readonly, insert_many, find_by."""

    @pytest.fixture
    def readonly_repo(self, sql_manager):
        """Репозиторий с readonly-полем, таблица создана через create_tables."""
        sql_manager.create_tables([ReadonlySchema])
        repo = sql_manager.get_repository(ReadonlySchema)
        yield repo

    @pytest.fixture
    def person_repo(self, sql_manager):
        """Репозиторий PersonSchema."""
        sql_manager.create_tables([PersonSchema])
        repo = sql_manager.get_repository(PersonSchema)
        yield repo

    def test_update_skips_readonly_fields(self, sql_manager, readonly_repo):
        """Обновление записи не изменяет readonly-поле."""
        record = ReadonlySchema(name="Initial", locked="original")
        readonly_repo.insert(record)

        # Попытка обновить поле locked через update
        updated_entity = ReadonlySchema(id=1, name="Updated", locked="changed")
        readonly_repo.update(1, updated_entity)

        # Перечитываем из БД напрямую через SQL
        rows = sql_manager.query('SELECT * FROM "readonly_test" WHERE "id" = 1')
        assert len(rows) == 1
        # locked не должен измениться
        assert rows[0]["locked"] == "original"
        # name должен измениться
        assert rows[0]["name"] == "Updated"

    def test_insert_many(self, readonly_repo):
        """insert_many вставляет все переданные записи."""
        entities = [
            ReadonlySchema(name="Alice", locked="fixed"),
            ReadonlySchema(name="Bob", locked="fixed"),
            ReadonlySchema(name="Carol", locked="fixed"),
        ]
        results = readonly_repo.insert_many(entities)
        assert len(results) == 3
        assert {r.name for r in results} == {"Alice", "Bob", "Carol"}

    def test_insert_many_empty(self, readonly_repo):
        """insert_many с пустым списком возвращает пустой список."""
        results = readonly_repo.insert_many([])
        assert results == []

    def test_find_by_single_field(self, person_repo):
        """find_by(name='Alice') находит нужную запись."""
        person_repo.insert_many(
            [
                PersonSchema(name="Alice", age=30),
                PersonSchema(name="Bob", age=25),
            ]
        )
        found = person_repo.find_by(name="Alice")
        assert len(found) == 1
        assert found[0].name == "Alice"

    def test_find_by_multiple_fields(self, person_repo):
        """find_by(name='Alice', age=25) применяет AND-логику."""
        person_repo.insert_many(
            [
                PersonSchema(name="Alice", age=25),
                PersonSchema(name="Alice", age=30),
                PersonSchema(name="Bob", age=25),
            ]
        )
        found = person_repo.find_by(name="Alice", age=25)
        assert len(found) == 1
        assert found[0].name == "Alice"
        assert found[0].age == 25

    def test_find_by_no_results(self, person_repo):
        """find_by с несуществующим значением возвращает пустой список."""
        person_repo.insert(PersonSchema(name="Alice", age=30))
        found = person_repo.find_by(name="Nonexistent")
        assert found == []

    def test_find_by_no_kwargs(self, person_repo):
        """find_by() без аргументов возвращает все записи."""
        person_repo.insert_many(
            [
                PersonSchema(name="Alice", age=30),
                PersonSchema(name="Bob", age=25),
            ]
        )
        found = person_repo.find_by()
        assert len(found) == 2
