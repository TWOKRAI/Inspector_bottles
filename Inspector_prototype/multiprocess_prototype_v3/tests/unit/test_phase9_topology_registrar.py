"""Тесты для apply_topology() — Task 9.5 часть C.

Проверяем императивное применение RouterTopology к IRouterManager:
  - Регистрация каналов и маршрутов
  - Diff: удаление устаревших каналов
  - Broadcast-маршруты
  - Счётчики ApplyResult
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

from multiprocess_framework.modules.router_module.interfaces import IRouterManager

from multiprocess_prototype_v3.services.processor.topology.builder import (
    ChannelSpec,
    EdgeSpec,
    RouterTopology,
)
from multiprocess_prototype_v3.services.processor.topology.registrar import (
    ApplyResult,
    apply_topology,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _mock_router() -> MagicMock:
    """Создать мок IRouterManager с настроенными return values."""
    router = MagicMock(spec=IRouterManager)
    router.register_channel.return_value = True
    router.unregister_channel.return_value = True
    router.register_route.return_value = True
    router.register_broadcast_route.return_value = True
    return router


def _simple_topology() -> RouterTopology:
    """Топология: 2 канала, 1 edge (webcam.out → resize.in), без broadcast."""
    return RouterTopology(
        channels=[
            ChannelSpec(channel_name="webcam.out", process_id="processor", payload_kind="image"),
            ChannelSpec(channel_name="resize.out", process_id="processor", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(
                source_channel="webcam.out",
                target_node_id="resize",
                target_input_port="in",
                cross_process=False,
            ),
        ],
        broadcast_routes={},
        process_ids=["processor"],
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_apply_topology_registers_channels_and_routes():
    """apply_topology регистрирует каналы и маршруты через router API."""
    router = _mock_router()
    topo = _simple_topology()

    result = apply_topology(router, topo)

    # 2 канала зарегистрированы
    assert router.register_channel.call_count == 2

    # Проверяем имена зарегистрированных каналов
    channel_names = [
        c.args[0].name for c in router.register_channel.call_args_list
    ]
    assert "webcam.out" in channel_names
    assert "resize.out" in channel_names

    # 1 route зарегистрирован (не broadcast)
    assert router.register_route.call_count == 1
    route_call = router.register_route.call_args
    assert route_call.kwargs.get("key") == "webcam.out" or route_call[1].get("key") == "webcam.out"

    # Нет broadcast
    assert router.register_broadcast_route.call_count == 0

    # Счётчики
    assert result.channels_added == 2
    assert result.routes_added == 1
    assert result.broadcast_routes_added == 0


def test_apply_topology_diff_removes_old_and_adds_new():
    """applied previous → applied new (с убранным каналом) → unregister_channel."""
    router = _mock_router()

    previous = RouterTopology(
        channels=[
            ChannelSpec(channel_name="webcam.out", process_id="processor", payload_kind="image"),
            ChannelSpec(channel_name="resize.out", process_id="processor", payload_kind="image"),
            ChannelSpec(channel_name="clahe.out", process_id="processor", payload_kind="image"),
        ],
        edges=[],
        broadcast_routes={},
        process_ids=["processor"],
    )

    # Новая топология: clahe.out удалён
    current = RouterTopology(
        channels=[
            ChannelSpec(channel_name="webcam.out", process_id="processor", payload_kind="image"),
            ChannelSpec(channel_name="resize.out", process_id="processor", payload_kind="image"),
        ],
        edges=[],
        broadcast_routes={},
        process_ids=["processor"],
    )

    result = apply_topology(router, current, previous=previous)

    # clahe.out должен быть unregister'ен
    router.unregister_channel.assert_called_once_with("clahe.out")
    assert result.channels_removed == 1

    # Новые каналы зарегистрированы (replacement для существующих — ok)
    assert result.channels_added == 2


def test_apply_topology_broadcast():
    """register_broadcast_route вызывается для fan-out."""
    router = _mock_router()

    topo = RouterTopology(
        channels=[
            ChannelSpec(channel_name="webcam.out", process_id="p", payload_kind="image"),
            ChannelSpec(channel_name="resize_b.out", process_id="p", payload_kind="image"),
            ChannelSpec(channel_name="resize_c.out", process_id="p", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(source_channel="webcam.out", target_node_id="resize_b", target_input_port="in", cross_process=False),
            EdgeSpec(source_channel="webcam.out", target_node_id="resize_c", target_input_port="in", cross_process=False),
        ],
        broadcast_routes={
            "webcam.out": ["resize_b.in", "resize_c.in"],
        },
        process_ids=["p"],
    )

    result = apply_topology(router, topo)

    # broadcast зарегистрирован
    assert router.register_broadcast_route.call_count == 1
    bc_call = router.register_broadcast_route.call_args
    assert bc_call.kwargs.get("key") == "webcam.out" or bc_call[1].get("key") == "webcam.out"

    # Одиночные routes НЕ зарегистрированы для broadcast-edges
    # (webcam.out в broadcast_routes → skip в _register_routes)
    assert router.register_route.call_count == 0

    assert result.broadcast_routes_added == 1


def test_apply_result_counters():
    """Корректные счётчики в ApplyResult."""
    router = _mock_router()

    topo = RouterTopology(
        channels=[
            ChannelSpec(channel_name="a.out", process_id="p", payload_kind="image"),
            ChannelSpec(channel_name="b.out", process_id="p", payload_kind="image"),
            ChannelSpec(channel_name="c.out", process_id="p", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(source_channel="a.out", target_node_id="b", target_input_port="in", cross_process=False),
            EdgeSpec(source_channel="b.out", target_node_id="c", target_input_port="in", cross_process=False),
        ],
        broadcast_routes={},
        process_ids=["p"],
    )

    result = apply_topology(router, topo)

    assert isinstance(result, ApplyResult)
    assert result.channels_added == 3
    assert result.channels_removed == 0
    assert result.routes_added == 2
    assert result.broadcast_routes_added == 0


def test_apply_topology_empty():
    """Пустая топология → никаких вызовов к router."""
    router = _mock_router()
    topo = RouterTopology()

    result = apply_topology(router, topo)

    assert router.register_channel.call_count == 0
    assert router.register_route.call_count == 0
    assert router.register_broadcast_route.call_count == 0

    assert result.channels_added == 0
    assert result.routes_added == 0


def test_apply_topology_diff_no_previous_no_unregister():
    """Без previous → никаких unregister_channel."""
    router = _mock_router()
    topo = _simple_topology()

    apply_topology(router, topo, previous=None)

    router.unregister_channel.assert_not_called()
