"""test_service_state_adapter.py -- Unit-тесты ServiceStateAdapter.

Проверяют:
1. bind/connect создают подписку на services.*.status
2. disconnect/unbind очищают подписки
3. sync_domain_to_state записывает lifecycle всех сервисов
4. sync_state_to_domain обновляет lifecycle из state
5. callback _on_state_deltas обновляет lifecycle
6. anti-loop: эхо от собственного set() не обновляет registry
7. proxy=None -- no-op без исключений
8. неизвестный сервис в state -- тихо игнорируется
9. невалидный status -- тихо игнорируется

Refs: plans/prototype-skeleton-2026-05/phase-3-service-registry.md Task 3.5
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.service_module import (
    ServiceEntry,
    ServiceLifecycle,
    ServiceRegistry,
)
from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_prototype.backend.state.adapters.service_state_adapter import (
    ServiceStateAdapter,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


class _DummyService:
    """Минимальный сервис-заглушка для тестов."""

    name: str = "dummy"

    def start(self, config: dict) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.name, "status": "ready"}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очистить singleton ServiceRegistry перед каждым тестом."""
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


@pytest.fixture()
def registry() -> ServiceRegistry:
    return ServiceRegistry()


@pytest.fixture()
def mock_proxy() -> MagicMock:
    proxy = MagicMock()
    proxy.subscribe.return_value = "sub-001"
    return proxy


@pytest.fixture()
def adapter(registry: ServiceRegistry, mock_proxy: MagicMock) -> ServiceStateAdapter:
    return ServiceStateAdapter(
        registry=registry,
        state_proxy=mock_proxy,
    )


def _make_entry(name: str, lifecycle: ServiceLifecycle = ServiceLifecycle.READY) -> ServiceEntry:
    """Создать ServiceEntry-заглушку."""
    return ServiceEntry(name=name, cls=_DummyService, lifecycle=lifecycle)


def _make_delta(path: str, new_value: str, old_value: str = "ready") -> Delta:
    """Создать Delta-заглушку."""
    return Delta(path=path, old_value=old_value, new_value=new_value, source="test")


# ---------------------------------------------------------------------------
# Тест 1: bind + connect подписывается на state
# ---------------------------------------------------------------------------


def test_connect_subscribes_to_state(adapter: ServiceStateAdapter, mock_proxy: MagicMock):
    """После connect() proxy.subscribe вызван с pattern 'services.*.status'."""
    adapter.connect()

    mock_proxy.subscribe.assert_called_once()
    args, kwargs = mock_proxy.subscribe.call_args
    assert args[0] == "services.*.status"
    assert adapter.is_connected
    assert len(adapter._sub_ids) == 1
    assert adapter._sub_ids[0] == "sub-001"


# ---------------------------------------------------------------------------
# Тест 2: disconnect очищает подписки
# ---------------------------------------------------------------------------


def test_disconnect_unsubscribes(adapter: ServiceStateAdapter, mock_proxy: MagicMock):
    """После disconnect() все sub_ids очищены, proxy.unsubscribe вызван."""
    adapter.connect()
    adapter.disconnect()

    mock_proxy.unsubscribe.assert_called_once_with("sub-001")
    assert len(adapter._sub_ids) == 0
    assert not adapter.is_connected


# ---------------------------------------------------------------------------
# Тест 3: sync_domain_to_state записывает все сервисы
# ---------------------------------------------------------------------------


def test_sync_domain_to_state_writes_all(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
    mock_proxy: MagicMock,
):
    """Registry с 3 сервисами разных lifecycle -> proxy.set вызван 3 раза."""
    registry.register(_make_entry("sql", ServiceLifecycle.READY))
    registry.register(_make_entry("auth", ServiceLifecycle.RUNNING))
    registry.register(_make_entry("webcam", ServiceLifecycle.STOPPED))

    adapter.sync_domain_to_state()

    assert mock_proxy.set.call_count == 3
    # Проверим конкретные вызовы (порядок может отличаться)
    calls = {c.args[0]: c.args[1] for c in mock_proxy.set.call_args_list}
    assert calls["services.sql.status"] == "ready"
    assert calls["services.auth.status"] == "running"
    assert calls["services.webcam.status"] == "stopped"


# ---------------------------------------------------------------------------
# Тест 4: sync_state_to_domain обновляет lifecycle в registry
# ---------------------------------------------------------------------------


def test_sync_state_to_domain_updates_registry(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
    mock_proxy: MagicMock,
):
    """State содержит services.foo.status='running', registry имеет READY -> RUNNING."""
    registry.register(_make_entry("foo", ServiceLifecycle.READY))

    mock_proxy.get.return_value = {
        "foo": {"status": "running"},
    }

    adapter.sync_state_to_domain()

    entry = registry.get("foo")
    assert entry is not None
    assert entry.lifecycle == ServiceLifecycle.RUNNING


