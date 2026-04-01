"""
Тесты для config_store (хранилище конфигов процессов).
"""

import pickle
import pytest
from ..config_store import ConfigStore


@pytest.fixture
def store():
    return ConfigStore()


class TestConfigStore:
    def test_store_and_get(self, store):
        store.store("p1", {"key": "value"})
        cfg = store.get("p1")
        assert cfg == {"key": "value"}

    def test_get_returns_copy(self, store):
        store.store("p1", {"key": "value"})
        cfg = store.get("p1")
        cfg["key"] = "modified"
        assert store.get("p1")["key"] == "value"

    def test_get_missing_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_has(self, store):
        assert not store.has("p1")
        store.store("p1", {})
        assert store.has("p1")

    def test_remove(self, store):
        store.store("p1", {})
        assert store.remove("p1") is True
        assert store.has("p1") is False

    def test_remove_missing_returns_false(self, store):
        assert store.remove("nonexistent") is False

    def test_get_all(self, store):
        store.store("p1", {"a": 1})
        store.store("p2", {"b": 2})
        all_cfgs = store.get_all()
        assert set(all_cfgs.keys()) == {"p1", "p2"}

    def test_get_all_returns_copies(self, store):
        store.store("p1", {"a": 1})
        all_cfgs = store.get_all()
        all_cfgs["p1"]["a"] = 999
        assert store.get("p1")["a"] == 1

    def test_overwrite(self, store):
        store.store("p1", {"v": 1})
        store.store("p1", {"v": 2})
        assert store.get("p1")["v"] == 2

    def test_store_requires_dict(self, store):
        with pytest.raises(TypeError):
            store.store("p1", "not_a_dict")

    def test_len(self, store):
        assert len(store) == 0
        store.store("p1", {})
        assert len(store) == 1

    def test_contains(self, store):
        store.store("p1", {})
        assert "p1" in store
        assert "p2" not in store

    def test_pickle_roundtrip(self, store):
        store.store("p1", {"queues": {"system": {"maxsize": 100}}})
        store2 = pickle.loads(pickle.dumps(store))
        assert store2.get("p1") == {"queues": {"system": {"maxsize": 100}}}
