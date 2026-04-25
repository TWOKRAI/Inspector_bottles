# -*- coding: utf-8 -*-
"""
Тесты для DataConverter (serialization/converter.py).

Покрывает:
    - model_to_dict / dict_to_model
    - model_to_json / json_to_model
    - model_to_yaml / yaml_to_model
    - Универсальный convert() между форматами
    - save_to_file / load_from_file (JSON и YAML)
    - Опции: exclude_none, exclude_defaults, include/exclude fields
"""
import json
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from multiprocess_framework.modules.data_schema_module import DataConverter, FormatType


# =============================================================================
# Тестовые модели
# =============================================================================

class SimpleModel(BaseModel):
    name: str = "default"
    count: int = 1
    active: bool = True


class NestedModel(BaseModel):
    title: str = "root"
    nested: Dict[str, Any] = Field(default_factory=lambda: {"level": 1})
    optional_field: Optional[str] = None


class ComplexModel(BaseModel):
    id: int = 0
    tags: list = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Тесты model_to_dict / dict_to_model
# =============================================================================

class TestModelToDict(unittest.TestCase):
    """Тесты model_to_dict."""

    def test_basic_conversion(self):
        m = SimpleModel(name="test", count=5)
        d = DataConverter.model_to_dict(m)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["count"], 5)
        self.assertEqual(d["active"], True)

    def test_nested_model(self):
        m = NestedModel(title="root", nested={"level": 2, "key": "val"})
        d = DataConverter.model_to_dict(m)
        self.assertEqual(d["nested"]["level"], 2)
        self.assertEqual(d["nested"]["key"], "val")

    def test_exclude_none(self):
        m = NestedModel(optional_field=None)
        d = DataConverter.model_to_dict(m, exclude_none=True)
        self.assertNotIn("optional_field", d)

    def test_include_fields(self):
        m = SimpleModel(name="x", count=10)
        d = DataConverter.model_to_dict(m, include={"name"})
        self.assertIn("name", d)
        self.assertNotIn("count", d)

    def test_exclude_fields(self):
        m = SimpleModel(name="x", count=10)
        d = DataConverter.model_to_dict(m, exclude={"active"})
        self.assertIn("name", d)
        self.assertNotIn("active", d)


class TestDictToModel(unittest.TestCase):
    """Тесты dict_to_model."""

    def test_basic_conversion(self):
        d = {"name": "from_dict", "count": 7, "active": False}
        m = DataConverter.dict_to_model(d, SimpleModel)
        self.assertIsInstance(m, SimpleModel)
        self.assertEqual(m.name, "from_dict")
        self.assertEqual(m.count, 7)
        self.assertFalse(m.active)

    def test_partial_dict_uses_defaults(self):
        d = {"name": "partial"}
        m = DataConverter.dict_to_model(d, SimpleModel)
        self.assertEqual(m.count, 1)  # дефолт

    def test_round_trip(self):
        original = SimpleModel(name="roundtrip", count=42)
        d = DataConverter.model_to_dict(original)
        restored = DataConverter.dict_to_model(d, SimpleModel)
        self.assertEqual(restored, original)


# =============================================================================
# Тесты model_to_json / json_to_model
# =============================================================================

class TestModelToJson(unittest.TestCase):
    """Тесты model_to_json / json_to_model."""

    def test_model_to_json_is_string(self):
        m = SimpleModel(name="json_test")
        js = DataConverter.model_to_json(m)
        self.assertIsInstance(js, str)
        parsed = json.loads(js)
        self.assertEqual(parsed["name"], "json_test")

    def test_json_to_model(self):
        js = '{"name": "from_json", "count": 3, "active": true}'
        m = DataConverter.json_to_model(js, SimpleModel)
        self.assertEqual(m.name, "from_json")
        self.assertEqual(m.count, 3)

    def test_json_round_trip(self):
        original = SimpleModel(name="roundtrip_json", count=99)
        js = DataConverter.model_to_json(original)
        restored = DataConverter.json_to_model(js, SimpleModel)
        self.assertEqual(restored, original)

    def test_json_with_nested(self):
        m = NestedModel(title="nested_json", nested={"a": 1, "b": 2})
        js = DataConverter.model_to_json(m)
        restored = DataConverter.json_to_model(js, NestedModel)
        self.assertEqual(restored.nested["a"], 1)


