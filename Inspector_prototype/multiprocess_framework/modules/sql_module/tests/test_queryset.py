# -*- coding: utf-8 -*-
"""Tests for QuerySet builder.

Uses mock adapter/mapper to test SQL generation and immutability.
"""
import pytest
from typing import Any, Dict, List, Optional, Type

from sql_module.core.queryset import QuerySet


# =============================================================================
# Fakes / Mocks
# =============================================================================


class FakeSchema:
    """Minimal schema stand-in for tests."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeMapper:
    """Mapper that wraps dicts in FakeSchema."""

    def row_to_entity(self, row: Dict[str, Any], schema_class: Type) -> Any:
        return schema_class(**row)


class FakeAdapter:
    """Adapter that records calls and returns configurable results."""

    def __init__(
        self,
        query_result: Optional[List[Dict[str, Any]]] = None,
        execute_result: int = 0,
    ) -> None:
        self.query_result = query_result or []
        self.execute_result = execute_result
        self.last_sql: Optional[str] = None
        self.last_params: Optional[Dict[str, Any]] = None
        self.call_count = 0

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self.last_sql = sql
        self.last_params = params
        self.call_count += 1
        return self.query_result

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        self.last_sql = sql
        self.last_params = params
        self.call_count += 1
        return self.execute_result


def _make_qs(
    adapter: Optional[FakeAdapter] = None,
    table: str = "users",
) -> QuerySet:
    """Helper to create a QuerySet with defaults."""
    return QuerySet(
        adapter=adapter or FakeAdapter(),
        schema_class=FakeSchema,
        schema_mapper=FakeMapper(),
        table_name=table,
    )


# =============================================================================
# Immutability
# =============================================================================


class TestImmutability:
    """filter/exclude/order_by/limit/offset must return new QuerySet, not mutate."""

    def test_filter_returns_new_instance(self):
        qs = _make_qs()
        qs2 = qs.filter(name="Alice")
        assert qs2 is not qs
        assert len(qs._filters) == 0
        assert len(qs2._filters) == 1

    def test_exclude_returns_new_instance(self):
        qs = _make_qs()
        qs2 = qs.exclude(role="admin")
        assert qs2 is not qs
        assert len(qs._excludes) == 0

    def test_order_by_returns_new_instance(self):
        qs = _make_qs()
        qs2 = qs.order_by("-score")
        assert qs2 is not qs
        assert qs._order_fields == []

    def test_limit_returns_new_instance(self):
        qs = _make_qs()
        qs2 = qs.limit(10)
        assert qs2 is not qs
        assert qs._limit_val is None

    def test_offset_returns_new_instance(self):
        qs = _make_qs()
        qs2 = qs.offset(5)
        assert qs2 is not qs
        assert qs._offset_val is None


# =============================================================================
# SQL generation — _parse_lookup
# =============================================================================


class TestParseLookup:

    def test_plain_field(self):
        qs = _make_qs()
        assert qs._parse_lookup("name") == ("name", "eq")

    def test_eq_lookup(self):
        qs = _make_qs()
        assert qs._parse_lookup("name__eq") == ("name", "eq")

    def test_gte_lookup(self):
        qs = _make_qs()
        assert qs._parse_lookup("age__gte") == ("age", "gte")

    def test_in_lookup(self):
        qs = _make_qs()
        assert qs._parse_lookup("status__in") == ("status", "in")

    def test_unknown_suffix_treated_as_field(self):
        """field__unknown => field name is 'field__unknown', op is 'eq'."""
        qs = _make_qs()
        assert qs._parse_lookup("field__unknown") == ("field__unknown", "eq")

    def test_isnull_lookup(self):
        qs = _make_qs()
        assert qs._parse_lookup("email__isnull") == ("email", "isnull")


# =============================================================================
# SQL generation — _build_select
# =============================================================================


class TestBuildSelect:

    def test_no_filters(self):
        qs = _make_qs(table="products")
        sql, params = qs._build_select()
        assert sql == 'SELECT * FROM "products"'
        assert params == {}

    def test_single_eq_filter(self):
        qs = _make_qs().filter(name="Alice")
        sql, params = qs._build_select()
        assert '"name" =' in sql
        assert "WHERE" in sql
        assert len(params) == 1
        assert list(params.values())[0] == "Alice"

    def test_multiple_filters(self):
        qs = _make_qs().filter(age__gte=18, role="user")
        sql, params = qs._build_select()
        assert "AND" in sql
        assert len(params) == 2

    def test_order_by_asc(self):
        qs = _make_qs().order_by("name")
        sql, _ = qs._build_select()
        assert '"name" ASC' in sql

    def test_order_by_desc(self):
        qs = _make_qs().order_by("-score")
        sql, _ = qs._build_select()
        assert '"score" DESC' in sql

    def test_limit_and_offset(self):
        qs = _make_qs().limit(10).offset(20)
        sql, _ = qs._build_select()
        assert "LIMIT 10" in sql
        assert "OFFSET 20" in sql

    def test_chained_complex(self):
        qs = (
            _make_qs()
            .filter(age__gte=18)
            .exclude(role="admin")
            .order_by("-score", "name")
            .limit(5)
            .offset(10)
        )
        sql, params = qs._build_select()
        assert "WHERE" in sql
        assert "NOT" in sql
        assert "ORDER BY" in sql
        assert '"score" DESC' in sql
        assert '"name" ASC' in sql
        assert "LIMIT 5" in sql
        assert "OFFSET 10" in sql


# =============================================================================
# SQL generation — operators
# =============================================================================


class TestOperators:

    def test_ne(self):
        qs = _make_qs().filter(status__ne="deleted")
        sql, params = qs._build_select()
        assert '"status" !=' in sql

    def test_gt(self):
        qs = _make_qs().filter(score__gt=90)
        sql, _ = qs._build_select()
        assert '"score" >' in sql

    def test_lt(self):
        qs = _make_qs().filter(score__lt=50)
        sql, _ = qs._build_select()
        assert '"score" <' in sql

    def test_lte(self):
        qs = _make_qs().filter(score__lte=100)
        sql, _ = qs._build_select()
        assert '"score" <=' in sql

    def test_like(self):
        qs = _make_qs().filter(name__like="%Alice%")
        sql, params = qs._build_select()
        assert '"name" LIKE' in sql
        assert "%Alice%" in params.values()

    def test_isnull_true(self):
        qs = _make_qs().filter(email__isnull=True)
        sql, params = qs._build_select()
        assert '"email" IS NULL' in sql
        assert len(params) == 0

    def test_isnull_false(self):
        qs = _make_qs().filter(email__isnull=False)
        sql, params = qs._build_select()
        assert '"email" IS NOT NULL' in sql

    def test_in_operator(self):
        qs = _make_qs().filter(role__in=["admin", "mod"])
        sql, params = qs._build_select()
        assert '"role" IN' in sql
        assert len(params) == 2
        assert set(params.values()) == {"admin", "mod"}

    def test_in_empty_list(self):
        qs = _make_qs().filter(role__in=[])
        sql, params = qs._build_select()
        assert "1=0" in sql
        assert len(params) == 0


# =============================================================================
# SQL generation — exclude (NOT)
# =============================================================================


class TestExclude:

    def test_exclude_generates_not(self):
        qs = _make_qs().exclude(role="admin")
        sql, params = qs._build_select()
        assert "NOT" in sql
        assert '"role" =' in sql


# =============================================================================
# SQL generation — count, delete, update
# =============================================================================


class TestBuildCount:

    def test_count_no_filter(self):
        qs = _make_qs(table="items")
        sql, params = qs._build_count()
        assert sql == 'SELECT COUNT(*) as count FROM "items"'
        assert params == {}

    def test_count_with_filter(self):
        qs = _make_qs().filter(active=True)
        sql, params = qs._build_count()
        assert "WHERE" in sql
        assert "COUNT(*)" in sql


class TestBuildDelete:

    def test_delete_no_filter(self):
        qs = _make_qs(table="logs")
        sql, params = qs._build_delete()
        assert sql == 'DELETE FROM "logs"'

    def test_delete_with_filter(self):
        qs = _make_qs().filter(status="old")
        sql, params = qs._build_delete()
        assert "DELETE" in sql
        assert "WHERE" in sql


class TestBuildUpdate:

    def test_update_with_filter(self):
        qs = _make_qs().filter(active=False)
        sql, params = qs._build_update({"status": "archived"})
        assert "UPDATE" in sql
        assert "SET" in sql
        assert '"status" =' in sql
        assert "WHERE" in sql
        assert "archived" in params.values()


# =============================================================================
# Terminal methods — all, first, count, values, delete, update
# =============================================================================


class TestTerminalAll:

    def test_all_returns_entities(self):
        adapter = FakeAdapter(query_result=[{"name": "Alice"}, {"name": "Bob"}])
        qs = _make_qs(adapter=adapter)
        results = qs.all()
        assert len(results) == 2
        assert results[0].name == "Alice"
        assert results[1].name == "Bob"
        assert adapter.call_count == 1


class TestTerminalFirst:

    def test_first_returns_single(self):
        adapter = FakeAdapter(query_result=[{"name": "Alice"}])
        qs = _make_qs(adapter=adapter)
        result = qs.first()
        assert result is not None
        assert result.name == "Alice"
        assert "LIMIT 1" in adapter.last_sql

    def test_first_returns_none_on_empty(self):
        adapter = FakeAdapter(query_result=[])
        qs = _make_qs(adapter=adapter)
        result = qs.first()
        assert result is None


class TestTerminalCount:

    def test_count_returns_int(self):
        adapter = FakeAdapter(query_result=[{"count": 42}])
        qs = _make_qs(adapter=adapter)
        assert qs.count() == 42

    def test_count_returns_zero_on_empty(self):
        adapter = FakeAdapter(query_result=[])
        qs = _make_qs(adapter=adapter)
        assert qs.count() == 0


class TestTerminalValues:

    def test_values_returns_raw_dicts(self):
        rows = [{"id": 1, "name": "Alice"}]
        adapter = FakeAdapter(query_result=rows)
        qs = _make_qs(adapter=adapter)
        result = qs.values()
        assert result == rows


class TestTerminalDelete:

    def test_delete_returns_rowcount(self):
        adapter = FakeAdapter(execute_result=3)
        qs = _make_qs(adapter=adapter).filter(status="old")
        assert qs.delete() == 3
        assert "DELETE" in adapter.last_sql


class TestTerminalUpdate:

    def test_update_returns_rowcount(self):
        adapter = FakeAdapter(execute_result=5)
        qs = _make_qs(adapter=adapter).filter(active=False)
        assert qs.update(status="archived") == 5
        assert "UPDATE" in adapter.last_sql
        assert "SET" in adapter.last_sql


# =============================================================================
# Parameterization safety
# =============================================================================


class TestParameterization:
    """All user values must go through params dict, never inlined in SQL."""

    def test_values_not_in_sql_string(self):
        qs = _make_qs().filter(name="Robert'; DROP TABLE users;--")
        sql, params = qs._build_select()
        assert "Robert" not in sql
        assert "DROP" not in sql
        assert "Robert'; DROP TABLE users;--" in params.values()

    def test_unique_param_names(self):
        qs = _make_qs().filter(a=1, b=2, c=3)
        _, params = qs._build_select()
        assert len(params) == 3
        # All param keys must be unique
        assert len(set(params.keys())) == 3

    def test_identifiers_quoted(self):
        qs = _make_qs().filter(user_name="test")
        sql, _ = qs._build_select()
        assert '"user_name"' in sql
