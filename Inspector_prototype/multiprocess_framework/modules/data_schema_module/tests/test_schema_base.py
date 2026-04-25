# -*- coding: utf-8 -*-
"""
Тесты для SchemaBase / RegisterBase (core/schema_base.py).

Покрывает:
    - Создание SchemaBase и RegisterBase (backward compat alias)
    - model_dump, validate_assignment
    - Валидация min/max при создании
    - update_field, validate_field
    - get_field_meta, get_all_fields_meta
    - Routing: get_routing_channels, get_fields_for_channel
    - Access: can_modify_field, get_visible_fields, get_editable_fields
"""
import unittest
from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    SchemaBase,
    RegisterBase,
    SchemaMixin,
    RegisterMixin,
)


def _make_simple_schema():
    """Создать простую схему для тестов."""
    class SimpleSchema(SchemaBase):
        value: Annotated[float, FieldMeta("Значение", min=0.0, max=100.0)] = 50.0
        name: str = "default"
        hidden_field: Annotated[int, FieldMeta("Скрытое", hidden=True)] = 0
        readonly_field: Annotated[str, FieldMeta("Только чтение", readonly=True)] = "fixed"
        admin_field: Annotated[int, FieldMeta("Для админа", access_level=10)] = 42

    return SimpleSchema


def _make_routing_schema():
    """Создать схему с маршрутизацией."""
    CHANNEL_A = FieldRouting(channel="channel_a")
    CHANNEL_B = FieldRouting(channel="channel_b")

    class RoutingSchema(SchemaBase):
        field_a1: Annotated[float, FieldMeta("A1", routing=CHANNEL_A)] = 1.0
        field_a2: Annotated[float, FieldMeta("A2", routing=CHANNEL_A)] = 2.0
        field_b1: Annotated[float, FieldMeta("B1", routing=CHANNEL_B)] = 3.0
        plain: float = 0.0

    return RoutingSchema


class TestSchemaBaseCreation(unittest.TestCase):
    """Тесты создания SchemaBase."""

    def test_create_with_defaults(self):
        Schema = _make_simple_schema()
        s = Schema()
        self.assertEqual(s.value, 50.0)
        self.assertEqual(s.name, "default")

    def test_create_with_values(self):
        Schema = _make_simple_schema()
        s = Schema(value=75.0, name="test")
        self.assertEqual(s.value, 75.0)
        self.assertEqual(s.name, "test")

    def test_model_dump(self):
        Schema = _make_simple_schema()
        s = Schema(value=30.0)
        d = s.model_dump()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["value"], 30.0)
        self.assertIn("name", d)

    def test_register_base_alias(self):
        """RegisterBase должен быть алиасом SchemaBase."""
        self.assertIs(RegisterBase, SchemaBase)

    def test_schema_mixin_alias(self):
        """RegisterMixin должен быть алиасом SchemaMixin."""
        self.assertIs(RegisterMixin, SchemaMixin)

    def test_inheritance(self):
        Schema = _make_simple_schema()
        s = Schema()
        self.assertIsInstance(s, SchemaBase)
        self.assertIsInstance(s, SchemaMixin)


class TestSchemaBaseConstraints(unittest.TestCase):
    """Тесты валидации ограничений min/max."""

    def setUp(self):
        self.Schema = _make_simple_schema()

    def test_valid_value_at_min(self):
        s = self.Schema(value=0.0)
        self.assertEqual(s.value, 0.0)

    def test_valid_value_at_max(self):
        s = self.Schema(value=100.0)
        self.assertEqual(s.value, 100.0)

    def test_value_below_min_raises(self):
        with self.assertRaises(ValueError):
            self.Schema(value=-1.0)

    def test_value_above_max_raises(self):
        with self.assertRaises(ValueError):
            self.Schema(value=101.0)

    def test_no_constraint_field_passes(self):
        s = self.Schema(name="any_string")
        self.assertEqual(s.name, "any_string")


class TestSchemaBaseFieldMeta(unittest.TestCase):
    """Тесты методов работы с FieldMeta."""

    def setUp(self):
        self.Schema = _make_simple_schema()
        self.s = self.Schema()

    def test_get_field_meta_returns_field_meta(self):
        meta = self.Schema.get_field_meta("value")
        self.assertIsNotNone(meta)
        self.assertIsInstance(meta, FieldMeta)

    def test_get_field_meta_min_max(self):
        meta = self.Schema.get_field_meta("value")
        self.assertEqual(meta.min, 0.0)
        self.assertEqual(meta.max, 100.0)

    def test_get_field_meta_plain_field_returns_none(self):
        meta = self.Schema.get_field_meta("name")
        self.assertIsNone(meta)

    def test_get_all_fields_meta(self):
        all_meta = self.Schema.get_all_fields_meta()
        self.assertIn("value", all_meta)
        self.assertNotIn("name", all_meta)

    def test_get_field_metadata_dict(self):
        d = self.s.get_field_metadata("value")
        self.assertIsInstance(d, dict)
        self.assertIn("description", d)
        self.assertIn("min", d)
        self.assertIn("max", d)

    def test_get_field_metadata_empty_for_plain(self):
        d = self.s.get_field_metadata("name")
        self.assertEqual(d, {})


