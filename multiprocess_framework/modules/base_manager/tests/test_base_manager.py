"""
Тесты BaseManager.

Покрывает: жизненный цикл, адаптеры, события, статистику, диагностику,
           isinstance по IBaseManager, pickle-совместимость.
"""

import pickle
import pytest

from ..core.base_manager import BaseManager
from ..interfaces import IBaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ConcreteManager(BaseManager):
    """Минимальная конкретная реализация BaseManager для тестов."""

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True


class MockAdapter:
    """Минимальный адаптер для тестов."""

    def __init__(self):
        self.manager = None
        self._initialized = False

    def setup(self) -> bool:
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        return self._initialized

    def get_stats(self) -> dict:
        return {"type": "MockAdapter"}


# ---------------------------------------------------------------------------
# TestBaseManager
# ---------------------------------------------------------------------------

class TestBaseManager:

    def test_creation_defaults(self):
        m = ConcreteManager("test_manager")
        assert m.manager_name == "test_manager"
        assert m.is_initialized is False
        assert m.process is None
        assert m.list_adapters() == []

    def test_creation_with_process(self):
        process = object()
        m = ConcreteManager("test_manager", process=process)
        assert m.process is process

    def test_initialize(self):
        m = ConcreteManager("test_manager")
        assert m.initialize() is True
        assert m.is_initialized is True

    def test_shutdown(self):
        m = ConcreteManager("test_manager")
        m.initialize()
        assert m.shutdown() is True
        assert m.is_initialized is False

    # ---- Адаптеры ----

    def test_attach_adapter_with_explicit_name(self):
        m = ConcreteManager("test_manager")
        adapter = MockAdapter()
        assert m.attach_adapter(adapter, name="mock") is True
        assert m.has_adapter("mock")
        assert m.get_adapter("mock") is adapter

    def test_attach_adapter_none_returns_false(self):
        m = ConcreteManager("test_manager")
        assert m.attach_adapter(None) is False

    def test_attach_adapter_sets_back_reference(self):
        m = ConcreteManager("test_manager")
        adapter = MockAdapter()
        m.attach_adapter(adapter, name="mock")
        assert adapter.manager is m

    def test_get_adapter_first_when_no_name(self):
        m = ConcreteManager("test_manager")
        adapter = MockAdapter()
        m.attach_adapter(adapter, name="first")
        assert m.get_adapter() is adapter

    def test_get_adapter_nonexistent_returns_none(self):
        m = ConcreteManager("test_manager")
        assert m.get_adapter("nonexistent") is None

    def test_list_adapters(self):
        m = ConcreteManager("test_manager")
        m.attach_adapter(MockAdapter(), name="a1")
        m.attach_adapter(MockAdapter(), name="a2")
        adapters = m.list_adapters()
        assert "a1" in adapters
        assert "a2" in adapters
        assert len(adapters) == 2

    def test_detach_adapter(self):
        m = ConcreteManager("test_manager")
        m.attach_adapter(MockAdapter(), name="mock")
        assert m.detach_adapter("mock") is True
        assert not m.has_adapter("mock")

    def test_detach_nonexistent_returns_false(self):
        m = ConcreteManager("test_manager")
        assert m.detach_adapter("nonexistent") is False

    def test_no_magic_getattr_for_adapters(self):
        """Адаптеры больше не доступны через magic __getattr__; только get_adapter()."""
        m = ConcreteManager("test_manager")
        adapter = MockAdapter()
        m.attach_adapter(adapter, name="mock")
        # Явный доступ работает
        assert m.get_adapter("mock") is adapter
        # Magic-доступ НЕ работает — чистый AttributeError
        with pytest.raises(AttributeError):
            _ = m.mock

    def test_attribute_error_for_nonexistent(self):
        m = ConcreteManager("test_manager")
        with pytest.raises(AttributeError):
            _ = m.nonexistent_adapter

    # ---- Статистика ----

    def test_get_stats_keys(self):
        m = ConcreteManager("test_manager")
        m.attach_adapter(MockAdapter(), name="mock")
        stats = m.get_stats()

        assert stats["manager_name"] == "test_manager"
        assert stats["is_initialized"] is False
        assert "mock" in stats["adapters"]
        assert "adapters_info" in stats
        assert "type" in stats["adapters_info"]["mock"]

    def test_get_stats_no_process(self):
        m = ConcreteManager("test_manager")
        assert m.get_stats()["process_name"] == "standalone"

    # ---- Диагностика ----

    def test_get_debug_info_keys(self):
        m = ConcreteManager("test_manager")
        info = m.get_debug_info()
        assert "manager_name" in info
        assert "is_initialized" in info
        assert "adapters" in info
        assert "available_methods" in info

    def test_str_repr(self):
        m = ConcreteManager("test_manager")
        s = str(m)
        assert "test_manager" in s
        assert "False" in s

    # ---- Контракт IBaseManager ----

    def test_isinstance_ibasemanager(self):
        m = ConcreteManager("test_manager")
        assert isinstance(m, IBaseManager)

    # ---- Pickle ----

    def test_pickle_roundtrip(self):
        m = ConcreteManager("test_manager")
        m.initialize()
        m.attach_adapter(MockAdapter(), name="mock")

        data = pickle.dumps(m)
        m2 = pickle.loads(data)

        assert m2.manager_name == "test_manager"
        assert m2.is_initialized is True
