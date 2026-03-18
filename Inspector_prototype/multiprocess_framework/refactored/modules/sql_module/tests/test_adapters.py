"""Тесты адаптеров."""
import pytest

from sql_module.core.engine_factory import create_sync_adapter, create_async_adapter
from sql_module.config import SQLManagerConfig


class TestSyncAdapters:
    def test_sqlite_sync(self):
        cfg = SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite")
        adapter = create_sync_adapter(cfg)
        adapter.setup()
        adapter.execute("CREATE TABLE t (x INT)")
        adapter.execute("INSERT INTO t VALUES (1)")
        rows = adapter.query("SELECT * FROM t")
        assert rows == [{"x": 1}]
        adapter.dispose()

    def test_fork_safe_null_pool(self, monkeypatch):
        monkeypatch.setenv("INSPECTOR_MULTIPROCESS", "1")
        cfg = SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite")
        adapter = create_sync_adapter(cfg)
        adapter.setup()
        rows = adapter.query("SELECT 1 as x")
        assert rows == [{"x": 1}]
        adapter.dispose()


class TestAsyncAdapters:
    @pytest.mark.asyncio
    async def test_sqlite_async(self):
        cfg = SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite")
        adapter = create_async_adapter(cfg)
        adapter.setup()
        await adapter.execute("CREATE TABLE t (x INT)")
        await adapter.execute("INSERT INTO t VALUES (1)")
        rows = await adapter.query("SELECT * FROM t")
        assert rows == [{"x": 1}]
        adapter.dispose()
