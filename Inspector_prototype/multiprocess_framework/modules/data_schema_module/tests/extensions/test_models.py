# -*- coding: utf-8 -*-
"""
Тесты для extensions/models — BaseComponentModel, BaseManagerModel, ComponentType.

Покрывает:
    - BaseComponentModel: создание, поля, model_dump
    - BaseManagerModel: создание, наследование от BaseComponentModel
    - ComponentType: значения enum
    - Опциональный ComponentDNA (пропускается если не установлен)
"""
import unittest
import time

from data_schema_module.extensions.models import (
    BaseComponentModel,
    BaseManagerModel,
    ComponentType,
)


# =============================================================================
# Тесты ComponentType
# =============================================================================

class TestComponentType(unittest.TestCase):
    """Тесты enum ComponentType."""

    def test_process_value(self):
        self.assertEqual(ComponentType.PROCESS, "process")

    def test_manager_value(self):
        self.assertEqual(ComponentType.MANAGER, "manager")

    def test_worker_value(self):
        self.assertEqual(ComponentType.WORKER, "worker")

    def test_module_value(self):
        self.assertEqual(ComponentType.MODULE, "module")

    def test_adapter_value(self):
        self.assertEqual(ComponentType.ADAPTER, "adapter")

    def test_component_value(self):
        self.assertEqual(ComponentType.COMPONENT, "component")

    def test_custom_value(self):
        self.assertEqual(ComponentType.CUSTOM, "custom")

    def test_all_types_are_strings(self):
        for ct in ComponentType:
            self.assertIsInstance(ct.value, str)


# =============================================================================
# Тесты BaseComponentModel
# =============================================================================

class TestBaseComponentModel(unittest.TestCase):
    """Тесты BaseComponentModel."""

    def _make_model(self, **kwargs):
        defaults = {
            "component_type": ComponentType.PROCESS,
            "component_class": "app.processes.TestProcess",
            "name": "test_process",
        }
        defaults.update(kwargs)
        return BaseComponentModel(**defaults)

    def test_create_basic(self):
        m = self._make_model()
        self.assertEqual(m.component_type, ComponentType.PROCESS)
        self.assertEqual(m.component_class, "app.processes.TestProcess")
        self.assertEqual(m.name, "test_process")

    def test_default_status(self):
        m = self._make_model()
        self.assertEqual(m.status, "initializing")

    def test_custom_status(self):
        m = self._make_model(status="running")
        self.assertEqual(m.status, "running")

    def test_metadata_default_empty(self):
        m = self._make_model()
        self.assertEqual(m.metadata, {})

    def test_metadata_custom(self):
        m = self._make_model(metadata={"key": "value", "count": 42})
        self.assertEqual(m.metadata["key"], "value")
        self.assertEqual(m.metadata["count"], 42)

    def test_version_is_set(self):
        m = self._make_model()
        self.assertIsNotNone(m.version)
        self.assertIsInstance(m.version, float)

    def test_created_at_is_set(self):
        before = time.time()
        m = self._make_model()
        after = time.time()
        self.assertGreaterEqual(m.created_at, before)
        self.assertLessEqual(m.created_at, after)

    def test_model_dump(self):
        m = self._make_model()
        d = m.model_dump()
        self.assertIsInstance(d, dict)
        self.assertIn("component_type", d)
        self.assertIn("name", d)
        self.assertIn("status", d)

    def test_different_component_types(self):
        for ct in ComponentType:
            m = self._make_model(component_type=ct)
            self.assertEqual(m.component_type, ct)

    def test_optional_paths_default_none(self):
        m = self._make_model()
        self.assertIsNone(m.class_path)
        self.assertIsNone(m.module_path)
        self.assertIsNone(m.file_path)
        self.assertIsNone(m.config_path)

    def test_optional_paths_set(self):
        m = self._make_model(
            class_path="app.processes.TestProcess",
            module_path="app.processes",
            file_path="/path/to/process.py",
        )
        self.assertEqual(m.class_path, "app.processes.TestProcess")
        self.assertEqual(m.module_path, "app.processes")


# =============================================================================
# Тесты BaseManagerModel
# =============================================================================

class TestBaseManagerModel(unittest.TestCase):
    """Тесты BaseManagerModel."""

    def _make_manager(self, **kwargs):
        defaults = {
            "component_type": ComponentType.MANAGER,
            "component_class": "app.managers.TestManager",
            "name": "test_manager",
        }
        defaults.update(kwargs)
        return BaseManagerModel(**defaults)

    def test_create_basic(self):
        m = self._make_manager()
        self.assertEqual(m.component_type, ComponentType.MANAGER)
        self.assertEqual(m.name, "test_manager")

    def test_is_base_component_model(self):
        m = self._make_manager()
        self.assertIsInstance(m, BaseComponentModel)

    def test_model_dump(self):
        m = self._make_manager()
        d = m.model_dump()
        self.assertIsInstance(d, dict)
        self.assertIn("component_type", d)


# =============================================================================
# Тесты опционального ComponentDNA
# =============================================================================

class TestComponentDNA(unittest.TestCase):
    """Тесты ComponentDNA (пропускается если не установлен)."""

    def setUp(self):
        try:
            from data_schema_module.extensions.models import ComponentDNA
            self.ComponentDNA = ComponentDNA
            self.available = ComponentDNA is not None
        except (ImportError, AttributeError):
            self.available = False

    def test_component_dna_importable(self):
        """ComponentDNA должен быть доступен через extensions.models."""
        if not self.available:
            self.skipTest("ComponentDNA не доступен")
        self.assertIsNotNone(self.ComponentDNA)


if __name__ == "__main__":
    unittest.main()
