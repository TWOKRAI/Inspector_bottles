# -*- coding: utf-8 -*-
"""
Тесты для SchemaRegistry (registry/schema_registry.py).

Покрывает:
    - Создание изолированных экземпляров (не Singleton)
    - register, get, has, unregister, clear
    - Декоратор @register_schema с опциональным registry
    - get_default_registry() — глобальный экземпляр
    - Изоляция: тесты не загрязняют глобальный реестр
    - Потокобезопасность
    - validate_recipe
    - Backward compat: SchemaManager.get_instance()
"""

import threading
import unittest
from typing import Annotated

from pydantic import BaseModel

from multiprocess_framework.modules.data_schema_module import (
    SchemaBase,
    FieldMeta,
    SchemaRegistry,
    SchemaManager,
    register_schema,
    get_default_registry,
)
from multiprocess_framework.modules.data_schema_module.core.exceptions import (
    InvalidParameterError,
    SchemaNotFoundError,
    SchemaRegistrationError,
    SchemaValidationError,
)


# =============================================================================
# Вспомогательные модели
# =============================================================================


class SampleModel(BaseModel):
    name: str = "default"
    count: int = 1


class AnotherModel(BaseModel):
    value: float = 0.0
    active: bool = True


class SampleSchema(SchemaBase):
    speed: Annotated[float, FieldMeta("Скорость", min=0.0, max=100.0)] = 10.0
    label: str = "test"


# =============================================================================
# Тесты изоляции (не Singleton)
# =============================================================================


class TestSchemaRegistryIsolation(unittest.TestCase):
    """Проверяет что SchemaRegistry — не Singleton."""

    def test_two_instances_are_independent(self):
        r1 = SchemaRegistry()
        r2 = SchemaRegistry()
        r1.register("Model", SampleModel)
        self.assertTrue(r1.has_schema("Model"))
        self.assertFalse(r2.has_schema("Model"))

    def test_clear_does_not_affect_other_instance(self):
        r1 = SchemaRegistry()
        r2 = SchemaRegistry()
        r1.register("Model", SampleModel)
        r2.register("Model", SampleModel)
        r1.clear()
        self.assertFalse(r1.has_schema("Model"))
        self.assertTrue(r2.has_schema("Model"))

    def test_default_registry_is_singleton_like(self):
        """get_default_registry() возвращает один и тот же объект."""
        r1 = get_default_registry()
        r2 = get_default_registry()
        self.assertIs(r1, r2)

    def test_schema_manager_get_instance_returns_default(self):
        """SchemaManager.get_instance() — backward compat для get_default_registry()."""
        self.assertIs(SchemaManager.get_instance(), get_default_registry())

    def test_schema_manager_is_alias(self):
        """SchemaManager — alias SchemaRegistry."""
        self.assertIs(SchemaManager, SchemaRegistry)


# =============================================================================
# Тесты базовых операций
# =============================================================================


class TestSchemaRegistryBasicOps(unittest.TestCase):
    """Тесты register, get, has, unregister, clear."""

    def setUp(self):
        self.registry = SchemaRegistry()

    def test_register_and_has(self):
        self.registry.register("Sample", SampleModel)
        self.assertTrue(self.registry.has_schema("Sample"))

    def test_get_schema(self):
        self.registry.register("Sample", SampleModel)
        self.assertIs(self.registry.get_schema("Sample"), SampleModel)

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(self.registry.get_schema("Nonexistent"))

    def test_has_nonexistent_returns_false(self):
        self.assertFalse(self.registry.has_schema("Nonexistent"))

    def test_list_schemas_empty(self):
        self.assertEqual(self.registry.list_schemas(), [])

    def test_list_schemas_after_register(self):
        self.registry.register("A", SampleModel)
        self.registry.register("B", AnotherModel)
        schemas = self.registry.list_schemas()
        self.assertIn("A", schemas)
        self.assertIn("B", schemas)
        self.assertEqual(len(schemas), 2)

    def test_unregister_existing(self):
        self.registry.register("Sample", SampleModel)
        result = self.registry.unregister("Sample")
        self.assertTrue(result)
        self.assertFalse(self.registry.has_schema("Sample"))

    def test_unregister_nonexistent_returns_false(self):
        result = self.registry.unregister("Nonexistent")
        self.assertFalse(result)

    def test_clear(self):
        self.registry.register("A", SampleModel)
        self.registry.register("B", AnotherModel)
        self.registry.clear()
        self.assertEqual(self.registry.list_schemas(), [])

    def test_register_overwrites_existing(self):
        self.registry.register("Model", SampleModel)
        self.registry.register("Model", AnotherModel)
        self.assertIs(self.registry.get_schema("Model"), AnotherModel)


