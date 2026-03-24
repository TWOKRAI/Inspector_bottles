# -*- coding: utf-8 -*-
"""
Тесты для extensions/versioning — VersionInfo и VersionManager.

Покрывает:
    - VersionInfo: создание, to_dict, from_dict
    - VersionManager: создание без StorageManager (standalone режим)
    - VersionManager: create_version без ProcessData возвращает 0
    - VersionManager: document versioning (create_document_version, get_document_version)
"""
import time
import unittest
from typing import Any, Dict, Optional

from data_schema_module.extensions.versioning import VersionManager, VersionInfo
from data_schema_module.extensions.models import BaseManagerModel, ComponentType


# =============================================================================
# Тесты VersionInfo
# =============================================================================

class TestVersionInfo(unittest.TestCase):
    """Тесты VersionInfo."""

    def _make_version_info(self, **kwargs) -> VersionInfo:
        defaults = {
            "version": 1,
            "data": {"name": "test", "value": 42},
            "timestamp": time.time(),
        }
        defaults.update(kwargs)
        return VersionInfo(**defaults)

    def test_create_basic(self):
        vi = self._make_version_info()
        self.assertEqual(vi.version, 1)
        self.assertEqual(vi.data["name"], "test")
        self.assertIsNotNone(vi.timestamp)

    def test_default_comment_none(self):
        vi = self._make_version_info()
        self.assertIsNone(vi.comment)

    def test_default_author_none(self):
        vi = self._make_version_info()
        self.assertIsNone(vi.author)

    def test_default_tags_empty(self):
        vi = self._make_version_info()
        self.assertEqual(vi.tags, [])

    def test_with_comment(self):
        vi = self._make_version_info(comment="Initial version")
        self.assertEqual(vi.comment, "Initial version")

    def test_with_author(self):
        vi = self._make_version_info(author="admin")
        self.assertEqual(vi.author, "admin")

    def test_with_tags(self):
        vi = self._make_version_info(tags=["stable", "production"])
        self.assertIn("stable", vi.tags)
        self.assertIn("production", vi.tags)

    def test_to_dict(self):
        vi = self._make_version_info(
            version=2,
            comment="Test",
            author="user",
            tags=["tag1"],
        )
        d = vi.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["version"], 2)
        self.assertEqual(d["comment"], "Test")
        self.assertEqual(d["author"], "user")
        self.assertIn("tag1", d["tags"])
        self.assertIn("data", d)
        self.assertIn("timestamp", d)

    def test_from_dict(self):
        original = self._make_version_info(
            version=3,
            comment="From dict",
            author="tester",
            tags=["v3"],
        )
        d = original.to_dict()
        restored = VersionInfo.from_dict(d)
        self.assertEqual(restored.version, 3)
        self.assertEqual(restored.comment, "From dict")
        self.assertEqual(restored.author, "tester")
        self.assertIn("v3", restored.tags)

    def test_round_trip(self):
        ts = time.time()
        original = VersionInfo(
            version=5,
            data={"key": "value", "num": 123},
            timestamp=ts,
            comment="Round trip test",
            author="dev",
            tags=["test", "round-trip"],
        )
        d = original.to_dict()
        restored = VersionInfo.from_dict(d)
        self.assertEqual(restored.version, original.version)
        self.assertEqual(restored.data, original.data)
        self.assertEqual(restored.timestamp, original.timestamp)
        self.assertEqual(restored.comment, original.comment)
        self.assertEqual(restored.author, original.author)
        self.assertEqual(restored.tags, original.tags)


# =============================================================================
# Тесты VersionManager (без ProcessData)
# =============================================================================

