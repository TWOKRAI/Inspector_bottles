"""Unit-тесты для Pipeline.validate_graph() — Task 9.3.

Покрывает все 6 видов ошибок GraphValidationError:
cycle, type_mismatch, unknown_source, unknown_port, unreachable, unknown_operation.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.registers.pipeline.processing_node import (
    NodeInput,
    NodeOutput,
    ProcessingNode,
)
from multiprocess_prototype.registers.pipeline.schemas import (
    CameraNode,
    GraphValidationError,
    Pipeline,
    RegionNode,
)
from multiprocess_prototype.registers.processor.catalog.port_types import (
    PORT_TYPE_DETECTIONS,
    PORT_TYPE_IMAGE,
    PORT_TYPE_MASK,
)
from multiprocess_prototype.registers.processor.catalog.schemas import (
    Port,
    ProcessingOperationDef,
)


# ---------------------------------------------------------------------------
# Фабрика для определений операций (аналогично test_dag_validation.py)
# ---------------------------------------------------------------------------


def _make_op_def(
    type_key: str,
    input_ports: list[Port] | None = None,
    output_ports: list[Port] | None = None,
) -> ProcessingOperationDef:
    """Создать определение операции с указанными портами."""
    kwargs: dict = {
        "name": f"Операция {type_key}",
        "type_key": type_key,
        "params_schema": f"registers.processor.processings.{type_key}.Params",
        "module_path": f"services.processor.operations.{type_key}_op.Op",
        "on_error": "skip",
    }
    if input_ports is not None:
        kwargs["input_ports"] = input_ports
    if output_ports is not None:
        kwargs["output_ports"] = output_ports
    return ProcessingOperationDef(**kwargs)


# ---------------------------------------------------------------------------
# Каталоги-фикстуры
# ---------------------------------------------------------------------------

_IMAGE_OP = _make_op_def("image_op")
_MASK_PRODUCER = _make_op_def(
    "mask_producer",
    input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
    output_ports=[Port(name="out", data_type=PORT_TYPE_MASK)],
)
_DETECTION_CONSUMER = _make_op_def(
    "detection_consumer",
    input_ports=[Port(name="in", data_type=PORT_TYPE_DETECTIONS)],
    output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
)

CATALOG: dict[str, ProcessingOperationDef] = {
    "image_op": _IMAGE_OP,
    "mask_producer": _MASK_PRODUCER,
    "detection_consumer": _DETECTION_CONSUMER,
}


# ---------------------------------------------------------------------------
# Хелпер: быстрое создание Pipeline с одним регионом
# ---------------------------------------------------------------------------


def _pipeline_one_region(
    nodes: dict[str, ProcessingNode],
    cam_id: str = "cam1",
    reg_id: str = "reg1",
) -> Pipeline:
    """Создать Pipeline с одной камерой/одним регионом и заданными нодами."""
    region = RegionNode(nodes=nodes)
    camera = CameraNode(regions={reg_id: region})
    return Pipeline(cameras={cam_id: camera})


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Валидные графы — ошибок быть не должно."""

    def test_empty_pipeline_no_errors(self):
        """Pipeline без камер — пустой список ошибок."""
        pipe = Pipeline()
        errors = pipe.validate_graph({})
        assert errors == []

    def test_valid_linear_graph_no_errors(self):
        """frame → A → B, типы совпадают (image→image) — ошибок нет."""
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a")],
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b})
        errors = pipe.validate_graph(CATALOG)
        assert errors == []

    def test_valid_dag_no_errors(self):
        """frame → A; A → B; A → C (fan-out) — ошибок нет."""
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a")],
        )
        node_c = ProcessingNode(
            node_id="c",
            operation_ref="image_op",
            inputs=[NodeInput(source="a")],
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b, "c": node_c})
        errors = pipe.validate_graph(CATALOG)
        assert errors == []