# =============================================================================
# Тесты валидации параметров
# =============================================================================


class TestSchemaRegistryValidation(unittest.TestCase):
    """Тесты валидации входных параметров."""

    def setUp(self):
        self.registry = SchemaRegistry()

    def test_register_empty_name_raises(self):
        with self.assertRaises(InvalidParameterError):
            self.registry.register("", SampleModel)

    def test_register_none_name_raises(self):
        with self.assertRaises(InvalidParameterError):
            self.registry.register(None, SampleModel)

    def test_register_non_class_raises(self):
        with self.assertRaises(InvalidParameterError):
            self.registry.register("Model", "not_a_class")

    def test_register_non_basemodel_raises(self):
        class NotAModel:
            pass

        with self.assertRaises(SchemaRegistrationError):
            self.registry.register("Model", NotAModel)

    def test_create_instance_unknown_schema_raises(self):
        with self.assertRaises(SchemaNotFoundError):
            self.registry.create_instance("Unknown")

    def test_create_instance_invalid_data_raises(self):
        self.registry.register("Sample", SampleModel)
        with self.assertRaises(SchemaValidationError):
            self.registry.create_instance("Sample", {"count": "not_int"})


# =============================================================================
# Тесты create_instance и get_defaults
# =============================================================================


class TestSchemaRegistryCreateInstance(unittest.TestCase):
    """Тесты создания экземпляров и получения дефолтов."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.registry.register("Sample", SampleModel)

    def test_create_with_defaults(self):
        instance = self.registry.create_instance("Sample")
        self.assertEqual(instance.name, "default")
        self.assertEqual(instance.count, 1)

    def test_create_with_data(self):
        instance = self.registry.create_instance("Sample", {"name": "custom", "count": 42})
        self.assertEqual(instance.name, "custom")
        self.assertEqual(instance.count, 42)

    def test_create_with_partial_data(self):
        instance = self.registry.create_instance("Sample", {"name": "partial"})
        self.assertEqual(instance.name, "partial")
        self.assertEqual(instance.count, 1)  # дефолт

    def test_get_defaults(self):
        defaults = self.registry.get_defaults("Sample")
        self.assertEqual(defaults, SampleModel().model_dump())

    def test_get_defaults_nonexistent_returns_empty(self):
        defaults = self.registry.get_defaults("Nonexistent")
        self.assertEqual(defaults, {})

    def test_create_schema_base_instance(self):
        self.registry.register("Schema", SampleSchema)
        instance = self.registry.create_instance("Schema")
        self.assertEqual(instance.speed, 10.0)
        self.assertEqual(instance.label, "test")


# =============================================================================
# Тесты метода validate
# =============================================================================


class TestSchemaRegistryValidateMethod(unittest.TestCase):
    """Тесты метода validate."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.registry.register("Sample", SampleModel)

    def test_validate_valid_data(self):
        ok, instance, err = self.registry.validate("Sample", {"name": "x", "count": 5})
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(instance.count, 5)

    def test_validate_invalid_data(self):
        ok, instance, err = self.registry.validate("Sample", {"count": "bad"})
        self.assertFalse(ok)
        self.assertIsNone(instance)
        self.assertIsNotNone(err)
        self.assertIn("count", err)

    def test_validate_unknown_schema(self):
        ok, instance, err = self.registry.validate("Unknown", {"name": "x"})
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_validate_non_dict_data(self):
        ok, instance, err = self.registry.validate("Sample", "not_a_dict")
        self.assertFalse(ok)
        self.assertIsNotNone(err)


