"""Smoke-тест пайплайна Task 9.4.

End-to-end проверка:
1. Загрузка каталога — 12 операций (2 legacy + 10 новых).
2. Все 10 новых классов загружаются через load_operation_class.
3. Pipeline webcam_input → resize → clahe валидируется без ошибок.
4. Конструкции не вызывают execute (камеры в тестах нет).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_prototype.registers.pipeline.processing_node import (
    NodeInput,
    ProcessingNode,
)
from multiprocess_prototype.registers.pipeline.schemas import (
    CameraNode,
    Pipeline,
    RegionNode,
)
from multiprocess_prototype.registers.processor.catalog.loader import load_catalog
from multiprocess_prototype.services.processor.operations.loader import load_operation_class

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "processing_catalog.yaml"

# Список module_path новых операций Task 9.4
_NEW_OP_MODULE_PATHS = [
    "services.processor.operations.input.webcam_input_op.WebcamInputOp",
    "services.processor.operations.input.hikvision_input_op.HikvisionInputOp",
    "services.processor.operations.input.file_input_op.FileInputOp",
    "services.processor.operations.input.simulator_input_op.SimulatorInputOp",
    "services.processor.operations.roi.region_splitter_op.RegionSplitterOp",
    "services.processor.operations.preprocess.resize_op.ResizeOp",
    "services.processor.operations.preprocess.color_convert_op.ColorConvertOp",
    "services.processor.operations.preprocess.clahe_op.ClaheOp",
    "services.processor.operations.preprocess.blur_op.BlurOp",
    "services.processor.operations.preprocess.threshold_op.ThresholdOp",
]


# ---------------------------------------------------------------------------
# Тест 1: Загрузка каталога — 12 операций
# ---------------------------------------------------------------------------


def test_catalog_loads_twelve_operations():
    """Загрузка обновлённого processing_catalog.yaml → ровно 12 операций."""
    catalog = load_catalog(_CATALOG_PATH)
    assert len(catalog) == 12, (
        f"Ожидалось 12 операций в каталоге, получено {len(catalog)}: {list(catalog.keys())}"
    )


# ---------------------------------------------------------------------------
# Тест 2: Все 10 новых классов загружаются через load_operation_class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", _NEW_OP_MODULE_PATHS)
def test_new_operation_class_loadable(module_path: str):
    """Все новые operation-классы загружаются через load_operation_class без ошибок."""
    cls = load_operation_class(module_path)
    assert cls is not None
    # Можно инстанциировать
    instance = cls()
    instance.configure({})
    assert instance is not None


# ---------------------------------------------------------------------------
# Тест 3: Pipeline webcam_input → resize → clahe валидируется без ошибок
# ---------------------------------------------------------------------------


def test_pipeline_webcam_resize_clahe_validates_clean():
    """Pipeline webcam_input → resize → clahe: validate_graph возвращает []."""
    catalog = load_catalog(_CATALOG_PATH)

    # webcam_input: нет входных портов (источник DAG)
    webcam_node = ProcessingNode(
        node_id="webcam",
        operation_ref="webcam_input",
        inputs=[],  # Источник — нет подключённых входов
    )

    # resize: подключён к webcam.out
    resize_node = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )

    # clahe: подключён к resize.out
    clahe_node = ProcessingNode(
        node_id="clahe",
        operation_ref="clahe",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    nodes = {
        "webcam": webcam_node,
        "resize": resize_node,
        "clahe": clahe_node,
    }
    region = RegionNode(nodes=nodes)
    camera = CameraNode(regions={"reg1": region})
    pipeline = Pipeline(cameras={"cam1": camera})

    errors = pipeline.validate_graph(catalog)
    assert errors == [], (
        f"Ожидался пустой список ошибок, получено: {[e.model_dump() for e in errors]}"
    )


# ---------------------------------------------------------------------------
# Тест 4: Каталог содержит все ожидаемые type_key
# ---------------------------------------------------------------------------


def test_catalog_contains_all_expected_type_keys():
    """Каталог содержит все 12 ожидаемых type_key."""
    catalog = load_catalog(_CATALOG_PATH)
    expected_keys = {
        # Legacy (Task 5a)
        "color_detection",
        "blob_detection",
        # Input (Task 9.4)
        "webcam_input",
        "hikvision_input",
        "file_input",
        "simulator_input",
        # ROI (Task 9.4)
        "region_splitter",
        # Preprocess (Task 9.4)
        "resize",
        "color_convert",
        "clahe",
        "blur",
        "threshold",
    }
    assert set(catalog.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Тест 5: Все записи каталога имеют корректные категории
# ---------------------------------------------------------------------------


def test_catalog_categories_are_correct():
    """Категории в каталоге соответствуют ожидаемым значениям."""
    catalog = load_catalog(_CATALOG_PATH)

    input_ops = {"webcam_input", "hikvision_input", "file_input", "simulator_input"}
    roi_ops = {"region_splitter"}
    preprocess_ops = {"resize", "color_convert", "clahe", "blur", "threshold"}
    detect_ops = {"color_detection", "blob_detection"}

    for key in input_ops:
        assert catalog[key].category == "Input", f"{key}: ожидалась категория Input"
    for key in roi_ops:
        assert catalog[key].category == "ROI", f"{key}: ожидалась категория ROI"
    for key in preprocess_ops:
        assert catalog[key].category == "Preprocess", f"{key}: ожидалась категория Preprocess"
    for key in detect_ops:
        assert catalog[key].category == "Detect", f"{key}: ожидалась категория Detect"


# ---------------------------------------------------------------------------
# Тест 6 (Task 9.5): Smoke topology — реальный Pipeline + каталог
# ---------------------------------------------------------------------------


def test_smoke_topology_from_real_pipeline():
    """Реальный Pipeline webcam_input → resize → clahe + реальный каталог →
    to_router_topology возвращает 3 канала + 2 edge. Без apply (router не создаём)."""
    from multiprocess_prototype.services.processor.topology.builder import to_router_topology

    catalog = load_catalog(_CATALOG_PATH)

    webcam_node = ProcessingNode(
        node_id="webcam",
        operation_ref="webcam_input",
        channel_prefix="cam0",
        inputs=[],
    )
    resize_node = ProcessingNode(
        node_id="resize",
        operation_ref="resize",
        channel_prefix="resize0",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    clahe_node = ProcessingNode(
        node_id="clahe",
        operation_ref="clahe",
        channel_prefix="clahe0",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    nodes = {
        "webcam": webcam_node,
        "resize": resize_node,
        "clahe": clahe_node,
    }
    region = RegionNode(nodes=nodes)
    camera = CameraNode(regions={"reg1": region})
    pipeline = Pipeline(cameras={"cam1": camera})

    # Сначала валидируем граф
    errors = pipeline.validate_graph(catalog)
    assert errors == [], f"Ошибки валидации: {[e.model_dump() for e in errors]}"

    # Затем строим топологию
    topo = to_router_topology(pipeline, catalog)

    # 3 ноды × 1 output = 3 канала
    assert len(topo.channels) == 3

    channel_names = {ch.channel_name for ch in topo.channels}
    assert "cam0.out" in channel_names  # webcam с channel_prefix="cam0"
    assert "resize0.out" in channel_names
    assert "clahe0.out" in channel_names

    # 2 edge: cam0.out → resize, resize0.out → clahe
    assert len(topo.edges) == 2

    # Нет broadcast
    assert topo.broadcast_routes == {}

    # process_ids
    assert topo.process_ids == ["processor"]