class TestUnknownOperation:
    """operation_ref не найден в каталоге."""

    def test_unknown_operation_reported(self):
        """Нода с operation_ref не из каталога → unknown_operation."""
        node = ProcessingNode(
            node_id="x",
            operation_ref="nonexistent_op",
            inputs=[NodeInput(source="frame")],
        )
        pipe = _pipeline_one_region({"x": node})
        errors = pipe.validate_graph(CATALOG)

        assert len(errors) >= 1
        op_errors = [e for e in errors if e.kind == "unknown_operation"]
        assert len(op_errors) == 1
        assert op_errors[0].node_id == "x"
        assert "nonexistent_op" in op_errors[0].message


class TestUnknownSource:
    """NodeInput.source ссылается на несуществующую ноду."""

    def test_unknown_source_reported(self):
        """source='ghost_node_id' → unknown_source."""
        node = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="ghost_node_id")],
        )
        pipe = _pipeline_one_region({"a": node})
        errors = pipe.validate_graph(CATALOG)

        src_errors = [e for e in errors if e.kind == "unknown_source"]
        assert len(src_errors) == 1
        assert src_errors[0].node_id == "a"
        assert src_errors[0].source_id == "ghost_node_id"


class TestUnknownPort:
    """Ссылка на несуществующий порт."""

    def test_unknown_output_port_reported(self):
        """output_port='missing' → unknown_port."""
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a", output_port="missing")],
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b})
        errors = pipe.validate_graph(CATALOG)

        port_errors = [e for e in errors if e.kind == "unknown_port"]
        assert len(port_errors) == 1
        assert port_errors[0].port_name == "missing"
        assert port_errors[0].source_id == "a"

    def test_unknown_input_port_reported(self):
        """input_port='missing' → unknown_port."""
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a", input_port="missing")],
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b})
        errors = pipe.validate_graph(CATALOG)

        port_errors = [e for e in errors if e.kind == "unknown_port"]
        assert len(port_errors) == 1
        assert port_errors[0].port_name == "missing"
        assert port_errors[0].node_id == "b"


class TestTypeMismatch:
    """Несовместимые типы портов."""

    def test_type_mismatch_reported(self):
        """A.out=image → B.in=detections — несовместимо."""
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="detection_consumer",
            inputs=[NodeInput(source="a")],
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b})
        errors = pipe.validate_graph(CATALOG)

        tm_errors = [e for e in errors if e.kind == "type_mismatch"]
        assert len(tm_errors) == 1
        assert tm_errors[0].source_id == "a"
        assert tm_errors[0].port_name is not None
        assert tm_errors[0].node_id == "b"


class TestCycleDetection:
    """Обнаружение циклов в графе."""

    def test_cycle_a_to_b_to_a_reported(self):
        """A → B → A — цикл."""
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="b")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[NodeInput(source="a")],
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b})
        errors = pipe.validate_graph(CATALOG)

        cycle_errors = [e for e in errors if e.kind == "cycle"]
        assert len(cycle_errors) == 1
        assert "a" in cycle_errors[0].message
        assert "b" in cycle_errors[0].message

    def test_cycle_self_loop_reported(self):
        """Нода ссылается на себя — self-loop."""
        node = ProcessingNode(
            node_id="loop",
            operation_ref="image_op",
            inputs=[NodeInput(source="loop")],
        )
        pipe = _pipeline_one_region({"loop": node})
        errors = pipe.validate_graph(CATALOG)

        cycle_errors = [e for e in errors if e.kind == "cycle"]
        assert len(cycle_errors) == 1
        assert "loop" in cycle_errors[0].message


