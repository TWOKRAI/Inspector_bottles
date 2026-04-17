# -*- coding: utf-8 -*-
"""Tests for DDLBuilder -- DDL generation from schema metadata."""
import pytest

from sqlalchemy import Integer, String, Float, Boolean, DateTime, Date

from sql_module.core.ddl_builder import DDLBuilder


# ---------------------------------------------------------------------------
# Fake mapper: returns pre-built metadata dicts
# ---------------------------------------------------------------------------

class FakeMapper:
    """Mimics SchemaBaseMapper.schema_to_table_meta() for testing."""

    def __init__(self, meta: dict):
        self._meta = meta

    def schema_to_table_meta(self, schema_class):
        return self._meta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _basic_meta():
    """Minimal table with id, name, score."""
    return {
        "table_name": "users",
        "columns": {
            "id": {
                "type": Integer,
                "nullable": False,
                "check_min": None,
                "check_max": None,
                "default": None,
                "readonly": False,
            },
            "name": {
                "type": String(100),
                "nullable": False,
                "check_min": None,
                "check_max": None,
                "default": "",
                "readonly": False,
            },
            "age": {
                "type": Integer,
                "nullable": False,
                "check_min": 0,
                "check_max": 150,
                "default": 0,
                "readonly": False,
            },
            "score": {
                "type": Float,
                "nullable": True,
                "check_min": None,
                "check_max": None,
                "default": 0.0,
                "readonly": False,
            },
        },
        "primary_key": ["id"],
        "indexes": [("name",), ("age", "score")],
        "unique_together": [("name",)],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDDLBuilderSQLite:
    """SQLite dialect tests."""

    def test_create_table_basic(self):
        mapper = FakeMapper(_basic_meta())
        builder = DDLBuilder(mapper)
        stmts = builder.build_create_table(object, dialect="sqlite")

        create = stmts[0]
        assert 'CREATE TABLE IF NOT EXISTS "users"' in create
        assert '"id" INTEGER PRIMARY KEY AUTOINCREMENT' in create
        assert "VARCHAR(100)" in create
        assert "NOT NULL" in create
        assert "DEFAULT ''" in create
        assert 'CHECK ("age" >= 0 AND "age" <= 150)' in create
        assert "DEFAULT 0.0" in create
        assert 'UNIQUE ("name")' in create

    def test_create_index(self):
        mapper = FakeMapper(_basic_meta())
        builder = DDLBuilder(mapper)
        stmts = builder.build_create_table(object, dialect="sqlite")

        # Should have CREATE TABLE + 2 indexes = 3 statements
        assert len(stmts) == 3
        assert 'CREATE INDEX IF NOT EXISTS "ix_users_name"' in stmts[1]
        assert 'CREATE INDEX IF NOT EXISTS "ix_users_age_score"' in stmts[2]
        assert 'ON "users"' in stmts[1]

    def test_boolean_default_sqlite(self):
        meta = {
            "table_name": "flags",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
                "active": {
                    "type": Boolean,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": True,
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="sqlite")[0]
        assert "DEFAULT 1" in create
        assert "INTEGER" in create  # Boolean -> INTEGER in SQLite

    def test_string_no_length(self):
        meta = {
            "table_name": "notes",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
                "body": {
                    "type": String,
                    "nullable": True,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="sqlite")[0]
        assert '"body" TEXT' in create


class TestDDLBuilderPostgreSQL:
    """PostgreSQL dialect tests."""

    def test_auto_pk_serial(self):
        meta = _basic_meta()
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="postgresql")[0]
        assert '"id" SERIAL PRIMARY KEY' in create

    def test_boolean_default_pg(self):
        meta = {
            "table_name": "flags",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
                "active": {
                    "type": Boolean,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": False,
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="postgresql")[0]
        assert "DEFAULT FALSE" in create
        assert "BOOLEAN" in create

    def test_float_type(self):
        meta = _basic_meta()
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="postgresql")[0]
        assert "DOUBLE PRECISION" in create


class TestDDLBuilderMySQL:
    """MySQL dialect tests."""

    def test_auto_pk_auto_increment(self):
        meta = _basic_meta()
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="mysql")[0]
        assert '"id" INTEGER AUTO_INCREMENT PRIMARY KEY' in create

    def test_boolean_mysql(self):
        meta = {
            "table_name": "flags",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
                "active": {
                    "type": Boolean,
                    "nullable": True,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object, dialect="mysql")[0]
        assert "TINYINT(1)" in create


class TestDDLBuilderEdgeCases:
    """Edge cases and validation."""

    def test_unsupported_dialect_raises(self):
        builder = DDLBuilder(FakeMapper(_basic_meta()))
        with pytest.raises(ValueError, match="Unsupported dialect"):
            builder.build_create_table(object, dialect="oracle")

    def test_build_create_all(self):
        meta = _basic_meta()
        builder = DDLBuilder(FakeMapper(meta))
        stmts = builder.build_create_all([object, object], dialect="sqlite")
        # 2 tables x (1 CREATE TABLE + 2 indexes) = 6
        assert len(stmts) == 6

    def test_check_min_only(self):
        meta = {
            "table_name": "items",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
                "price": {
                    "type": Float,
                    "nullable": False,
                    "check_min": 0,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object)[0]
        assert 'CHECK ("price" >= 0)' in create
        assert "AND" not in create.split("CHECK")[1]

    def test_string_default_escapes_quotes(self):
        meta = {
            "table_name": "msgs",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
                "text": {
                    "type": String,
                    "nullable": True,
                    "check_min": None,
                    "check_max": None,
                    "default": "it's a test",
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        create = builder.build_create_table(object)[0]
        assert "DEFAULT 'it''s a test'" in create

    def test_no_indexes_no_unique(self):
        meta = {
            "table_name": "simple",
            "columns": {
                "id": {
                    "type": Integer,
                    "nullable": False,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                },
            },
            "primary_key": ["id"],
            "indexes": [],
            "unique_together": [],
        }
        builder = DDLBuilder(FakeMapper(meta))
        stmts = builder.build_create_table(object)
        assert len(stmts) == 1  # Only CREATE TABLE, no indexes
