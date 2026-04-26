"""Тесты для to_router_topology() — Task 9.5 часть B.

Проверяем трансформацию Pipeline → RouterTopology:
  - Пустой pipeline → пустая топология
  - Простая цепочка → каналы + рёбра
  - Disabled ноды исключаются
  - Fan-out → broadcast_routes
  - Cross-process → EdgeSpec.cross_process
  - channel_prefix → переопределение имени канала
  - Round-trip сериализация
  - Функция не проверяет валидность графа
"""

from __future__ import annotations

import pytest

from multiprocess_prototype_v3.registers.pipeline.processing_node import (
    NodeInput,
    NodeOutput,
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


# ---------------------------------------------------------------------------
# Хелперы: минимальный каталог
# ---------------------------------------------------------------------------


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Минимальный каталог: webcam_input (0→1), resize (1→1), clahe (1→1)."""
    return {
        "webcam_input": ProcessingOperationDef(
            name="Webcam",
            type_key="webcam_input",
            params_schema="stub",
            module_path="stub",
            input_ports=[],
            output_ports=[Port(name="out", data_type="image")],
            category="Input",
        ),
        "resize": ProcessingOperationDef(
            name="Resize",
            type_key="resize",
            params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")],
            category="Preprocess",
        ),
        "clahe": ProcessingOperationDef(
            name="CLAHE",
            type_key="clahe",
            params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")],
            category="Preprocess",
        ),
        "color_detection": ProcessingOperationDef(
            name="Color detect",
            type_key="color_detection",
            params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[
                Port(name="detections", data_type="detections"),
                Port(name="mask", data_type="mask"),
            ],
            category="Detect",
        ),
        "region_splitter": ProcessingOperationDef(
            name="Region splitter",
            type_key="region_splitter",
            params_schema="stub",
            module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[],  # dynamic
            multiplicity="dynamic",
            category="ROI",
        ),
    }


def _make_simple_pipeline() -> tuple[Pipeline, dict[str, ProcessingOperationDef]]:
    """Pipeline: webcam → resize → clahe (без channel_prefix)."""
    catalog = _make_catalog()

    n_in = ProcessingNode(
        node_id="webcam",
        operation_ref="webcam_input",
        inputs=[],
    )
    n_rs = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe",
        operation_ref="clahe",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in,
        "resize": n_rs,
        "clahe": n_cl,
    })})})

    return pipe, catalog


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_to_router_topology_empty_pipeline_returns_empty():
    """Pipeline без камер → RouterTopology с пустыми списками."""
    pipe = Pipeline(cameras={})
    catalog = _make_catalog()

    topo = to_router_topology(pipe, catalog)

    assert topo.channels == []
    assert topo.edges == []
    assert topo.broadcast_routes == {}
    assert topo.process_ids == []


def test_simple_chain_builds_three_channels():
    """Pipeline webcam → resize → clahe → 3 канала (webcam.out, resize.out, clahe.out), 2 edge."""
    pipe, catalog = _make_simple_pipeline()

    topo = to_router_topology(pipe, catalog)

    # 3 ноды × 1 output port = 3 канала
    assert len(topo.channels) == 3

    channel_names = {ch.channel_name for ch in topo.channels}
    assert "webcam.out" in channel_names
    assert "resize.out" in channel_names
    assert "clahe.out" in channel_names

    # 2 edge: webcam.out → resize.in, resize.out → clahe.in
    assert len(topo.edges) == 2

    src_channels = {e.source_channel for e in topo.edges}
    assert "webcam.out" in src_channels
    assert "resize.out" in src_channels

    # Нет broadcast (каждый выход → ровно один вход)
    assert topo.broadcast_routes == {}

    # Один process_id: 'processor' (по умолчанию)
    assert topo.process_ids == ["processor"]


def test_disabled_node_excluded():
    """node.enabled=False → его каналы и edges не попадают в топологию."""
    catalog = _make_catalog()

    n_in = ProcessingNode(node_id="webcam", operation_ref="webcam_input", inputs=[])
    n_rs = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        enabled=False,  # Отключён
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe",
        operation_ref="clahe",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in,
        "resize": n_rs,
        "clahe": n_cl,
    })})})

    topo = to_router_topology(pipe, catalog)

    # resize отключён → его канал resize.out отсутствует
    channel_names = {ch.channel_name for ch in topo.channels}
    assert "resize.out" not in channel_names

    # webcam.out присутствует, clahe.out присутствует
    assert "webcam.out" in channel_names
    assert "clahe.out" in channel_names

    # Edge webcam.out → resize отсутствует (resize disabled, не в all_nodes)
    # Edge resize.out → clahe: source 'resize' disabled, source_node=None → skip
    # Остаётся 0 edges
    assert len(topo.edges) == 0


def test_fan_out_creates_broadcast_route():
    """Нода A с двумя downstream → broadcast_routes."""
    catalog = _make_catalog()

    n_in = ProcessingNode(node_id="webcam", operation_ref="webcam_input", inputs=[])
    n_b = ProcessingNode(
        node_id="resize_b",
        operation_ref="resize",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_c = ProcessingNode(
        node_id="resize_c",
        operation_ref="resize",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in,
        "resize_b": n_b,
        "resize_c": n_c,
    })})})

    topo = to_router_topology(pipe, catalog)

    # Fan-out: webcam.out → [resize_b.in, resize_c.in]
    assert "webcam.out" in topo.broadcast_routes
    targets = topo.broadcast_routes["webcam.out"]
    assert len(targets) == 2
    assert "resize_b.in" in targets
    assert "resize_c.in" in targets


def test_cross_process_edge_marked():
    """Нода A process_id='proc1', нода B process_id='proc2' → EdgeSpec.cross_process=True."""
    catalog = _make_catalog()

    n_in = ProcessingNode(
        node_id="webcam",
        operation_ref="webcam_input",
        process_id="proc1",
        inputs=[],
    )
    n_rs = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        process_id="proc2",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in,
        "resize": n_rs,
    })})})

    topo = to_router_topology(pipe, catalog)

    assert len(topo.edges) == 1
    edge = topo.edges[0]
    assert edge.cross_process is True

    assert sorted(topo.process_ids) == ["proc1", "proc2"]


def test_channel_prefix_overrides_node_id():
    """node.channel_prefix='my_input' → channel_name='my_input.out' вместо '{uuid}.out'."""
    catalog = _make_catalog()

    n_in = ProcessingNode(
        node_id="some_uuid_like_id",
        operation_ref="webcam_input",
        channel_prefix="my_input",
        inputs=[],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "some_uuid_like_id": n_in,
    })})})

    topo = to_router_topology(pipe, catalog)

    assert len(topo.channels) == 1
    assert topo.channels[0].channel_name == "my_input.out"


def test_topology_round_trip_serialization():
    """RouterTopology → model_dump_json → model_validate_json = эквивалент."""
    pipe, catalog = _make_simple_pipeline()
    topo = to_router_topology(pipe, catalog)

    json_str = topo.model_dump_json()
    restored = RouterTopology.model_validate_json(json_str)

    assert len(restored.channels) == len(topo.channels)
    assert len(restored.edges) == len(topo.edges)
    assert restored.broadcast_routes == topo.broadcast_routes
    assert restored.process_ids == topo.process_ids

    # Проверяем содержимое каналов
    orig_names = {ch.channel_name for ch in topo.channels}
    rest_names = {ch.channel_name for ch in restored.channels}
    assert orig_names == rest_names


def test_invalid_pipeline_does_not_raise_but_validate_first():
    """to_router_topology() НЕ проверяет валидность графа.

    Ссылка на несуществующий source → edge просто пропускается
    (source_node is None → continue). Валидация — ответственность
    pipeline.validate_graph() вызванного снаружи.
    """
    catalog = _make_catalog()

    # Нода ссылается на несуществующий source
    n_rs = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        inputs=[NodeInput(source="nonexistent", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "resize": n_rs,
    })})})

    # Не должен бросить исключение
    topo = to_router_topology(pipe, catalog)

    # Edge пропущен (source не найден)
    assert len(topo.edges) == 0
    # Канал resize.out всё равно создан
    assert len(topo.channels) == 1


def test_dynamic_multiplicity_uses_node_outputs():
    """Операция с multiplicity=dynamic (region_splitter): output_ports из каталога пустые,
    используются node.outputs."""
    catalog = _make_catalog()

    n_splitter = ProcessingNode(
        node_id="splitter",
        operation_ref="region_splitter",
        inputs=[],
        outputs=[
            NodeOutput(port_name="region_a"),
            NodeOutput(port_name="region_b"),
        ],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "splitter": n_splitter,
    })})})

    topo = to_router_topology(pipe, catalog)

    channel_names = {ch.channel_name for ch in topo.channels}
    assert "splitter.region_a" in channel_names
    assert "splitter.region_b" in channel_names
    assert len(topo.channels) == 2

    # payload_kind = 'any' для динамических портов
    for ch in topo.channels:
        assert ch.payload_kind == "any"


def test_frame_virtual_source_creates_edge():
    """inp.source == 'frame' → edge с source_channel='frame.out'."""
    catalog = _make_catalog()

    n_rs = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        inputs=[NodeInput(source="frame", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "resize": n_rs,
    })})})

    topo = to_router_topology(pipe, catalog)

    assert len(topo.edges) == 1
    edge = topo.edges[0]
    assert edge.source_channel == "frame.out"
    assert edge.target_node_id == "resize"
    assert edge.target_input_port == "in"
    assert edge.cross_process is False


def test_multi_output_ports_creates_multiple_channels():
    """Операция с несколькими output_ports (color_detection: detections + mask)."""
    catalog = _make_catalog()

    n_det = ProcessingNode(
        node_id="detector",
        operation_ref="color_detection",
        inputs=[],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "detector": n_det,
    })})})

    topo = to_router_topology(pipe, catalog)

    channel_names = {ch.channel_name for ch in topo.channels}
    assert "detector.detections" in channel_names
    assert "detector.mask" in channel_names
    assert len(topo.channels) == 2

    # Проверяем payload_kind
    by_name = {ch.channel_name: ch for ch in topo.channels}
    assert by_name["detector.detections"].payload_kind == "detections"
    assert by_name["detector.mask"].payload_kind == "mask"