class TestUnreachable:
    """Ноды недостижимые из frame-источника."""

    def test_unreachable_node_reported(self):
        """Нода без frame-предков → unreachable."""
        # node_a подключен к frame, node_b — нет (изолирован)
        node_a = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        node_b = ProcessingNode(
            node_id="b",
            operation_ref="image_op",
            inputs=[],  # нет входов вообще
        )
        pipe = _pipeline_one_region({"a": node_a, "b": node_b})
        errors = pipe.validate_graph(CATALOG)

        unr_errors = [e for e in errors if e.kind == "unreachable"]
        assert len(unr_errors) == 1
        assert unr_errors[0].node_id == "b"


class TestMultiRegionAndEdgeCases:
    """Проверки на несколько регионов и граничные случаи."""

    def test_multi_region_independent(self):
        """Ошибка в одном регионе не «течёт» в другой; camera_id/region_id корректны."""
        # Регион 1: валидный
        node_ok = ProcessingNode(
            node_id="ok",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        region_ok = RegionNode(nodes={"ok": node_ok})

        # Регион 2: ошибка — unknown_operation
        node_bad = ProcessingNode(
            node_id="bad",
            operation_ref="missing_op",
            inputs=[NodeInput(source="frame")],
        )
        region_bad = RegionNode(nodes={"bad": node_bad})

        camera = CameraNode(regions={"good_reg": region_ok, "bad_reg": region_bad})
        pipe = Pipeline(cameras={"cam1": camera})
        errors = pipe.validate_graph(CATALOG)

        # Ошибка только из bad_reg
        assert all(e.region_id == "bad_reg" for e in errors if e.kind == "unknown_operation")
        assert not any(e.region_id == "good_reg" for e in errors if e.kind == "unknown_operation")

    def test_frame_source_skipped_for_source_check(self):
        """source='frame' не репортится как unknown_source."""
        node = ProcessingNode(
            node_id="a",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
        )
        pipe = _pipeline_one_region({"a": node})
        errors = pipe.validate_graph(CATALOG)

        assert not any(e.kind == "unknown_source" for e in errors)

    def test_collects_multiple_errors_at_once(self):
        """Два разных типа ошибок в одном регионе → оба в списке."""
        # Нода с неизвестной операцией + нода с unknown_source
        node_unknown_op = ProcessingNode(
            node_id="x",
            operation_ref="no_such_op",
            inputs=[NodeInput(source="frame")],
        )
        node_bad_src = ProcessingNode(
            node_id="y",
            operation_ref="image_op",
            inputs=[NodeInput(source="ghost")],
        )
        pipe = _pipeline_one_region({"x": node_unknown_op, "y": node_bad_src})
        errors = pipe.validate_graph(CATALOG)

        kinds = {e.kind for e in errors}
        assert "unknown_operation" in kinds
        assert "unknown_source" in kinds


class TestRoundTrip:
    """Часть D — round-trip Pipeline с новыми полями ProcessingNode."""

    def test_pipeline_round_trip_with_new_node_fields(self):
        """Pipeline с outputs/display_targets/channel_prefix → JSON round-trip."""
        node = ProcessingNode(
            node_id="n1",
            operation_ref="image_op",
            inputs=[NodeInput(source="frame")],
            outputs=[
                NodeOutput(port_name="out", display_target="win_main"),
                NodeOutput(port_name="mask"),
            ],
            display_targets=["win_main", "win_debug"],
            channel_prefix="my_prefix",
        )
        region = RegionNode(nodes={"n1": node})
        camera = CameraNode(regions={"r1": region})
        pipe = Pipeline(cameras={"c1": camera})

        json_str = pipe.model_dump_json()
        restored = Pipeline.model_validate_json(json_str)

        restored_node = restored.cameras["c1"].regions["r1"].nodes["n1"]
        assert len(restored_node.outputs) == 2
        assert restored_node.outputs[0].port_name == "out"
        assert restored_node.outputs[0].display_target == "win_main"
        assert restored_node.outputs[1].port_name == "mask"
        assert restored_node.outputs[1].display_target is None
        assert restored_node.display_targets == ["win_main", "win_debug"]
        assert restored_node.channel_prefix == "my_prefix"
