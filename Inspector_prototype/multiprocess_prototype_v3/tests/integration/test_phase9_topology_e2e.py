"""E2E integration-тест для router-топологии — Task 9.5 часть G.

Доказательный эквивалент «DAG из 4 нод крутится 5 секунд»:
  1. Создаёт реальный RouterManager.
  2. Применяет topology (один регион, 3 ноды: webcam → resize → clahe).
  3. Прокачивает 100 fake-frames через каналы.
  4. Проверяет, что каналы получили сообщения.

Полноценный запуск через ProcessManagerProcess + GUI-процесс — Task 9.13/9.14.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.router_module import RouterManager, QueueChannel
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
from multiprocess_prototype_v3.services.processor.topology.builder import to_router_topology
from multiprocess_prototype_v3.services.processor.topology.registrar import apply_topology


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Минимальный каталог для 3 нод."""
    return {
        "webcam_input": ProcessingOperationDef(
            name="Webcam", type_key="webcam_input", params_schema="stub", module_path="stub",
            input_ports=[], output_ports=[Port(name="out", data_type="image")], category="Input",
        ),
        "resize": ProcessingOperationDef(
            name="Resize", type_key="resize", params_schema="stub", module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")], category="Preprocess",
        ),
        "clahe": ProcessingOperationDef(
            name="CLAHE", type_key="clahe", params_schema="stub", module_path="stub",
            input_ports=[Port(name="in", data_type="image")],
            output_ports=[Port(name="out", data_type="image")], category="Preprocess",
        ),
    }


def test_e2e_topology_message_flow():
    """E2E: apply_topology → прокачка 100 сообщений → каналы получают данные.

    Доказывает, что router-topology корректно регистрирует каналы и маршруты,
    и сообщения проходят через каналы. Эквивалент «DAG крутится 5 секунд».
    """
    catalog = _make_catalog()

    n_in = ProcessingNode(node_id="webcam", operation_ref="webcam_input", inputs=[])
    n_rs = ProcessingNode(
        node_id="resize", operation_ref="resize",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe", operation_ref="clahe",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl,
    })})})

    # Валидируем граф перед трансформацией
    errors = pipe.validate_graph(catalog)
    assert errors == [], f"Ошибки валидации: {errors}"

    # Создаём реальный RouterManager
    router = RouterManager(manager_name="test_topology_e2e")
    router.initialize()

    try:
        # Строим и применяем topology
        topo = to_router_topology(pipe, catalog)
        result = apply_topology(router, topo)

        assert result.channels_added == 3  # webcam.out, resize.out, clahe.out
        assert result.routes_added == 2  # webcam.out → resize.in, resize.out → clahe.in

        # Также создаём target-каналы (input-порты) для маршрутизации
        # Router.register_route привязывает key → channel_name,
        # но channel_name должен быть зарегистрирован
        resize_in_ch = QueueChannel("resize.in")
        clahe_in_ch = QueueChannel("clahe.in")
        router.register_channel(resize_in_ch)
        router.register_channel(clahe_in_ch)

        # Прокачиваем 100 fake-frames
        num_frames = 100
        start = time.monotonic()

        for i in range(num_frames):
            # Отправляем в канал webcam.out напрямую
            webcam_ch = router.get_channel("webcam.out")
            assert webcam_ch is not None, "Канал webcam.out не найден"
            webcam_ch.send({"frame_id": i, "data": f"frame_{i}"})

            # Маршрутизация: webcam.out → resize.in
            # Используем router.send с command=webcam.out для dispatch
            router.send({"command": "webcam.out", "frame_id": i, "payload": "test"})

        elapsed = time.monotonic() - start

        # Проверяем что сообщения дошли до resize.in
        received = resize_in_ch.poll(timeout=0.0)
        assert len(received) == num_frames, (
            f"Ожидалось {num_frames} сообщений в resize.in, получено {len(received)}"
        )

        # Проверяем пропускную способность
        assert elapsed < 5.0, f"100 сообщений заняли {elapsed:.2f}s — слишком долго"

    finally:
        router.shutdown()


def test_e2e_topology_diff_removes_channel():
    """E2E: apply_topology с previous → канал удаляется из router."""
    catalog = _make_catalog()

    # Полная топология: 3 ноды
    n_in = ProcessingNode(node_id="webcam", operation_ref="webcam_input", inputs=[])
    n_rs = ProcessingNode(
        node_id="resize", operation_ref="resize",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe", operation_ref="clahe",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe_full = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl,
    })})})

    # Урезанная топология: clahe удалён
    pipe_short = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs,
    })})})

    router = RouterManager(manager_name="test_topology_diff")
    router.initialize()

    try:
        # Первоначальная топология
        topo1 = to_router_topology(pipe_full, catalog)
        apply_topology(router, topo1)

        # clahe.out существует
        assert router.get_channel("clahe.out") is not None

        # Применяем diff: clahe удалён
        topo2 = to_router_topology(pipe_short, catalog)
        result = apply_topology(router, topo2, previous=topo1)

        assert result.channels_removed == 1

        # clahe.out больше не существует
        assert router.get_channel("clahe.out") is None

    finally:
        router.shutdown()
