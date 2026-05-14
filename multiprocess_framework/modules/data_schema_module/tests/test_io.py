# -*- coding: utf-8 -*-
"""
Тесты для RegistersIO (serialization/io.py).

Покрывает:
    - registers_to_dict / registers_from_dict
    - registers_to_json / registers_from_json
    - registers_to_yaml / registers_from_yaml
    - registers_to_flat_dict / registers_from_flat_dict
    - Работа с реальным RegistersContainer
"""

import importlib.util
import json
import unittest
from typing import Any, Dict

from multiprocess_framework.modules.data_schema_module import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
    RegistersContainer,
    SchemaBase,
    FieldMeta,
)
from typing import Annotated


# =============================================================================
# Вспомогательные классы
# =============================================================================


class FakeRegisters:
    """Минимальный объект с model_dump_all / model_validate_all."""

    def __init__(self) -> None:
        self.data: Dict[str, Dict[str, Any]] = {
            "sensor": {"temperature": 25.0, "humidity": 60.0},
            "control": {"speed": 10, "active": True},
        }

    def model_dump_all(self) -> Dict[str, Any]:
        return dict(self.data)

    def model_validate_all(self, data: Dict[str, Any]) -> None:
        self.data = dict(data)


def _fake_factory() -> FakeRegisters:
    return FakeRegisters()


class SensorRegisters(SchemaBase):
    temperature: Annotated[float, FieldMeta("Температура", min=-40.0, max=120.0)] = 25.0
    humidity: Annotated[float, FieldMeta("Влажность", min=0.0, max=100.0)] = 60.0


class ControlRegisters(SchemaBase):
    speed: Annotated[int, FieldMeta("Скорость", min=0, max=100)] = 10
    active: bool = True


# =============================================================================
# Тесты registers_to_dict / registers_from_dict
# =============================================================================


class TestRegistersToDictFromDict(unittest.TestCase):
    """Тесты экспорта/импорта в dict."""

    def test_to_dict(self):
        r = FakeRegisters()
        d = registers_to_dict(r)
        self.assertIsInstance(d, dict)
        self.assertIn("sensor", d)
        self.assertIn("control", d)
        self.assertEqual(d["sensor"]["temperature"], 25.0)

    def test_from_dict(self):
        data = {
            "sensor": {"temperature": 30.0, "humidity": 70.0},
            "control": {"speed": 20, "active": False},
        }
        r = registers_from_dict(data, _fake_factory)
        result = r.model_dump_all()
        self.assertEqual(result["sensor"]["temperature"], 30.0)
        self.assertEqual(result["control"]["speed"], 20)

    def test_round_trip_dict(self):
        r = FakeRegisters()
        original = r.model_dump_all()
        r2 = registers_from_dict(original, _fake_factory)
        self.assertEqual(r2.model_dump_all(), original)

    def test_to_dict_with_container(self):
        container = RegistersContainer(
            {
                "sensor": SensorRegisters,
                "control": ControlRegisters,
            }
        )
        d = registers_to_dict(container)
        self.assertIn("sensor", d)
        self.assertIn("control", d)
        self.assertEqual(d["sensor"]["temperature"], 25.0)


# =============================================================================
# Тесты registers_to_json / registers_from_json
# =============================================================================


class TestRegistersToJsonFromJson(unittest.TestCase):
    """Тесты экспорта/импорта в JSON."""

    def test_to_json_is_string(self):
        r = FakeRegisters()
        js = registers_to_json(r)
        self.assertIsInstance(js, str)

    def test_to_json_valid_json(self):
        r = FakeRegisters()
        js = registers_to_json(r)
        parsed = json.loads(js)
        self.assertIn("sensor", parsed)

    def test_to_json_indent(self):
        r = FakeRegisters()
        js_indented = registers_to_json(r, indent=4)
        js_compact = registers_to_json(r, indent=0)
        self.assertGreater(len(js_indented), len(js_compact))

    def test_from_json(self):
        js = '{"sensor": {"temperature": 35.0, "humidity": 80.0}, "control": {"speed": 50, "active": true}}'
        r = registers_from_json(js, _fake_factory)
        result = r.model_dump_all()
        self.assertEqual(result["sensor"]["temperature"], 35.0)

    def test_json_round_trip(self):
        r = FakeRegisters()
        original = r.model_dump_all()
        js = registers_to_json(r)
        r2 = registers_from_json(js, _fake_factory)
        self.assertEqual(r2.model_dump_all(), original)

    def test_json_round_trip_with_container(self):
        container = RegistersContainer(
            {
                "sensor": SensorRegisters,
                "control": ControlRegisters,
            }
        )
        js = registers_to_json(container)
        parsed = json.loads(js)
        self.assertEqual(parsed["sensor"]["temperature"], 25.0)
        self.assertEqual(parsed["control"]["speed"], 10)


