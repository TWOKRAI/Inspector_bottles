"""Тесты адаптеров."""
import pytest

from Services.sql.core.adapter_factory import create_sync_adapter, create_async_adapter
from Services.sql.configs import SQLManagerConfig

try:
    import pytest_asyncio  # noqa: F401
    HAS_ASYNCIO = True
except ImportError:
    HAS_ASYNCIO = False

skip_no_asyncio = pytest.mark.skipif(
    not HAS_ASYNCIO, reason="pytest-asyncio not installed"
)


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
    @skip_no_asyncio
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
