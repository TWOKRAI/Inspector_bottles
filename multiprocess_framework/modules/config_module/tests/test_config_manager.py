"""
Unit-тесты для класса ConfigManager.
"""
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.config_module.core.config_manager import ConfigManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cm() -> ConfigManager:
    """ConfigManager без shared_resources (автономный режим)."""
    return ConfigManager(manager_name="TestCM")


@pytest.fixture
def cm_with_store() -> ConfigManager:
    """ConfigManager с mock-ConfigStore."""
    store = MagicMock()
    store.get.return_value = None
    store.list_keys.return_value = []

    sr = MagicMock()
    sr.config_store = store

    return ConfigManager(manager_name="TestCM", shared_resources=sr)


# ---------------------------------------------------------------------------
# create_config / get_config / has_config / list_configs
# ---------------------------------------------------------------------------

def test_create_config_returns_config(cm):
    cfg = cm.create_config("app", initial_data={"debug": False})
    assert isinstance(cfg, Config)
    assert cfg.get("debug") is False


def test_create_config_idempotent(cm):
    c1 = cm.create_config("app")
    c2 = cm.create_config("app")
    assert c1 is c2


def test_get_config(cm):
    cm.create_config("app")
    assert cm.get_config("app") is not None
    assert cm.get_config("nonexistent") is None


def test_has_config(cm):
    cm.create_config("app")
    assert cm.has_config("app")
    assert not cm.has_config("nonexistent")


def test_list_configs(cm):
    cm.create_config("a")
    cm.create_config("b")
    assert sorted(cm.list_configs()) == ["a", "b"]


def test_get_all_configs(cm):
    cm.create_config("x", initial_data={"v": 1})
    cm.create_config("y", initial_data={"v": 2})
    all_cfgs = cm.get_all_configs()
    assert set(all_cfgs.keys()) == {"x", "y"}


# ---------------------------------------------------------------------------
# remove_config
# ---------------------------------------------------------------------------

def test_remove_config(cm):
    cm.create_config("app")
    assert cm.remove_config("app")
    assert not cm.has_config("app")


def test_remove_nonexistent(cm):
    assert not cm.remove_config("nonexistent")


# ---------------------------------------------------------------------------
# initialize / shutdown
# ---------------------------------------------------------------------------

def test_initialize(cm):
    assert cm.initialize()
    assert cm.is_initialized


def test_shutdown_clears_configs(cm):
    cm.create_config("app")
    cm.initialize()
    assert cm.shutdown()
    assert not cm.is_initialized
    assert cm.list_configs() == []


# ---------------------------------------------------------------------------
# sync_config / load_config_from_storage
# ---------------------------------------------------------------------------

def test_sync_config(cm_with_store):
    store = cm_with_store._shared_resources.config_store
    cm_with_store.create_config("svc", initial_data={"key": "val"})
    result = cm_with_store.sync_config("svc")
    assert result
    store.store.assert_called_once_with("svc", {"key": "val"})


def test_sync_config_missing_config(cm_with_store):
    assert not cm_with_store.sync_config("ghost")


def test_sync_config_no_shared_resources(cm):
    cm.create_config("app")
    assert not cm.sync_config("app")


def test_load_config_from_storage(cm_with_store):
    store = cm_with_store._shared_resources.config_store
    store.get.return_value = {"host": "db.local"}
    result = cm_with_store.load_config_from_storage("db")
    assert result
    assert cm_with_store.has_config("db")
    assert cm_with_store.get_config("db").get("host") == "db.local"


def test_load_config_from_storage_not_found(cm_with_store):
    store = cm_with_store._shared_resources.config_store
    store.get.return_value = None
    assert not cm_with_store.load_config_from_storage("missing")


def test_load_config_from_storage_updates_existing(cm_with_store):
    store = cm_with_store._shared_resources.config_store
    store.get.return_value = {"k": "new"}
    cm_with_store.create_config("svc", initial_data={"k": "old"})
    cm_with_store.load_config_from_storage("svc")
    assert cm_with_store.get_config("svc").get("k") == "new"


def test_load_no_shared_resources(cm):
    assert not cm.load_config_from_storage("any")
