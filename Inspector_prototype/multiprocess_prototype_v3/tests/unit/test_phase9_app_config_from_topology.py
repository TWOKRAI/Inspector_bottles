"""Тесты AppConfig.from_topology() — Task 9.6.

Проверяем:
  - from_topology создаёт ProcessorWorkerConfig для каждого process_id
  - base-конфиг (cameras, renderer) сохраняется
  - Существующие процессы не дублируются
"""

from __future__ import annotations

from multiprocess_prototype_v3.backend.processes.camera.config import CameraConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.backend.processes.processor_worker.config import (
    ProcessorWorkerConfig,
)
from multiprocess_prototype_v3.config.app import AppConfig
from multiprocess_prototype_v3.services.processor.topology.builder import RouterTopology


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_from_topology_creates_processor_per_id():
    """Topology с 3 process_id -> 3 ProcessorWorkerConfig в topology_workers."""
    topo = RouterTopology(
        channels=[],
        edges=[],
        broadcast_routes={},
        process_ids=["proc_A", "proc_B", "proc_C"],
    )

    config = AppConfig.from_topology(topo)

    assert len(config.topology_workers) == 3

    worker_names = {w.process_name for w in config.topology_workers}
    assert worker_names == {"proc_A", "proc_B", "proc_C"}


def test_from_topology_preserves_base():
    """base с camera и renderer -> after from_topology() они на месте."""
    base = AppConfig(
        cameras=[CameraConfig(camera_id=0), CameraConfig(camera_id=1)],
        display_enabled=True,
    )

    topo = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["proc_X"],
    )

    config = AppConfig.from_topology(topo, base=base)

    # Камеры сохранились
    assert len(config.cameras) == 2
    assert config.cameras[0].camera_id == 0
    assert config.cameras[1].camera_id == 1

    # Renderer на месте
    assert config.display_enabled is True

    # Новый topology-воркер добавлен
    worker_names = {w.process_name for w in config.topology_workers}
    assert "proc_X" in worker_names

    # Статические processors не тронуты
    assert len(config.processors) == 2  # auto-created per camera


def test_from_topology_does_not_duplicate_existing_topology_worker():
    """base уже содержит topology_worker с таким именем -> не дублируется."""
    existing_worker = ProcessorWorkerConfig(process_name="proc_A", worker_index=0)
    object.__setattr__(existing_worker, "process_name", "proc_A")

    base = AppConfig(
        cameras=[CameraConfig(camera_id=0)],
        topology_workers=[existing_worker],
    )

    topo = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["proc_A", "proc_B"],
    )

    config = AppConfig.from_topology(topo, base=base)

    # proc_A не дублируется: 1 existing + 1 новый (proc_B) = 2
    worker_names = [w.process_name for w in config.topology_workers]
    assert worker_names.count("proc_A") == 1
    assert "proc_B" in worker_names
    assert len(config.topology_workers) == 2


def test_from_topology_does_not_duplicate_existing_processor():
    """base уже содержит ProcessorConfig с именем совпадающим с process_id -> не дублируется.

    Например processor_0 может совпадать с topology process_id.
    """
    base = AppConfig(
        cameras=[CameraConfig(camera_id=0)],
    )
    # model_post_init создал processor_0 автоматически
    assert any(p.process_name == "processor_0" for p in base.processors)

    topo = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["processor_0", "proc_new"],
    )

    config = AppConfig.from_topology(topo, base=base)

    # processor_0 не дублируется в topology_workers
    topology_names = [w.process_name for w in config.topology_workers]
    assert "processor_0" not in topology_names
    assert "proc_new" in topology_names
    assert len(config.topology_workers) == 1


def test_from_topology_without_base_creates_defaults():
    """Без base -> AppConfig() создаётся с дефолтами + topology-воркеры."""
    topo = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["worker_1"],
    )

    config = AppConfig.from_topology(topo)

    # Дефолтная камера создана (model_post_init)
    assert len(config.cameras) >= 1

    # Topology-воркер добавлен
    worker_names = {w.process_name for w in config.topology_workers}
    assert "worker_1" in worker_names

    # all_process_configs включает topology_workers
    all_names = {c.process_name for c in config.all_process_configs()}
    assert "worker_1" in all_names


def test_from_topology_all_process_configs_includes_topology_workers():
    """all_process_configs() возвра��ает topology_workers вместе со статическими."""
    topo = RouterTopology(
        channels=[], edges=[], broadcast_routes={},
        process_ids=["topo_A", "topo_B"],
    )

    config = AppConfig.from_topology(topo)

    all_configs = config.all_process_configs()
    all_names = {c.process_name for c in all_configs}
    assert "topo_A" in all_names
    assert "topo_B" in all_names
