"""Тесты cross-process топологии — Task 9.6.

Проверяем:
  - process_groups корректно группируют ноды по process_id
  - process_channels корректно отображают каналы процессов
  - SHM middleware подключается для cross-process edge с payload_kind='image'
  - SHM middleware НЕ подключается для detections
  - Динамические процессы: создание новых, остановка устаревших, no-op
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

from multiprocess_framework.modules.router_module.interfaces import IRouterManager
from multiprocess_framework.modules.process_manager_module.interfaces import IProcessRegistry

from multiprocess_prototype_v3.registers.pipeline.processing_node import (
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype_v3.registers.pipeline.schemas import (
    CameraNode,
    Pipeline,
    RegionNode,
)
from multiprocess_prototype_v3.registers.processor.catalog.schemas import (
    Port,
    ProcessingOperationDef,
)
from multiprocess_prototype_v3.services.processor.topology.builder import (
    ChannelSpec,
    EdgeSpec,
    RouterTopology,
    to_router_topology,
)
from multiprocess_prototype_v3.services.processor.topology.registrar import (
    ApplyResult,
    apply_topology,
    _reset_shm_middleware_cache,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Минимальный каталог: webcam_input, resize, clahe, threshold."""
    return {
        "webcam_input": ProcessingOperationDef(
            name="Webcam", type_key="webcam_input", params_schema="stub",
            module_path="stub", input_ports=[],
            output_ports=[Port(name="out", data_type="image")], category="Input",
        ),
        "resize": ProcessingOperationDef(
            name="Resize", type_key="resize", params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")], category="Preprocess",
        ),
        "clahe": ProcessingOperationDef(
            name="CLAHE", type_key="clahe", params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")], category="Preprocess",
        ),
        "threshold": ProcessingOperationDef(
            name="Threshold", type_key="threshold", params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")], category="Preprocess",
        ),
        "color_detection": ProcessingOperationDef(
            name="Color detect", type_key="color_detection", params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="detections", data_type="detections")],
            category="Detect",
        ),
    }


def _mock_router() -> MagicMock:
    """Мок IRouterManager."""
    router = MagicMock(spec=IRouterManager)
    router.register_channel.return_value = True
    router.unregister_channel.return_value = True
    router.register_route.return_value = True
    router.register_broadcast_route.return_value = True
    return router


def _mock_memory_manager() -> MagicMock:
    """Мок MemoryManager с API write_images/read_images/find_free_index."""
    mm = MagicMock()
    mm.write_images.return_value = "shm_actual_name"
    mm.read_images.return_value = [None]
    mm.find_free_index.return_value = 0
    return mm


def _mock_process_registry() -> MagicMock:
    """Мок IProcessRegistry."""
    registry = MagicMock(spec=IProcessRegistry)
    registry.create_and_register.return_value = MagicMock()  # Успешное создание
    registry.stop_one.return_value = True
    registry.remove_process.return_value = None
    return registry


# ---------------------------------------------------------------------------
# Тесты: process_groups
# ---------------------------------------------------------------------------


def test_to_topology_groups_by_process_id():
    """Три ноды в двух process_id -> process_groups корректно сгруппированы."""
    catalog = _make_catalog()

    n_in = ProcessingNode(
        node_id="webcam", operation_ref="webcam_input", process_id="proc_A",
    )
    n_rs = ProcessingNode(
        node_id="resize", operation_ref="resize", process_id="proc_A",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe", operation_ref="clahe", process_id="proc_B",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl,
    })})})

    topo = to_router_topology(pipe, catalog)

    assert "proc_A" in topo.process_groups
    assert "proc_B" in topo.process_groups
    assert sorted(topo.process_groups["proc_A"]) == ["resize", "webcam"]
    assert topo.process_groups["proc_B"] == ["clahe"]


def test_to_topology_process_channels_mapping():
    """Проверяем что process_channels корректно отображает каналы каждого процесса."""
    catalog = _make_catalog()

    n_in = ProcessingNode(
        node_id="webcam", operation_ref="webcam_input", process_id="proc_A",
    )
    n_rs = ProcessingNode(
        node_id="resize", operation_ref="resize", process_id="proc_A",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe", operation_ref="clahe", process_id="proc_B",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl,
    })})})

    topo = to_router_topology(pipe, catalog)

    # proc_A владеет каналами webcam.out и resize.out
    assert sorted(topo.process_channels["proc_A"]) == ["resize.out", "webcam.out"]
    # proc_B владеет каналом clahe.out
    assert topo.process_channels["proc_B"] == ["clahe.out"]


# ---------------------------------------------------------------------------
# Тесты: SHM middleware
# ---------------------------------------------------------------------------


