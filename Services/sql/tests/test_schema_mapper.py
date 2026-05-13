# -*- coding: utf-8 -*-
"""
Тесты SchemaBaseMapper и extract_sql_meta.

Task 7.2 — Tests for SQLMeta + enhanced mapper.
"""

import sys
import os

# Ensure modules root is on sys.path (conftest does this too, but keep explicit for clarity)
_modules_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if os.path.abspath(_modules_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_modules_dir))

from typing import Annotated, Optional  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import String  # noqa: E402

from multiprocess_framework.modules.data_schema_module import SchemaBase, FieldMeta  # noqa: E402
from Services.sql.adapters.sql_meta import extract_sql_meta  # noqa: E402
from Services.sql.adapters.schema_mapper import SchemaBaseMapper  # noqa: E402


# ---------------------------------------------------------------------------
# Тестовые схемы
# ---------------------------------------------------------------------------


class SimpleSchema(SchemaBase):
    """Без SQLMeta и без FieldMeta — минимальная схема."""

    id: Optional[int] = None
    name: str = ""


class FullSchema(SchemaBase):
    """Полная схема: SQLMeta + FieldMeta-аннотации."""

    class SQLMeta:
        table_name = "full_items"
        indexes = [("email",), ("name", "age")]
        unique_together = [("email",)]

    id: Optional[int] = None
    name: Annotated[str, FieldMeta("Имя", max=100)] = ""
    email: Annotated[str, FieldMeta("Email", max=255)] = ""
    age: Annotated[int, FieldMeta("Возраст", min=0, max=150)] = 0
    score: Annotated[float, FieldMeta("Рейтинг", min=0.0, max=10.0)] = 0.0
    readonly_field: Annotated[str, FieldMeta("Только чтение", readonly=True)] = "fixed"


# ---------------------------------------------------------------------------
# Тесты extract_sql_meta
# ---------------------------------------------------------------------------


class TestExtractSQLMeta:
    def test_extract_sql_meta_with_class(self):
        """FullSchema: table_name из SQLMeta, indexes, unique_together."""
        meta = extract_sql_meta(FullSchema)
        assert meta["table_name"] == "full_items"
        assert ("email",) in meta["indexes"]
        assert ("name", "age") in meta["indexes"]
        assert ("email",) in meta["unique_together"]

    def test_extract_sql_meta_without_class(self):
        """SimpleSchema: table_name выводится из имени класса, списки пустые."""
        meta = extract_sql_meta(SimpleSchema)
        # "Simple" (stripped Schema) → lowercase + s → "simples"
        assert meta["table_name"] == "simples"
        assert meta["indexes"] == []
        assert meta["unique_together"] == []


# ---------------------------------------------------------------------------
# Тесты SchemaBaseMapper
# ---------------------------------------------------------------------------


class TestSchemaBaseMapper:
    @pytest.fixture(autouse=True)
    def mapper(self):
        self.mapper = SchemaBaseMapper()

    def test_mapper_check_constraints(self):
        """Числовое поле с min/max → check_min/check_max в метаданных колонки."""
        meta = self.mapper.schema_to_table_meta(FullSchema)
        age_col = meta["columns"]["age"]
        assert age_col["check_min"] == 0
        assert age_col["check_max"] == 150

        score_col = meta["columns"]["score"]
        assert score_col["check_min"] == 0.0
        assert score_col["check_max"] == 10.0

    def test_mapper_varchar(self):
        """Строковое поле с FieldMeta(max=100) → String с длиной."""
        meta = self.mapper.schema_to_table_meta(FullSchema)
        name_col = meta["columns"]["name"]
        # type должен быть String с length
        col_type = name_col["type"]
        assert isinstance(col_type, String)
        assert col_type.length == 100

        email_col = meta["columns"]["email"]
        assert isinstance(email_col["type"], String)
        assert email_col["type"].length == 255

    def test_mapper_readonly(self):
        """FieldMeta(readonly=True) → 'readonly': True в метаданных колонки."""
        meta = self.mapper.schema_to_table_meta(FullSchema)
        col = meta["columns"]["readonly_field"]
        assert col["readonly"] is True

    def test_mapper_default_value(self):
        """Поле с default → 'default' присутствует в метаданных колонки."""
        meta = self.mapper.schema_to_table_meta(FullSchema)
        # name имеет default=""
        _name_col = meta["columns"]["name"]
        # default "" — falsy, поэтому mapper хранит его только если not None and not PydanticUndefined
        # По реализации: пустая строка "" не является None → default не попадает (условие: != None)
        # Проверяем поле readonly_field с непустым дефолтом
        rf_col = meta["columns"]["readonly_field"]
        assert rf_col["default"] == "fixed"

    def test_mapper_nullable_optional(self):
        """Optional[int] → nullable: True."""
        meta = self.mapper.schema_to_table_meta(FullSchema)
        id_col = meta["columns"]["id"]
        assert id_col["nullable"] is True

    def test_mapper_backward_compatible(self):
        """Ключи table_name, columns, primary_key по-прежнему присутствуют в результате."""
        meta = self.mapper.schema_to_table_meta(FullSchema)
        assert "table_name" in meta
        assert "columns" in meta
        assert "primary_key" in meta
        # table_name корректен
        assert meta["table_name"] == "full_items"
        # id — primary_key
        assert "id" in meta["primary_key"]
        # columns содержит все поля схемы
        for field in ("id", "name", "email", "age", "score", "readonly_field"):
            assert field in meta["columns"]
