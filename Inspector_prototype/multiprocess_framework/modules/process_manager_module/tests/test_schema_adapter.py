"""
Тесты ProcessSchemaAdapter.

Проверяют adapt, adapt_instance, adapt_many, build_process_entry,
_extract_dict фильтрацию и _flatten_dict.
"""

import pytest
from typing import Any, Dict

from ..adapters.schema_adapter import ProcessSchemaAdapter


# ---------------------------------------------------------------------------
# Вспомогательные схемы для тестов
# ---------------------------------------------------------------------------

class SimpleSchema:
    """Простая схема без build()."""
    timeout: float = 5.0
    workers: int = 4
    name: str = "test"

    def __init__(self):
        self.timeout = 5.0
        self.workers = 4
        self.name = "test"


class SchemaWithBuild:
    """Схема с методом build()."""

    def build(self):
        return "MyProcess", {"class": "my.Process", "timeout": 10.0}


class SchemaWithModelDump:
    """Схема с model_dump() (Pydantic-like)."""

    def model_dump(self) -> Dict[str, Any]:
        return {"field1": "value1", "field2": 42, "_private": "hidden"}


class SchemaWithSchemaName:
    """Схема с явным __schema_name__."""
    __schema_name__ = "CustomName"

    def __init__(self):
        self.value = 1


class WorkerConfig:
    def __init__(self):
        self.threads = 2
        self.timeout = 3.0


class ProcessConfig:
    def __init__(self):
        self.class_ = "my.Process"
        self.priority = "normal"


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestProcessSchemaAdapterAdapt:
    """Тесты метода adapt()."""

    def test_adapt_simple_class(self) -> None:
        adapter = ProcessSchemaAdapter()
        result = adapter.adapt(SimpleSchema)
        assert isinstance(result, dict)
        assert result["timeout"] == 5.0
        assert result["workers"] == 4

    def test_adapt_returns_empty_on_bad_class(self) -> None:
        adapter = ProcessSchemaAdapter()

        class BadSchema:
            def __init__(self):
                raise ValueError("cannot instantiate")

        result = adapter.adapt(BadSchema)
        assert result == {}

    def test_adapt_with_include_fields(self) -> None:
        adapter = ProcessSchemaAdapter()
        result = adapter.adapt(SimpleSchema, include_fields=["timeout"])
        assert "timeout" in result
        assert "workers" not in result

    def test_adapt_with_exclude_fields(self) -> None:
        adapter = ProcessSchemaAdapter()
        result = adapter.adapt(SimpleSchema, exclude_fields=["name"])
        assert "name" not in result
        assert "timeout" in result


class TestProcessSchemaAdapterAdaptInstance:
    """Тесты метода adapt_instance()."""

    def test_adapt_instance_uses_build_if_available(self) -> None:
        adapter = ProcessSchemaAdapter()
        schema = SchemaWithBuild()
        name, config = adapter.adapt_instance(schema)
        assert name == "MyProcess"
        assert config["class"] == "my.Process"

    def test_adapt_instance_without_build(self) -> None:
        adapter = ProcessSchemaAdapter()
        schema = SimpleSchema()
        name, config = adapter.adapt_instance(schema)
        assert isinstance(name, str)
        assert isinstance(config, dict)
        assert "timeout" in config

    def test_adapt_instance_name_strips_config_suffix(self) -> None:
        adapter = ProcessSchemaAdapter()

        class WorkerConfig:
            def __init__(self):
                self.threads = 2

        schema = WorkerConfig()
        name, _ = adapter.adapt_instance(schema)
        assert name == "Worker"

    def test_adapt_instance_uses_schema_name_attribute(self) -> None:
        adapter = ProcessSchemaAdapter()
        schema = SchemaWithSchemaName()
        name, _ = adapter.adapt_instance(schema)
        assert name == "CustomName"


class TestProcessSchemaAdapterAdaptMany:
    """Тесты метода adapt_many()."""

    def test_adapt_many_returns_list(self) -> None:
        adapter = ProcessSchemaAdapter()
        results = adapter.adapt_many(SimpleSchema(), WorkerConfig())
        assert isinstance(results, list)
        assert len(results) == 2

    def test_adapt_many_each_is_tuple(self) -> None:
        adapter = ProcessSchemaAdapter()
        results = adapter.adapt_many(SimpleSchema())
        assert len(results) == 1
        name, config = results[0]
        assert isinstance(name, str)
        assert isinstance(config, dict)


class TestProcessSchemaAdapterBuildProcessEntry:
    """Тесты метода build_process_entry()."""

    def test_build_process_entry_no_workers(self) -> None:
        adapter = ProcessSchemaAdapter()
        schema = SchemaWithBuild()
        name, config = adapter.build_process_entry(schema)
        assert name == "MyProcess"
        assert "workers" not in config

    def test_build_process_entry_with_workers(self) -> None:
        adapter = ProcessSchemaAdapter()
        process_schema = SchemaWithBuild()
        worker_schema = WorkerConfig()
        name, config = adapter.build_process_entry(process_schema, worker_schema)
        assert "workers" in config
        assert len(config["workers"]) == 1

    def test_build_process_entry_multiple_workers(self) -> None:
        adapter = ProcessSchemaAdapter()
        process_schema = SchemaWithBuild()
        name, config = adapter.build_process_entry(
            process_schema, WorkerConfig(), WorkerConfig()
        )
        assert len(config["workers"]) == 2


class TestExtractDict:
    """Тесты метода _extract_dict()."""

    def test_extract_dict_uses_model_dump(self) -> None:
        adapter = ProcessSchemaAdapter()
        schema = SchemaWithModelDump()
        result = adapter._extract_dict(schema)
        assert "field1" in result
        assert "field2" in result

    def test_extract_dict_uses_dict_fallback(self) -> None:
        adapter = ProcessSchemaAdapter()
        schema = SimpleSchema()
        result = adapter._extract_dict(schema)
        assert "timeout" in result
        assert "workers" in result

    def test_extract_dict_filters_private_from_dict(self) -> None:
        adapter = ProcessSchemaAdapter()

        class WithPrivate:
            def __init__(self):
                self.public = 1
                self._private = 2

        result = adapter._extract_dict(WithPrivate())
        assert "public" in result
        assert "_private" not in result

    def test_extract_dict_returns_empty_for_unknown(self) -> None:
        adapter = ProcessSchemaAdapter()
        result = adapter._extract_dict(42)  # type: ignore
        assert result == {}


class TestFlattenDict:
    """Тесты метода _flatten_dict()."""

    def test_flatten_simple(self) -> None:
        adapter = ProcessSchemaAdapter()
        data = {"a": 1, "b": 2}
        result = adapter._flatten_dict(data)
        assert result == {"a": 1, "b": 2}

    def test_flatten_nested(self) -> None:
        adapter = ProcessSchemaAdapter()
        data = {"a": {"b": 1, "c": 2}}
        result = adapter._flatten_dict(data)
        assert "a_b" in result
        assert "a_c" in result
        assert result["a_b"] == 1

    def test_flatten_deep_nested(self) -> None:
        adapter = ProcessSchemaAdapter()
        data = {"x": {"y": {"z": 42}}}
        result = adapter._flatten_dict(data)
        assert "x_y_z" in result
        assert result["x_y_z"] == 42

    def test_flatten_with_adapt(self) -> None:
        adapter = ProcessSchemaAdapter()

        class NestedSchema:
            def __init__(self):
                self.config = {"timeout": 5, "retries": 3}

        result = adapter._extract_dict(NestedSchema(), flatten=True)
        assert "config_timeout" in result
        assert "config_retries" in result