# ---------------------------------------------------------------------------
# Тест 5: callback _on_state_deltas обновляет lifecycle
# ---------------------------------------------------------------------------


def test_on_state_deltas_updates_lifecycle(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
):
    """Внешнее изменение services.foo.status='stopped' -> entry.lifecycle = STOPPED."""
    registry.register(_make_entry("foo", ServiceLifecycle.RUNNING))

    deltas = [_make_delta("services.foo.status", "stopped", "running")]
    adapter._on_state_deltas(deltas)

    entry = registry.get("foo")
    assert entry is not None
    assert entry.lifecycle == ServiceLifecycle.STOPPED


# ---------------------------------------------------------------------------
# Тест 6: anti-loop -- эхо от собственного set() игнорируется
# ---------------------------------------------------------------------------


def test_anti_loop_skips_own_change(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
):
    """_mark_pending(path) + _on_state_deltas -> registry НЕ обновляется (это наше эхо)."""
    registry.register(_make_entry("foo", ServiceLifecycle.READY))

    path = "services.foo.status"
    adapter._mark_pending(path)

    deltas = [_make_delta(path, "running", "ready")]
    adapter._on_state_deltas(deltas)

    # lifecycle не изменился -- эхо было пропущено
    entry = registry.get("foo")
    assert entry is not None
    assert entry.lifecycle == ServiceLifecycle.READY


# ---------------------------------------------------------------------------
# Тест 7: proxy=None -- sync_domain_to_state() без исключений
# ---------------------------------------------------------------------------


def test_proxy_none_sync_domain_no_crash(registry: ServiceRegistry):
    """sync_domain_to_state() при proxy=None -> no-op, без исключений."""
    adapter = ServiceStateAdapter(registry=registry, state_proxy=None)
    registry.register(_make_entry("foo"))

    # Не должно упасть
    adapter.sync_domain_to_state()


# ---------------------------------------------------------------------------
# Тест 8: proxy=None -- sync_state_to_domain() без исключений
# ---------------------------------------------------------------------------


def test_proxy_none_sync_state_no_crash(registry: ServiceRegistry):
    """sync_state_to_domain() при proxy=None -> no-op, без исключений."""
    adapter = ServiceStateAdapter(registry=registry, state_proxy=None)
    adapter.sync_state_to_domain()


# ---------------------------------------------------------------------------
# Тест 9: неизвестный сервис в state -- тихо игнорируется
# ---------------------------------------------------------------------------


def test_state_change_unknown_service_ignored(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
):
    """Изменение services.unknown.status (нет в registry) -> no-op."""
    registry.register(_make_entry("foo"))

    deltas = [_make_delta("services.unknown.status", "running")]
    # Не должно упасть
    adapter._on_state_deltas(deltas)

    # foo не изменился
    entry = registry.get("foo")
    assert entry is not None
    assert entry.lifecycle == ServiceLifecycle.READY


# ---------------------------------------------------------------------------
# Тест 10: невалидный status в state -- тихо игнорируется
# ---------------------------------------------------------------------------


def test_state_change_invalid_status_ignored(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
):
    """services.foo.status = 'weird_value' -> ValueError поймано, lifecycle не изменён."""
    registry.register(_make_entry("foo", ServiceLifecycle.READY))

    deltas = [_make_delta("services.foo.status", "weird_value")]
    adapter._on_state_deltas(deltas)

    entry = registry.get("foo")
    assert entry is not None
    assert entry.lifecycle == ServiceLifecycle.READY


# ---------------------------------------------------------------------------
# Тест 11: sync_domain_to_state с пустым registry -- no-op
# ---------------------------------------------------------------------------


def test_sync_domain_to_state_empty_registry(
    adapter: ServiceStateAdapter,
    mock_proxy: MagicMock,
):
    """Пустой registry -> proxy.set() не вызывается."""
    adapter.sync_domain_to_state()
    mock_proxy.set.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 12: anti-loop -- pending-путь очищается после однократного эхо
# ---------------------------------------------------------------------------


def test_anti_loop_clears_after_echo(
    adapter: ServiceStateAdapter,
    registry: ServiceRegistry,
):
    """Второй вызов _on_state_deltas с тем же путём -- обрабатывается (pending снят)."""
    registry.register(_make_entry("foo", ServiceLifecycle.READY))

    path = "services.foo.status"
    adapter._mark_pending(path)

    # Первый вызов -- эхо, пропускаем
    adapter._on_state_deltas([_make_delta(path, "running")])
    assert registry.get("foo").lifecycle == ServiceLifecycle.READY

    # Второй вызов -- реальное внешнее изменение, обрабатываем
    adapter._on_state_deltas([_make_delta(path, "stopped")])
    assert registry.get("foo").lifecycle == ServiceLifecycle.STOPPED