# =============================================================================
# Тесты model_to_yaml / yaml_to_model
# =============================================================================

class TestModelToYaml(unittest.TestCase):
    """Тесты model_to_yaml / yaml_to_model."""

    def setUp(self):
        try:
            import yaml
            self.yaml_available = True
        except ImportError:
            self.yaml_available = False

    def test_model_to_yaml_is_string(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        m = SimpleModel(name="yaml_test")
        ys = DataConverter.model_to_yaml(m)
        self.assertIsInstance(ys, str)
        self.assertIn("yaml_test", ys)

    def test_yaml_round_trip(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        original = SimpleModel(name="yaml_roundtrip", count=55)
        ys = DataConverter.model_to_yaml(original)
        restored = DataConverter.yaml_to_model(ys, SimpleModel)
        self.assertEqual(restored, original)

    def test_yaml_with_nested(self):
        if not self.yaml_available:
            self.skipTest("PyYAML не установлен")
        m = NestedModel(title="yaml_nested", nested={"x": 10})
        ys = DataConverter.model_to_yaml(m)
        restored = DataConverter.yaml_to_model(ys, NestedModel)
        self.assertEqual(restored.nested["x"], 10)


# =============================================================================
# Тесты универсального convert()
# =============================================================================

class TestConvertUniversal(unittest.TestCase):
    """Тесты универсального метода convert()."""

    def test_model_to_dict(self):
        m = SimpleModel(name="conv", count=3)
        result = DataConverter.convert(m, FormatType.MODEL, FormatType.DICT)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "conv")

    def test_model_to_json(self):
        m = SimpleModel(name="conv_json")
        result = DataConverter.convert(m, FormatType.MODEL, FormatType.JSON)
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertEqual(parsed["name"], "conv_json")

    def test_json_to_model(self):
        js = '{"name": "from_json_conv", "count": 7, "active": false}'
        result = DataConverter.convert(
            js, FormatType.JSON, FormatType.MODEL, model_class=SimpleModel
        )
        self.assertIsInstance(result, SimpleModel)
        self.assertEqual(result.name, "from_json_conv")

    def test_dict_to_json(self):
        d = {"name": "dict_to_json", "count": 1}
        result = DataConverter.convert(d, FormatType.DICT, FormatType.JSON)
        self.assertIsInstance(result, str)
        self.assertIn("dict_to_json", result)

    def test_json_to_dict(self):
        js = '{"name": "json_to_dict", "count": 2}'
        result = DataConverter.convert(js, FormatType.JSON, FormatType.DICT)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "json_to_dict")


# =============================================================================
# Тесты save_to_file / load_from_file
# =============================================================================

class TestFileOperations(unittest.TestCase):
    """Тесты сохранения и загрузки из файла."""

    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load_json(self):
        m = SimpleModel(name="file_json", count=10)
        path = self.temp_dir / "test.json"
        DataConverter.save_to_file(m, path)
        loaded = DataConverter.load_from_file(path, model_class=SimpleModel)
        self.assertEqual(loaded, m)

    def test_save_and_load_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML не установлен")
        m = SimpleModel(name="file_yaml", count=20)
        path = self.temp_dir / "test.yaml"
        DataConverter.save_to_file(m, path, format_type=FormatType.YAML)
        loaded = DataConverter.load_from_file(path, model_class=SimpleModel)
        self.assertEqual(loaded, m)

    def test_save_nested_model(self):
        m = NestedModel(title="nested_file", nested={"a": 1, "b": [1, 2, 3]})
        path = self.temp_dir / "nested.json"
        DataConverter.save_to_file(m, path)
        loaded = DataConverter.load_from_file(path, model_class=NestedModel)
        self.assertEqual(loaded.title, "nested_file")
        self.assertEqual(loaded.nested["b"], [1, 2, 3])

    def test_load_nonexistent_file_raises(self):
        path = self.temp_dir / "nonexistent.json"
        with self.assertRaises(Exception):
            DataConverter.load_from_file(path, model_class=SimpleModel)


if __name__ == "__main__":
    unittest.main()