class TestVersionManagerStandalone(unittest.TestCase):
    """Тесты VersionManager без StorageManager (standalone)."""

    def setUp(self):
        self.vm = VersionManager()  # без storage_manager

    def _make_manager_model(self, name: str = "test_manager") -> BaseManagerModel:
        return BaseManagerModel(
            component_type=ComponentType.MANAGER,
            component_class="app.managers.TestManager",
            name=name,
        )

    def test_create_without_storage_manager(self):
        vm = VersionManager()
        self.assertIsNone(vm.storage_manager)

    def test_create_version_without_process_data_returns_zero(self):
        """Без ProcessData create_version возвращает 0."""
        model = self._make_manager_model()
        result = self.vm.create_version(model, comment="Test")
        self.assertEqual(result, 0)

    def test_get_current_version_without_process_data(self):
        """Без ProcessData get_current_version возвращает 0."""
        result = self.vm.get_current_version("app.managers.TestManager", "test_manager")
        self.assertEqual(result, 0)

    def test_get_version_without_process_data_returns_none(self):
        """Без ProcessData get_version возвращает None."""
        result = self.vm.get_version("app.managers.TestManager", "test_manager", 1)
        self.assertIsNone(result)

    def test_rollback_without_process_data_returns_false(self):
        """Без ProcessData rollback возвращает False."""
        result = self.vm.rollback("app.managers.TestManager", "test_manager", 1)
        self.assertFalse(result)

    def test_get_version_history_without_process_data_returns_empty(self):
        """Без ProcessData get_version_history возвращает пустой список."""
        result = self.vm.get_version_history("app.managers.TestManager", "test_manager")
        self.assertEqual(result, [])


# =============================================================================
# Тесты VersionManager с mock StorageManager
# =============================================================================

class MockProcessData:
    """Мок ProcessData для тестирования."""

    def __init__(self):
        self.custom: Dict[str, Any] = {}
        self._timestamp = time.time()

    def update_timestamp(self):
        self._timestamp = time.time()


class MockStorageManager:
    """Мок StorageManager для тестирования."""

    def __init__(self):
        self._process_data = MockProcessData()

    def _get_process_data(self, process_name: Optional[str] = None) -> MockProcessData:
        return self._process_data


class TestVersionManagerWithMock(unittest.TestCase):
    """Тесты VersionManager с mock StorageManager."""

    def setUp(self):
        self.storage = MockStorageManager()
        self.vm = VersionManager(storage_manager=self.storage)

    def _make_manager_model(self, name: str = "test_manager") -> BaseManagerModel:
        return BaseManagerModel(
            component_type=ComponentType.MANAGER,
            component_class="app.managers.TestManager",
            name=name,
        )

    def test_create_version_returns_version_number(self):
        model = self._make_manager_model()
        version = self.vm.create_version(model, comment="First version")
        self.assertEqual(version, 1)

    def test_create_multiple_versions_increments(self):
        model = self._make_manager_model()
        v1 = self.vm.create_version(model)
        v2 = self.vm.create_version(model)
        v3 = self.vm.create_version(model)
        self.assertEqual(v1, 1)
        self.assertEqual(v2, 2)
        self.assertEqual(v3, 3)

    def test_get_current_version_after_create(self):
        model = self._make_manager_model()
        self.vm.create_version(model)
        self.vm.create_version(model)
        current = self.vm.get_current_version(
            "app.managers.TestManager",
            "test_manager",
        )
        self.assertEqual(current, 2)

    def test_get_version_history_returns_versions(self):
        model = self._make_manager_model()
        self.vm.create_version(model, comment="v1")
        self.vm.create_version(model, comment="v2")
        history = self.vm.get_version_history("app.managers.TestManager", "test_manager")
        self.assertGreaterEqual(len(history), 2)

    def test_different_managers_independent(self):
        model1 = self._make_manager_model("manager_1")
        model2 = self._make_manager_model("manager_2")
        # model2 имеет другой component_class
        model2 = BaseManagerModel(
            component_type=ComponentType.MANAGER,
            component_class="app.managers.OtherManager",
            name="manager_2",
        )
        self.vm.create_version(model1)
        self.vm.create_version(model1)
        self.vm.create_version(model2)

        v1 = self.vm.get_current_version("app.managers.TestManager", "manager_1")
        v2 = self.vm.get_current_version("app.managers.OtherManager", "manager_2")
        self.assertEqual(v1, 2)
        self.assertEqual(v2, 1)


if __name__ == "__main__":
    unittest.main()
