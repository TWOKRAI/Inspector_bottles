"""test_display_state_adapter.py -- Unit-тесты DisplayStateAdapter.

Проверяют:
1. Конструктор с registry
2. isinstance IStateAdapter
3. bind+connect → proxy.subscribe вызван
4. sync_domain_to_state → proxy.set ≥4 раз (2 × status + 2 × config)
5. _mark_pending вызывается ПЕРЕД каждым proxy.set (anti-loop)
6. disconnect → proxy.unsubscribe вызван
7. connect без bind (proxy=None) → no-op, без исключений

Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md Task 4.8
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry
from multiprocess_framework.modules.state_store_module.adapters import IStateAdapter
from multiprocess_prototype.backend.state.adapters.display_state_adapter import (
    DisplayStateAdapter,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_entry(display_id: str = "main") -> DisplayEntry:
    """Создать DisplayEntry-заглушку."""
    return DisplayEntry(
        id=display_id,
        name=f"Дисплей {display_id}",
        width=1280,
        height=720,
        format="BGR",
        fps_limit=30.0,
        ring_buffer_blocks=3,
    )


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очистить singleton DisplayRegistry перед каждым тестом."""
    DisplayRegistry().clear()
    yield
    DisplayRegistry().clear()


@pytest.fixture()
def registry() -> DisplayRegistry:
    return DisplayRegistry()


@pytest.fixture()
def mock_proxy() -> MagicMock:
    proxy = MagicMock()
    proxy.subscribe.return_value = "sub-display-001"
    return proxy


@pytest.fixture()
def adapter(registry: DisplayRegistry, mock_proxy: MagicMock) -> DisplayStateAdapter:
    return DisplayStateAdapter(
        registry=registry,
        state_proxy=mock_proxy,
    )


# ---------------------------------------------------------------------------
# Тест 1: Конструктор без исключений
# ---------------------------------------------------------------------------


def test_construct_with_registry(registry: DisplayRegistry):
    """DisplayStateAdapter(registry=DisplayRegistry()) — без исключений."""
    adapter = DisplayStateAdapter(registry=registry)
    assert adapter is not None


# ---------------------------------------------------------------------------
# Тест 2: isinstance IStateAdapter
# ---------------------------------------------------------------------------


def test_is_instance_of_istateadapter(adapter: DisplayStateAdapter):
    """isinstance(adapter, IStateAdapter) → True (runtime_checkable Protocol)."""
    assert isinstance(adapter, IStateAdapter)


# ---------------------------------------------------------------------------
# Тест 3: bind+connect → proxy.subscribe вызван
# ---------------------------------------------------------------------------


def test_bind_connect_subscribes(registry: DisplayRegistry, mock_proxy: MagicMock):
    """bind(proxy) + connect() → proxy.subscribe('displays.*.status', ...) вызван."""
    adapter = DisplayStateAdapter(registry=registry)
    adapter.bind(mock_proxy)
    adapter.connect()

    mock_proxy.subscribe.assert_called_once()
    args, kwargs = mock_proxy.subscribe.call_args
    assert args[0] == "displays.*.status"
    assert adapter.is_connected


# ---------------------------------------------------------------------------
# Тест 4: sync_domain_to_state → proxy.set ≥4 раз (2 дисплея × 2 пути)
# ---------------------------------------------------------------------------


def test_sync_domain_to_state(
    adapter: DisplayStateAdapter,
    registry: DisplayRegistry,
    mock_proxy: MagicMock,
):
    """2 дисплея в registry → sync_domain_to_state() → proxy.set вызван ≥4 раза."""
    registry.register(_make_entry("main"))
    registry.register(_make_entry("debug"))

    adapter.sync_domain_to_state()

    # 2 дисплея × 2 пути (status + config) = минимум 4 вызова
    assert mock_proxy.set.call_count >= 4

    # Проверяем что status-пути присутствуют в вызовах
    called_paths = [c.args[0] for c in mock_proxy.set.call_args_list]
    assert any("displays.main.status" in p for p in called_paths)
    assert any("displays.debug.status" in p for p in called_paths)
    assert any("displays.main.config" in p for p in called_paths)
    assert any("displays.debug.config" in p for p in called_paths)


# ---------------------------------------------------------------------------
# Тест 5: _mark_pending вызывается ПЕРЕД каждым proxy.set (anti-loop)
# ---------------------------------------------------------------------------


def test_sync_marks_pending_anti_loop(
    adapter: DisplayStateAdapter,
    registry: DisplayRegistry,
    mock_proxy: MagicMock,
):
    """_mark_pending вызывается ДО каждого proxy.set — anti-loop защита."""
    registry.register(_make_entry("main"))

    call_order: list[str] = []

    # Перехватываем вызовы _mark_pending через side_effect
    original_mark = adapter._mark_pending

    def _mark_wrapper(path: str) -> None:
        call_order.append(f"mark:{path}")
        original_mark(path)

    adapter._mark_pending = _mark_wrapper  # type: ignore[method-assign]

    # Перехватываем вызовы proxy.set
    original_set = mock_proxy.set.side_effect

    def _set_wrapper(path: str, value: object) -> None:
        call_order.append(f"set:{path}")
        if original_set is not None:
            original_set(path, value)

    mock_proxy.set.side_effect = _set_wrapper

    adapter.sync_domain_to_state()

    # Для каждого set-пути должен быть предшествующий mark
    set_paths = [e.split(":", 1)[1] for e in call_order if e.startswith("set:")]
    mark_paths = [e.split(":", 1)[1] for e in call_order if e.startswith("mark:")]

    # Каждый set-путь должен быть помечен
    for sp in set_paths:
        assert sp in mark_paths, f"mark_pending НЕ вызван перед set({sp!r})"

    # Для каждого set-пути его mark идёт раньше в call_order
    for sp in set_paths:
        mark_idx = next(i for i, e in enumerate(call_order) if e == f"mark:{sp}")
        set_idx = next(i for i, e in enumerate(call_order) if e == f"set:{sp}")
        assert mark_idx < set_idx, f"mark({sp}) должен быть раньше set({sp})"


# ---------------------------------------------------------------------------
# Тест 6: disconnect → proxy.unsubscribe вызван
# ---------------------------------------------------------------------------


def test_disconnect_unsubscribes(adapter: DisplayStateAdapter, mock_proxy: MagicMock):
    """После connect + disconnect → proxy.unsubscribe вызван."""
    adapter.connect()
    adapter.disconnect()

    mock_proxy.unsubscribe.assert_called_once_with("sub-display-001")
    assert not adapter.is_connected
    assert len(adapter._sub_ids) == 0


# ---------------------------------------------------------------------------
# Тест 7: proxy=None → connect() no-op, без исключений
# ---------------------------------------------------------------------------


def test_proxy_none_no_op(registry: DisplayRegistry):
    """connect() без bind (proxy=None) — не падает, остаётся не connected."""
    adapter = DisplayStateAdapter(registry=registry, state_proxy=None)
    # Не должно упасть
    adapter.connect()
    assert not adapter.is_connected
