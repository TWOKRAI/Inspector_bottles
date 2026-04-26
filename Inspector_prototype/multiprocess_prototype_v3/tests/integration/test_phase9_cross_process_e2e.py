"""E2E integration-тест для cross-process топологии — Task 9.6.

Доказательный тест:
  1. Pipeline с 4 нодами в 2 process_id.
  2. to_router_topology -> cross-process edges.
  3. apply_topology с мок MemoryManager -> SHM middleware подключён.
  4. Симуляция: отправка msg с numpy frame через middleware round-trip.
  5. Графовый rebuild: добавление третьего process_id -> create_and_register.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.router_module import RouterManager, QueueChannel
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
from multiprocess_prototype_v3.services.processor.topology.builder import to_router_topology
from multiprocess_prototype_v3.services.processor.topology.registrar import (
    apply_topology,
    _reset_shm_middleware_cache,
)


def _make_catalog() -> dict[str, ProcessingOperationDef]:
    """Минимальный каталог для 4 нод."""
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
    }


class MockMemoryManager:
    """In-memory реализация MemoryManager для e2e тестов.

    Хранит данные в dict вместо реальной shared memory.
    API совместим с FrameShmMiddleware: write_images, read_images, find_free_index.
    """

    def __init__(self) -> None:
        # (owner, slot, index) -> list[ndarray]
        self._storage: dict[tuple[str, str, int], list[np.ndarray]] = {}

    def find_free_index(self, owner: str, slot: str) -> int:
        """Всегда возвращаем 0 для простоты."""
        return 0

    def write_images(
        self, owner: str, slot: str, images: list[np.ndarray], index: int,
    ) -> str:
        """Записать изображения в in-memory storage."""
        self._storage[(owner, slot, index)] = list(images)
        return f"{slot}_actual"

    def read_images(
        self, owner: str, slot: str, index: int, n: int = 1,
    ) -> list[np.ndarray]:
        """Прочитать изображения из in-memory storage."""
        key = (owner, slot, index)
        images = self._storage.get(key, [])
        return images[:n]


def test_e2e_cross_process_shm_roundtrip():
    """E2E: Pipeline с 4 нодами в 2 process_id, SHM middleware round-trip.

    Топология:
      proc_A: webcam_input -> resize
      proc_B: clahe -> threshold

    Cross-process edge: resize.out -> clahe.in (image payload).
    SHM middleware должен подключиться и обеспечить round-trip frame.
    """
    _reset_shm_middleware_cache()
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
    n_th = ProcessingNode(
        node_id="threshold", operation_ref="threshold", process_id="proc_B",
        inputs=[NodeInput(source="clahe", output_port="out", input_port="in")],
    )

    pipe = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl, "threshold": n_th,
    })})})

    # Валидация графа
    errors = pipe.validate_graph(catalog)
    assert errors == [], f"Ошибки валидации: {errors}"

    # Строим topology
    topo = to_router_topology(pipe, catalog)

    # Проверяем cross-process edges
    cross_edges = [e for e in topo.edges if e.cross_process]
    assert len(cross_edges) == 1
    assert cross_edges[0].source_channel == "resize.out"

    # Проверяем process_groups
    assert sorted(topo.process_groups["proc_A"]) == ["resize", "webcam"]
    assert sorted(topo.process_groups["proc_B"]) == ["clahe", "threshold"]

    # Создаём реальный RouterManager
    router = RouterManager(manager_name="test_cross_process_e2e")
    router.initialize()

    try:
        mm = MockMemoryManager()

        result = apply_topology(router, topo, memory_manager=mm)

        assert result.channels_added == 4  # webcam.out, resize.out, clahe.out, threshold.out
        assert result.shm_middlewares_added == 1  # resize.out -> clahe (cross-process, image)

        # Создаём target-каналы для маршрутизации
        for ch_name in ["resize.in", "clahe.in", "threshold.in"]:
            router.register_channel(QueueChannel(ch_name))

        # --- Симуляция SHM round-trip ---
        # Отправляем сообщение с numpy frame через router
        test_frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

        msg = {
            "command": "resize.out",
            "frame": test_frame,
            "data": {"frame_id": 42},
        }

        # on_send middleware должен перехватить frame
        router.send(msg)

        # После on_send: frame убран из msg, shm координаты добавлены
        # Это произошло in-place в middleware.
        # Проверяем что frame был записан в MockMemoryManager
        assert len(mm._storage) > 0, "FrameShmMiddleware не записал frame в storage"

        # Читаем из storage напрямую — данные должны совпадать
        stored = list(mm._storage.values())[0]
        assert len(stored) == 1
        np.testing.assert_array_equal(stored[0], test_frame)

    finally:
        router.shutdown()


def test_e2e_graph_rebuild_adds_process():
    """E2E: графовый rebuild — добавляем третий process_id, проверяем create_and_register."""
    _reset_shm_middleware_cache()
    catalog = _make_catalog()

    # Начальная топология: 2 process_id
    n_in = ProcessingNode(
        node_id="webcam", operation_ref="webcam_input", process_id="proc_A",
    )
    n_rs = ProcessingNode(
        node_id="resize", operation_ref="resize", process_id="proc_B",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )

    pipe_v1 = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs,
    })})})

    topo_v1 = to_router_topology(pipe_v1, catalog)
    assert sorted(topo_v1.process_ids) == ["proc_A", "proc_B"]

    # Расширенная топология: добавляем clahe в proc_C
    n_cl = ProcessingNode(
        node_id="clahe", operation_ref="clahe", process_id="proc_C",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe_v2 = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl,
    })})})

    topo_v2 = to_router_topology(pipe_v2, catalog)
    assert sorted(topo_v2.process_ids) == ["proc_A", "proc_B", "proc_C"]

    # Мок registry и router
    router = MagicMock()
    router.register_channel.return_value = True
    router.register_route.return_value = True
    router.register_broadcast_route.return_value = True
    router.unregister_channel.return_value = True

    registry = MagicMock(spec=IProcessRegistry)
    registry.create_and_register.return_value = MagicMock()

    # apply v1 (initial)
    result_v1 = apply_topology(
        router, topo_v1,
        process_registry=registry,
    )
    assert result_v1.processes_created == 2  # proc_A, proc_B

    # apply v2 с previous=v1 (rebuild)
    result_v2 = apply_topology(
        router, topo_v2,
        previous=topo_v1,
        process_registry=registry,
    )

    # Только proc_C — новый
    assert result_v2.processes_created == 1
    assert result_v2.processes_stopped == 0

    # Проверяем что create_and_register вызван с name='proc_C'
    last_call = registry.create_and_register.call_args_list[-1]
    assert last_call.kwargs.get("name") or last_call[0][0] == "proc_C"


def test_e2e_graph_rebuild_removes_process():
    """E2E: графовый rebuild — убираем process_id, проверяем stop_one + remove_process."""
    _reset_shm_middleware_cache()
    catalog = _make_catalog()

    # v1: 3 process_id
    n_in = ProcessingNode(
        node_id="webcam", operation_ref="webcam_input", process_id="proc_A",
    )
    n_rs = ProcessingNode(
        node_id="resize", operation_ref="resize", process_id="proc_B",
        inputs=[NodeInput(source="webcam", output_port="out", input_port="in")],
    )
    n_cl = ProcessingNode(
        node_id="clahe", operation_ref="clahe", process_id="proc_C",
        inputs=[NodeInput(source="resize", output_port="out", input_port="in")],
    )

    pipe_v1 = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs, "clahe": n_cl,
    })})})
    topo_v1 = to_router_topology(pipe_v1, catalog)

    # v2: убираем clahe (proc_C)
    pipe_v2 = Pipeline(cameras={"c0": CameraNode(regions={"r0": RegionNode(nodes={
        "webcam": n_in, "resize": n_rs,
    })})})
    topo_v2 = to_router_topology(pipe_v2, catalog)
    assert sorted(topo_v2.process_ids) == ["proc_A", "proc_B"]

    router = MagicMock()
    router.register_channel.return_value = True
    router.register_route.return_value = True
    router.register_broadcast_route.return_value = True
    router.unregister_channel.return_value = True

    registry = MagicMock(spec=IProcessRegistry)
    registry.create_and_register.return_value = MagicMock()
    registry.stop_one.return_value = True

    # Rebuild: v1 -> v2
    result = apply_topology(
        router, topo_v2,
        previous=topo_v1,
        process_registry=registry,
    )

    assert result.processes_stopped == 1
    registry.stop_one.assert_called_once_with("proc_C", timeout=5.0)
    registry.remove_process.assert_called_once_with("proc_C")
