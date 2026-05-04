"""Default System Template — стандартная pipeline для инспекции.

Строит SystemBlueprint из параметров камер:
    camera_N (CameraServicePlugin) → processor_N (ProcessorServicePlugin)
    → renderer (RenderPlugin)
    + database (DatabasePlugin)
    + robot (RobotPlugin)
    + worker_K (ProcessorWorkerPlugin) * worker_pool_size
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.blueprint import (
    ProcessConfig,
    SystemBlueprint,
    Wire,
)

from multiprocess_prototype.plugins.cameras.camera_service.config import CameraServicePluginConfig
from multiprocess_prototype.plugins.database.sqlite_storage.config import DatabasePluginConfig
from multiprocess_prototype.plugins.hardware.robot_control.config import RobotPluginConfig
from multiprocess_prototype.plugins.services.processor_service.config import ProcessorServicePluginConfig
from multiprocess_prototype.plugins.services.processor_worker.config import ProcessorWorkerPluginConfig


def build_default_blueprint(
    cameras: list | None = None,
    worker_pool_size: int = 0,
    display_enabled: bool = True,
    db_url: str = "sqlite:///./data/db/inspector.db",
) -> SystemBlueprint:
    """Построить стандартный SystemBlueprint для инспекции.

    Args:
        cameras: Список dict'ов с параметрами камер. Каждый dict содержит:
            camera_id, camera_type, ring_buffer_size, fps, resolution_width,
            resolution_height, device_id, и т.д.
            Если None — одна камера-симулятор по умолчанию.
        worker_pool_size: Количество worker-процессов в пуле (0 = отключён).
        display_enabled: Включить renderer.
        db_url: URL подключения к БД.

    Returns:
        SystemBlueprint — готовый к проверке и запуску.
    """
    if cameras is None:
        cameras = [{"camera_id": 0, "camera_type": "simulator"}]

    processes: list[ProcessConfig] = []
    wires: list[Wire] = []

    # --- Камеры и процессоры (по одному на камеру) ---
    for cam_cfg in cameras:
        cam_id = cam_cfg.get("camera_id", 0)

        # Камера
        camera_plugin = CameraServicePluginConfig(
            camera_id=cam_id,
            camera_type=cam_cfg.get("camera_type", "simulator"),
            ring_buffer_size=cam_cfg.get("ring_buffer_size", 3),
            fps=cam_cfg.get("fps", 25),
            resolution_width=cam_cfg.get("resolution_width", 640),
            resolution_height=cam_cfg.get("resolution_height", 480),
            device_id=cam_cfg.get("device_id", 0),
            shm_native_resolution=cam_cfg.get("shm_native_resolution", False),
            use_simulator=cam_cfg.get("use_simulator", False),
            simulator_image_path=cam_cfg.get("simulator_image_path"),
        )
        processes.append(ProcessConfig.from_plugins(
            f"camera_{cam_id}", camera_plugin, priority="high"
        ))

        # Процессор
        processor_plugin = ProcessorServicePluginConfig(
            camera_id=cam_id,
            color_lower=cam_cfg.get("color_lower", [0, 0, 150]),
            color_upper=cam_cfg.get("color_upper", [100, 100, 255]),
            min_area=cam_cfg.get("min_area", 500),
            max_area=cam_cfg.get("max_area", 50000),
            resolution_width=cam_cfg.get("resolution_width", 640),
            resolution_height=cam_cfg.get("resolution_height", 480),
            worker_pool_size=worker_pool_size,
        )
        processes.append(ProcessConfig.from_plugins(
            f"processor_{cam_id}", processor_plugin, priority="high"
        ))

        # Wire: camera → processor (frame)
        wires.append(Wire(
            source=f"camera_{cam_id}.capture.frame",
            target=f"processor_{cam_id}.processor.frame",
            description=f"Кадры камеры {cam_id} → процессор {cam_id}",
        ))

    # --- Database ---
    db_plugin = DatabasePluginConfig(db_url=db_url)
    processes.append(ProcessConfig.from_plugins("database", db_plugin))

    # --- Robot ---
    robot_plugin = RobotPluginConfig()
    processes.append(ProcessConfig.from_plugins("robot", robot_plugin, priority="low"))

    # --- Worker pool ---
    for i in range(worker_pool_size):
        worker_plugin = ProcessorWorkerPluginConfig(worker_index=i)
        processes.append(ProcessConfig.from_plugins(
            f"processor_worker_{i}", worker_plugin
        ))

    return SystemBlueprint(
        name="default_inspection",
        description="Стандартная pipeline: cameras → processors → renderer + database",
        processes=processes,
        wires=wires,
    )
