"""
Unit-тесты для ModelFactory (factory/model_factory.py).

Сценарии:
- create_manager / create / from_dict (с указанием schema_name и без).
- Дефолты, auto_register (мок StorageManager), отсутствующая схема → SchemaNotFoundError,
  отсутствующее name → SchemaValidationError.
"""

import pytest
from unittest.mock import Mock, patch

from ..registry.schema_registry import SchemaManager
from ..factory.model_factory import ModelFactory
from ..models.base import BaseManagerModel
from ..models.types import ComponentType
from ..core.exceptions import (
    SchemaNotFoundError,
    SchemaValidationError,
)


# Тестовая модель (префикс _ чтобы pytest не собирал как тест)
class _TestManagerModel(BaseManagerModel):
    """Тестовая модель менеджера."""

    test_field: str = "default_value"


@pytest.fixture(autouse=True)
def reset_registry():
    """Сбрасываем реестр перед каждым тестом."""
    registry = SchemaManager.get_instance()
    registry.clear()
    registry.register("TestManager", _TestManagerModel)
    yield
    registry.clear()


def test_create_manager():
    """Тест создания модели менеджера."""
    model = ModelFactory.create_manager(
        "TestManager",
        "test_instance",
        data={"test_field": "custom_value"},
        auto_register=False,  # Не регистрируем в ProcessData
    )

    assert isinstance(model, BaseManagerModel)
    assert model.component_class == "TestManager"
    assert model.name == "test_instance"
    assert model.component_type == ComponentType.MANAGER
    assert model.test_field == "custom_value"


def test_create_manager_with_defaults():
    """Тест создания модели с дефолтными значениями."""
    model = ModelFactory.create_manager("TestManager", "test_instance", auto_register=False)

    assert model.test_field == "default_value"  # Дефолтное значение из модели


def test_from_dict():
    """Тест создания модели из словаря."""
    data = {
        "component_class": "TestManager",
        "name": "test_from_dict",
        "component_type": ComponentType.MANAGER,
        "test_field": "from_dict_value",
    }

    model = ModelFactory.from_dict(data)

    assert isinstance(model, BaseManagerModel)
    assert model.component_class == "TestManager"
    assert model.name == "test_from_dict"
    assert model.test_field == "from_dict_value"


def test_from_dict_with_schema_name():
    """Тест создания модели из словаря с указанием схемы."""
    data = {"name": "test_instance", "test_field": "custom_value"}

    model = ModelFactory.from_dict(data, schema_name="TestManager")

    assert isinstance(model, BaseManagerModel)
    assert model.test_field == "custom_value"


def test_create_manager_auto_register():
    """Тест автоматической регистрации в ProcessData."""
    from ..storage.storage_manager import StorageManager

    with patch.object(StorageManager, "get_instance") as mock_get_instance:
        mock_instance = Mock()
        mock_get_instance.return_value = mock_instance

        model = ModelFactory.create_manager(
            "TestManager", "test_instance", auto_register=True, process_name="TestProcess", shared_resources=None
        )

        # Проверяем, что был вызван register_manager
        mock_instance.register_manager.assert_called_once()
        call_args = mock_instance.register_manager.call_args
        assert call_args[0][0] == model  # Первый аргумент - модель
        assert call_args[0][1] == "TestProcess"  # Второй аргумент - process_name


def test_from_dict_missing_schema():
    """Тест создания модели с несуществующей схемой."""
    with pytest.raises(SchemaNotFoundError) as exc_info:
        ModelFactory.from_dict({"name": "test", "test_field": "value"}, schema_name="NonExistentSchema")
    assert exc_info.value.schema_name == "NonExistentSchema"


def test_from_dict_missing_name():
    """Тест создания модели без обязательного поля name."""
    with pytest.raises(SchemaValidationError) as exc_info:
        ModelFactory.from_dict({"test_field": "value"}, schema_name="TestManager")
    assert exc_info.value.schema_name == "TestManager"


def test_create_manager_missing_schema():
    """Тест создания модели менеджера с несуществующей схемой."""
    registry = SchemaManager.get_instance()
    registry.clear()  # Очищаем реестр

    with pytest.raises(SchemaNotFoundError) as exc_info:
        ModelFactory.create_manager("NonExistentManager", "test_instance", auto_register=False)
    assert exc_info.value.schema_name == "NonExistentManager"


def test_create_basic():
    """Тест базового метода create."""
    model = ModelFactory.create(
        "TestManager",
        {
            "name": "test",
            "test_field": "value",
            "component_class": "TestManager",
            "component_type": ComponentType.MANAGER,
        },
    )

    assert isinstance(model, BaseManagerModel)
    assert model.name == "test"
    assert model.test_field == "value"