def test_cross_process_edge_with_image_payload_attaches_shm_middleware():
    """Cross-process edge с payload_kind='image' -> SHM middleware подключён."""
    _reset_shm_middleware_cache()

    router = _mock_router()
    mm = _mock_memory_manager()

    topo = RouterTopology(
        channels=[
            ChannelSpec(channel_name="resize.out", process_id="proc_A", payload_kind="image"),
            ChannelSpec(channel_name="clahe.out", process_id="proc_B", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(
                source_channel="resize.out",
                target_node_id="clahe",
                target_input_port="in",
                cross_process=True,
            ),
        ],
        broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    result = apply_topology(router, topo, memory_manager=mm)

    # SHM middleware подключён
    assert result.shm_middlewares_added == 1
    # add_send_middleware и add_receive_middleware вызваны по разу
    assert router.add_send_middleware.call_count == 1
    assert router.add_receive_middleware.call_count == 1


def test_cross_process_edge_with_detections_payload_does_not_attach_shm():
    """Cross-process edge с payload_kind='detections' -> SHM middleware НЕ подключается."""
    _reset_shm_middleware_cache()

    router = _mock_router()
    mm = _mock_memory_manager()

    topo = RouterTopology(
        channels=[
            ChannelSpec(channel_name="detector.detections", process_id="proc_A", payload_kind="detections"),
            ChannelSpec(channel_name="sink.out", process_id="proc_B", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(
                source_channel="detector.detections",
                target_node_id="sink",
                target_input_port="in",
                cross_process=True,
            ),
        ],
        broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    result = apply_topology(router, topo, memory_manager=mm)

    # SHM middleware НЕ подключён (detections — лёгкий payload)
    assert result.shm_middlewares_added == 0
    assert router.add_send_middleware.call_count == 0
    assert router.add_receive_middleware.call_count == 0


def test_shm_middleware_no_memory_manager_warning_only():
    """Без memory_manager — SHM middleware не подключается, только warning."""
    _reset_shm_middleware_cache()

    router = _mock_router()

    topo = RouterTopology(
        channels=[
            ChannelSpec(channel_name="resize.out", process_id="proc_A", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(
                source_channel="resize.out",
                target_node_id="clahe",
                target_input_port="in",
                cross_process=True,
            ),
        ],
        broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    # memory_manager=None (по умолчанию)
    result = apply_topology(router, topo)

    assert result.shm_middlewares_added == 0


def test_shm_middleware_cache_prevents_duplicates():
    """Повторный apply_topology не подключает дублирующий SHM middleware."""
    _reset_shm_middleware_cache()

    router = _mock_router()
    mm = _mock_memory_manager()

    topo = RouterTopology(
        channels=[
            ChannelSpec(channel_name="resize.out", process_id="proc_A", payload_kind="image"),
        ],
        edges=[
            EdgeSpec(
                source_channel="resize.out",
                target_node_id="clahe",
                target_input_port="in",
                cross_process=True,
            ),
        ],
        broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    # Первый apply — middleware подключён
    r1 = apply_topology(router, topo, memory_manager=mm)
    assert r1.shm_middlewares_added == 1

    # Второй apply — middleware уже в кеше, не дублируется
    r2 = apply_topology(router, topo, memory_manager=mm, previous=topo)
    assert r2.shm_middlewares_added == 0


# ---------------------------------------------------------------------------
# Тесты: динамические процессы
# ---------------------------------------------------------------------------


def test_apply_topology_creates_new_processes():
    """Topology с 2 process_id, previous пустая -> 2 create_and_register вызова."""
    _reset_shm_middleware_cache()

    router = _mock_router()
    registry = _mock_process_registry()

    topo = RouterTopology(
        channels=[],
        edges=[],
        broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    result = apply_topology(
        router, topo,
        process_registry=registry,
    )

    assert result.processes_created == 2
    assert registry.create_and_register.call_count == 2

    # Проверяем что process_id передан в конфиг
    call_args_list = registry.create_and_register.call_args_list
    created_names = {c.kwargs.get("name") or c[0][0] for c in call_args_list}
    assert created_names == {"proc_A", "proc_B"}


def test_apply_topology_stops_obsolete_processes():
    """previous={p0, p1}, new={p0} -> stop_one(p1) + remove_process(p1)."""
    _reset_shm_middleware_cache()

    router = _mock_router()
    registry = _mock_process_registry()

    previous = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )
    current = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["proc_A"],
    )

    result = apply_topology(
        router, current,
        previous=previous,
        process_registry=registry,
    )

    assert result.processes_stopped == 1
    assert result.processes_created == 0
    registry.stop_one.assert_called_once_with("proc_B", timeout=5.0)
    registry.remove_process.assert_called_once_with("proc_B")


def test_apply_topology_no_op_when_process_set_unchanged():
    """Одинаковый набор process_id -> 0 create, 0 stop."""
    _reset_shm_middleware_cache()

    router = _mock_router()
    registry = _mock_process_registry()

    topo = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    result = apply_topology(
        router, topo,
        previous=topo,
        process_registry=registry,
    )

    assert result.processes_created == 0
    assert result.processes_stopped == 0
    registry.create_and_register.assert_not_called()
    registry.stop_one.assert_not_called()