class TestSchemaBaseUpdateField(unittest.TestCase):
    """Тесты update_field."""

    def setUp(self):
        self.Schema = _make_simple_schema()
        self.s = self.Schema()

    def test_update_valid_value(self):
        ok, err = self.s.update_field("value", 75.0)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(self.s.value, 75.0)

    def test_update_value_below_min_fails(self):
        ok, err = self.s.update_field("value", -10.0)
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertEqual(self.s.value, 50.0)  # не изменилось

    def test_update_value_above_max_fails(self):
        ok, err = self.s.update_field("value", 200.0)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_update_readonly_field_fails(self):
        ok, err = self.s.update_field("readonly_field", "new_value")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_update_admin_field_without_access_fails(self):
        ok, err = self.s.update_field("admin_field", 99, access_level=0)
        self.assertFalse(ok)

    def test_update_admin_field_with_access_succeeds(self):
        ok, err = self.s.update_field("admin_field", 99, access_level=10)
        self.assertTrue(ok)
        self.assertEqual(self.s.admin_field, 99)

    def test_update_plain_field(self):
        ok, err = self.s.update_field("name", "new_name")
        self.assertTrue(ok)
        self.assertEqual(self.s.name, "new_name")


class TestSchemaBaseAccessControl(unittest.TestCase):
    """Тесты управления доступом."""

    def setUp(self):
        self.Schema = _make_simple_schema()
        self.s = self.Schema()

    def test_can_modify_normal_field(self):
        self.assertTrue(self.s.can_modify_field("value"))

    def test_cannot_modify_readonly_field(self):
        self.assertFalse(self.s.can_modify_field("readonly_field"))

    def test_cannot_modify_admin_field_without_access(self):
        self.assertFalse(self.s.can_modify_field("admin_field", access_level=0))

    def test_can_modify_admin_field_with_access(self):
        self.assertTrue(self.s.can_modify_field("admin_field", access_level=10))

    def test_get_visible_fields_excludes_hidden(self):
        visible = self.s.get_visible_fields()
        self.assertIn("value", visible)
        self.assertNotIn("hidden_field", visible)

    def test_get_editable_fields_excludes_readonly(self):
        editable = self.s.get_editable_fields()
        self.assertIn("value", editable)
        self.assertNotIn("readonly_field", editable)

    def test_values_dict_alias(self):
        d = self.s.values_dict()
        self.assertEqual(d, self.s.model_dump())


class TestSchemaBaseRouting(unittest.TestCase):
    """Тесты маршрутизации."""

    def setUp(self):
        self.Schema = _make_routing_schema()
        self.s = self.Schema()

    def test_get_routing_channels(self):
        channels = self.s.get_routing_channels()
        self.assertIn("channel_a", channels)
        self.assertIn("channel_b", channels)

    def test_get_fields_for_channel_a(self):
        fields = self.s.get_fields_for_channel("channel_a")
        self.assertIn("field_a1", fields)
        self.assertIn("field_a2", fields)
        self.assertNotIn("field_b1", fields)

    def test_get_fields_for_channel_b(self):
        fields = self.s.get_fields_for_channel("channel_b")
        self.assertIn("field_b1", fields)
        self.assertNotIn("field_a1", fields)

    def test_plain_field_not_in_any_channel(self):
        channels = self.s.get_routing_channels()
        for ch in channels:
            self.assertNotIn("plain", self.s.get_fields_for_channel(ch))


class TestSchemaInheritance(unittest.TestCase):
    """Тесты наследования SchemaBase."""

    def test_child_inherits_parent_fields(self):
        class Parent(SchemaBase):
            x: Annotated[int, FieldMeta("X", min=0, max=10)] = 5

        class Child(Parent):
            y: Annotated[int, FieldMeta("Y", min=0, max=20)] = 10

        c = Child()
        self.assertEqual(c.x, 5)
        self.assertEqual(c.y, 10)
        all_meta = Child.get_all_fields_meta()
        self.assertIn("x", all_meta)
        self.assertIn("y", all_meta)

    def test_child_constraint_validation(self):
        class Parent(SchemaBase):
            x: Annotated[int, FieldMeta("X", min=0, max=10)] = 5

        class Child(Parent):
            y: Annotated[int, FieldMeta("Y", min=0, max=20)] = 10

        with self.assertRaises(ValueError):
            Child(x=100)  # нарушение ограничения родителя


if __name__ == "__main__":
    unittest.main()