# =============================================================================
# Тесты registers_to_yaml / registers_from_yaml
# =============================================================================


class TestRegistersToYamlFromYaml(unittest.TestCase):
    """Тесты экспорта/импорта в YAML."""

    def setUp(self):
        self.yaml_available = importlib.util.find_spec("yaml") is not None

    def test_to_yaml_is_string(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        r = FakeRegisters()
        ys = registers_to_yaml(r)
        self.assertIsInstance(ys, str)

    def test_to_yaml_contains_keys(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        r = FakeRegisters()
        ys = registers_to_yaml(r)
        self.assertIn("sensor", ys)

    def test_yaml_round_trip(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        r = FakeRegisters()
        original = r.model_dump_all()
        ys = registers_to_yaml(r)
        r2 = registers_from_yaml(ys, _fake_factory)
        self.assertEqual(r2.model_dump_all(), original)

    def test_from_yaml(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        import yaml

        data = {"sensor": {"temperature": 40.0, "humidity": 90.0}}
        ys = yaml.dump(data)
        r = registers_from_yaml(ys, _fake_factory)
        self.assertEqual(r.model_dump_all()["sensor"]["temperature"], 40.0)


# =============================================================================
# Тесты registers_to_flat_dict / registers_from_flat_dict
# =============================================================================


class TestRegistersFlatDict(unittest.TestCase):
    """Тесты плоского словаря."""

    def test_to_flat_dict_basic(self):
        r = FakeRegisters()
        flat = registers_to_flat_dict(r)
        self.assertIn("sensor.temperature", flat)
        self.assertIn("sensor.humidity", flat)
        self.assertIn("control.speed", flat)
        self.assertEqual(flat["sensor.temperature"], 25.0)

    def test_to_flat_dict_with_prefix(self):
        r = FakeRegisters()
        flat = registers_to_flat_dict(r, prefix="process")
        self.assertIn("process.sensor.temperature", flat)
        self.assertIn("process.control.speed", flat)

    def test_from_flat_dict_basic(self):
        flat = {
            "sensor.temperature": 30.0,
            "sensor.humidity": 70.0,
            "control.speed": 20,
            "control.active": True,
        }
        r = registers_from_flat_dict(flat, _fake_factory)
        result = r.model_dump_all()
        self.assertEqual(result["sensor"]["temperature"], 30.0)
        self.assertEqual(result["control"]["speed"], 20)

    def test_flat_dict_round_trip(self):
        r = FakeRegisters()
        original = r.model_dump_all()
        flat = registers_to_flat_dict(r)
        r2 = registers_from_flat_dict(flat, _fake_factory)
        self.assertEqual(r2.model_dump_all(), original)

    def test_from_flat_dict_groups_by_register(self):
        flat = {"a.x": 1, "a.z": 3, "b.y": 2}
        r = registers_from_flat_dict(flat, _fake_factory)
        result = r.model_dump_all()
        self.assertEqual(result["a"]["x"], 1)
        self.assertEqual(result["a"]["z"], 3)
        self.assertEqual(result["b"]["y"], 2)

    def test_flat_dict_with_container(self):
        container = RegistersContainer(
            {
                "sensor": SensorRegisters,
                "control": ControlRegisters,
            }
        )
        flat = registers_to_flat_dict(container)
        self.assertIn("sensor.temperature", flat)
        self.assertIn("control.speed", flat)


if __name__ == "__main__":
    unittest.main()
