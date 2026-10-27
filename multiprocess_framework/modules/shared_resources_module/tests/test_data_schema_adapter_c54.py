"""C-54: ``DataSchemaAdapter`` отдаёт настоящий ``StorageManager`` и не глотает ошибку импорта.

Слепая приёмка (plans/word-layout/tasks/C-53.md). Контракт: ``get_data_manager()`` -- экземпляр
``data_schema_module.storage.storage_manager.StorageManager``; ``is_available()`` -- ``True``;
сломанный импорт -- ``ImportError``, а не ``None``.
"""

from __future__ import annotations

import sys

import pytest

from multiprocess_framework.modules.data_schema_module.storage.storage_manager import StorageManager
from multiprocess_framework.modules.shared_resources_module.adapters.data_schema_adapter import (
    DataSchemaAdapter,
)

_STORAGE_MANAGER_MODULE = "multiprocess_framework.modules.data_schema_module.storage.storage_manager"


class _SrmStub:
    """Заглушка SharedResourcesManager: настоящий не нужен."""


def test_get_data_manager_returns_storage_manager():
    dm = DataSchemaAdapter(None).get_data_manager()
    assert isinstance(dm, StorageManager)


def test_get_data_manager_binds_given_srm():
    srm = _SrmStub()
    dm = DataSchemaAdapter(srm).get_data_manager()
    assert isinstance(dm, StorageManager)
    assert dm.shared_resources is srm


def test_second_call_returns_same_object():
    adapter = DataSchemaAdapter(None)
    first = adapter.get_data_manager()
    assert first is not None
    assert adapter.get_data_manager() is first


def test_data_manager_property_is_same_object_as_get_data_manager():
    adapter = DataSchemaAdapter(None)
    first = adapter.get_data_manager()
    assert first is not None
    assert adapter.data_manager is first


def test_is_available_true():
    assert DataSchemaAdapter(None).is_available() is True


def test_import_error_is_not_swallowed(monkeypatch):
    monkeypatch.setitem(sys.modules, _STORAGE_MANAGER_MODULE, None)
    adapter = DataSchemaAdapter(None)
    with pytest.raises(ImportError):
        adapter.get_data_manager()


def test_is_available_does_not_hide_broken_import(monkeypatch):
    monkeypatch.setitem(sys.modules, _STORAGE_MANAGER_MODULE, None)
    adapter = DataSchemaAdapter(None)
    with pytest.raises(ImportError):
        adapter.is_available()
