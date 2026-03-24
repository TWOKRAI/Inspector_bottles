"""
Unit-тесты для VersionManager (versioning/version_manager.py).

Сценарии:
- create_version, get_current_version, get_version (модель по номеру версии), get_version_history.
- rollback с create_new_version, compare_versions.
Используются моки StorageManager и ProcessData; SchemaManager — реальный (фикстура schema_registry).
"""

import pytest
from typing import Optional
from unittest.mock import Mock

from ..registry.schema_registry import SchemaManager
from ..versioning.version_manager import VersionManager, VersionInfo
from ..storage.storage_manager import StorageManager
from ..models.base import BaseManagerModel
from ..models.types import ComponentType
# Опциональный импорт ProcessData для тестов
try:
    from ...process_module.process_data import ProcessData
except ImportError:
    # Fallback для старого пути
    try:
        from ....modules.Shared_resources_module.Process_module.process_data import ProcessData
    except ImportError:
        ProcessData = None  # type: ignore


# Тестовая модель (префикс _ чтобы pytest не собирал как тест)
class _TestManagerModel(BaseManagerModel):
    """Тестовая модель менеджера."""
    
    test_field: str = "default"


@pytest.fixture
def schema_registry():
    """Фикстура для SchemaManager."""
    registry = SchemaManager.get_instance()
    registry.clear()
    registry.register("TestManager", _TestManagerModel)
    yield registry
    registry.clear()


@pytest.fixture
def mock_process_data():
    """Создает mock ProcessData."""
    process_data = Mock(spec=ProcessData)
    process_data.custom = {
        'component_managers': {},
        'component_managers_versions': {}
    }
    process_data.update_timestamp = Mock()
    return process_data


@pytest.fixture
def mock_storage_manager(mock_process_data):
    """Создает mock StorageManager."""
    manager = Mock(spec=StorageManager)
    manager._get_process_data = Mock(return_value=mock_process_data)
    return manager


@pytest.fixture
def version_manager(mock_storage_manager):
    """Создает VersionManager для тестов."""
    return VersionManager(mock_storage_manager)


@pytest.fixture
def manager_model():
    """Создает тестовую модель менеджера."""
    return _TestManagerModel(
        component_class="TestManager",
        name="test_manager",
        component_type=ComponentType.MANAGER,
        config={"test_field": "test_value"}
    )


def test_create_version(version_manager, manager_model, mock_process_data):
    """Тест создания версии."""
    version = version_manager.create_version(
        manager_model,
        comment="Test version",
        tags=["test"]
    )
    
    assert version == 1
    assert 'component_managers_versions' in mock_process_data.custom
    versions_dict = mock_process_data.custom['component_managers_versions']
    assert 'TestManager' in versions_dict
    assert 'test_manager' in versions_dict['TestManager']
    
    manager_versions = versions_dict['TestManager']['test_manager']
    assert manager_versions['current_version'] == 1
    assert '1' in manager_versions['versions']
    
    version_info = manager_versions['versions']['1']
    assert version_info['version'] == 1
    assert version_info['comment'] == "Test version"
    assert "test" in version_info['tags']


def test_get_current_version(version_manager, manager_model, mock_process_data):
    """Тест получения текущей версии."""
    # Создаем версию
    version_manager.create_version(manager_model)
    
    current = version_manager.get_current_version(
        "TestManager",
        "test_manager"
    )
    assert current == 1


def test_get_version(version_manager, manager_model, mock_process_data, schema_registry):
    """Тест получения модели по версии."""
    # Создаем версию
    version_manager.create_version(manager_model)
    
    # Получаем версию
    retrieved = version_manager.get_version(
        "TestManager",
        "test_manager",
        1
    )
    
    assert retrieved is not None
    assert isinstance(retrieved, BaseManagerModel)
    assert retrieved.component_class == "TestManager"
    assert retrieved.name == "test_manager"


def test_get_version_history(version_manager, manager_model, mock_process_data):
    """Тест получения истории версий."""
    # Создаем несколько версий
    version_manager.create_version(manager_model, comment="Version 1")
    version_manager.create_version(manager_model, comment="Version 2")
    
    history = version_manager.get_version_history(
        "TestManager",
        "test_manager"
    )
    
    assert len(history) == 2
    assert history[0]['version'] == 2  # Сортировка от новых к старым
    assert history[1]['version'] == 1


def test_rollback(version_manager, manager_model, mock_process_data, mock_storage_manager):
    """Тест отката к предыдущей версии."""
    # Создаем версию
    version_manager.create_version(manager_model, comment="Version 1")
    
    # Откатываемся
    success = version_manager.rollback(
        "TestManager",
        "test_manager",
        1,
        create_new_version=True,
        comment="Rollback"
    )
    
    assert success
    # Проверяем, что была создана новая версия с откатом
    history = version_manager.get_version_history("TestManager", "test_manager")
    assert len(history) == 2


def test_compare_versions(version_manager, manager_model, mock_process_data, schema_registry):
    """Тест сравнения версий."""
    # Создаем первую версию
    model1 = _TestManagerModel(
        component_class="TestManager",
        name="test_manager",
        component_type=ComponentType.MANAGER,
        config={"test_field": "value1"}
    )
    version_manager.create_version(model1)
    
    # Создаем вторую версию с изменением
    model2 = _TestManagerModel(
        component_class="TestManager",
        name="test_manager",
        component_type=ComponentType.MANAGER,
        config={"test_field": "value2"}
    )
    version_manager.create_version(model2)
    
    # Сравниваем версии
    diff = version_manager.compare_versions(
        "TestManager",
        "test_manager",
        1,
        2
    )
    
    assert 'differences' in diff
    assert diff['version1'] == 1
    assert diff['version2'] == 2