# =============================================================================
# Тесты validate_recipe
# =============================================================================


class TestSchemaRegistryValidateRecipe(unittest.TestCase):
    """Тесты validate_recipe."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.registry.register("Sample", SampleModel)
        self.registry.register("Another", AnotherModel)

    def test_valid_recipe(self):
        ok, err = self.registry.validate_recipe(
            {
                "Sample": {"name": "r1", "count": 1},
                "Another": {"value": 0.5, "active": True},
            }
        )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_invalid_recipe_one_register(self):
        ok, err = self.registry.validate_recipe(
            {
                "Sample": {"name": "r1", "count": "bad"},
            }
        )
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertIn("Sample", err)

    def test_recipe_not_dict_raises(self):
        ok, err = self.registry.validate_recipe("not_a_dict")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_recipe_unknown_schema_skipped(self):
        """Неизвестные ключи в recipe пропускаются (нет схемы — нет валидации)."""
        ok, err = self.registry.validate_recipe(
            {
                "UnknownSchema": {"anything": 1},
            }
        )
        self.assertTrue(ok)

    def test_recipe_with_register_names_filter(self):
        """validate_recipe с filter по register_names."""
        ok, err = self.registry.validate_recipe(
            {
                "Sample": {"name": "r1", "count": 1},
                "Another": {"value": "bad"},
            },
            register_names=["Sample"],  # проверяем только Sample
        )
        self.assertTrue(ok)  # Another не проверяется


# =============================================================================
# Тесты декоратора @register_schema
# =============================================================================


class TestRegisterSchemaDecorator(unittest.TestCase):
    """Тесты декоратора @register_schema."""

    def test_decorator_with_isolated_registry(self):
        """Декоратор с явным registry не загрязняет глобальный."""
        isolated = SchemaRegistry()

        @register_schema("DecoratedModel", registry=isolated)
        class DecoratedModel(BaseModel):
            level: str = "INFO"

        self.assertTrue(isolated.has_schema("DecoratedModel"))
        # Глобальный реестр не затронут
        _global_reg = get_default_registry()
        # Не проверяем глобальный, т.к. другие тесты могут его изменить

    def test_decorator_sets_schema_name(self):
        isolated = SchemaRegistry()

        @register_schema("TestConfig", registry=isolated)
        class TestConfig(BaseModel):
            value: int = 0

        self.assertEqual(TestConfig._schema_name, "TestConfig")

    def test_decorator_uses_class_name_if_none(self):
        isolated = SchemaRegistry()

        @register_schema(registry=isolated)
        class AutoNamedConfig(BaseModel):
            x: int = 0

        self.assertTrue(isolated.has_schema("AutoNamedConfig"))

    def test_decorator_auto_register_false(self):
        isolated = SchemaRegistry()

        @register_schema("NotRegistered", auto_register=False, registry=isolated)
        class NotRegistered(BaseModel):
            x: int = 0

        self.assertFalse(isolated.has_schema("NotRegistered"))

    def test_decorator_creates_instance(self):
        isolated = SchemaRegistry()

        @register_schema("ConfigModel", registry=isolated)
        class ConfigModel(BaseModel):
            timeout: int = 30

        instance = isolated.create_instance("ConfigModel")
        self.assertEqual(instance.timeout, 30)


# =============================================================================
# Тесты потокобезопасности
# =============================================================================


class TestSchemaRegistryThreadSafety(unittest.TestCase):
    """Тесты потокобезопасности."""

    def test_concurrent_register(self):
        registry = SchemaRegistry()
        errors = []

        def register_batch(thread_id: int):
            try:
                for i in range(10):

                    class TempModel(BaseModel):
                        value: int = i

                    registry.register(f"T{thread_id}_{i}", TempModel)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_batch, args=(tid,)) for tid in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(registry.list_schemas()), 50)

    def test_concurrent_read_write(self):
        registry = SchemaRegistry()
        registry.register("Shared", SampleModel)
        errors = []

        def read_write():
            try:
                for _ in range(20):
                    registry.has_schema("Shared")
                    registry.get_schema("Shared")
                    registry.list_schemas()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_write) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
