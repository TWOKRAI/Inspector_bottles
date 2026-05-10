"""Root application config: aggregates all process configs.

Phase 3: поддержка гетерогенного списка камер (webcam + hikvision + simulator + file
в одном запуске). Список камер приходит из рецепта или строится по settings profile.

Phase 4 (Task 2.4): N процессоров (по одному на камеру). Каждый Processor привязан
к своей камере через camera_id, все шлют detection_result в общий Renderer.

Phase 9 (Task 9.6): from_topology() — построение AppConfig из RouterTopology.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessLaunchConfig

from multiprocess_prototype.backend.processes.camera.config import CameraConfig
from multiprocess_prototype.backend.processes.database.config import DatabaseConfig
from multiprocess_prototype.backend.processes.gui.config import GuiConfig
from multiprocess_prototype.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype.backend.processes.processor_worker.config import (
    ProcessorWorkerConfig,
)
from multiprocess_prototype.backend.processes.renderer.config import RendererConfig
from multiprocess_prototype.backend.processes.robot.config import RobotConfig

from .shm_region import ShmRegionSpec

if TYPE_CHECKING:
    from multiprocess_prototype.services.processor.topology.builder import RouterTopology

logger = logging.getLogger(__name__)

_PROTO_ROOT = Path(__file__).resolve().parent.parent


class LoggingConfig(SchemaBase):
    """Logging configuration."""

    log_dir: str = ""
    preset: str = "standard"

    def model_post_init(self, __context: Any) -> None:
        if not self.log_dir:
            default = _PROTO_ROOT / "logs"
            self.log_dir = os.environ.get("INSPECTOR_LOG_DIR") or str(default)


class AppConfig(SchemaBase):
    """Top-level application configuration.

    cameras — гетерогенный список: каждая камера может быть своего типа
    (webcam, hikvision, simulator, file). Если пуст — fallback на 1 симулятор.

    processors — список процессоров (по одному на камеру). Если пуст —
    автоматически создаётся N ProcessorConfig (один per camera) в model_post_init.

    worker_pool_size — количество ProcessorWorker-процессов в пуле (0 = пул отключён).
    """

    logging: LoggingConfig = LoggingConfig()
    cameras: list[CameraConfig] = []
    processors: list[ProcessorConfig] = []
    renderer: RendererConfig = RendererConfig()
    robot: RobotConfig = RobotConfig()
    database: DatabaseConfig = DatabaseConfig()
    gui: GuiConfig = GuiConfig()
    stop_timeout: float = 5.0
    worker_pool_size: int = 0
    # Topology-driven воркеры (Task 9.6): process_id из RouterTopology.
    # Хранятся отдельно от processors (ProcessorConfig привязан к camera_id).
    topology_workers: list[ProcessorWorkerConfig] = []
    # Headless-режим: False — renderer не запускается, display SHM не аллоцируется
    display_enabled: bool = True

    def model_post_init(self, __context: object) -> None:
        """Fallback: cameras и processors заполняются автоматически если пусты.

        Если cameras пуст — создаём 1 симулятор (обратная совместимость).
        Если processors пуст — создаём N ProcessorConfig (один per camera),
        наследуя разрешение от соответствующей камеры.
        """
        if not self.cameras:
            object.__setattr__(self, "cameras", [CameraConfig(camera_id=0)])

        if not self.processors:
            processors = []
            for cam in self.cameras:
                processors.append(
                    ProcessorConfig(
                        camera_id=cam.camera_id,
                        resolution_width=cam.resolution_width,
                        resolution_height=cam.resolution_height,
                    )
                )
            object.__setattr__(self, "processors", processors)

    @property
    def worker_configs(self) -> list[ProcessorWorkerConfig]:
        """Список конфигов воркеров пула (пустой если worker_pool_size == 0)."""
        return [ProcessorWorkerConfig(worker_index=i) for i in range(self.worker_pool_size)]

    def all_shm_regions(self) -> list[ShmRegionSpec]:
        """Собрать все SHM-регионы от всех процессов.

        Каждый процесс с методом shm_region() предоставляет свою спецификацию.
        Камеры возвращают per-camera регионы с разными разрешениями.
        """
        regions: list[ShmRegionSpec] = []
        for cfg in self.all_process_configs():
            if hasattr(cfg, "shm_region") and callable(cfg.shm_region):
                regions.append(cfg.shm_region())
        return regions

    def all_shm_names(self) -> list[str]:
        """Собрать все базовые имена SHM из memory-свойств всех процессов.

        Используется cleanup-ом при старте для очистки осиротевших сегментов.
        Ключ "coll" в словаре memory — служебный (количество слотов), не имя сегмента.

        Returns:
            Список уникальных базовых имён SHM (без суффиксов _0, _1, ...).
        """
        names: list[str] = []
        for cfg in self.all_process_configs():
            mem = cfg.memory
            if not isinstance(mem, dict):
                continue
            for key in mem:
                if key != "coll" and key not in names:
                    names.append(key)
        return names

    def all_process_configs(self) -> list[ProcessLaunchConfig]:
        """Все конфиги процессов: N камер + N процессоров + [renderer] + robot + database + gui + K воркеров + topology_workers.

        Renderer исключается если display_enabled=False (headless-режим).
        GUI процесс остаётся в любом режиме — он управляет pipeline-логикой.
        topology_workers добавляются после статических воркеров (Task 9.6).
        """
        configs = [
            *self.cameras,
            *self.processors,
        ]
        if self.display_enabled:
            configs.append(self.renderer)
        configs.extend(
            [
                self.robot,
                self.database,
                self.gui,
                *self.worker_configs,
                *self.topology_workers,
            ]
        )
        return configs

    @classmethod
    def from_topology(
        cls,
        topology: "RouterTopology",
        *,
        base: Optional["AppConfig"] = None,
    ) -> "AppConfig":
        """Построить AppConfig из RouterTopology.

        Уникальные topology.process_ids -> новые ProcessorWorkerConfig в topology_workers[].
        base — опциональная статическая часть (cameras, gui, renderer, ...).

        Topology-driven воркеры хранятся в topology_workers[] (не в processors[]),
        потому что ProcessorConfig привязан к camera_id, а topology-воркеры —
        универсальные operation runner'ы.

        НЕ удаляет существующие конфиги — это ответственность caller'а.
        Это снимает риск случайно удалить statically-configured процессы.
        """
        if base is not None:
            config = base.model_copy(deep=True)
        else:
            config = cls()

        # Имена уже существующих процессов — processors + topology_workers + pool workers
        existing_names: set[str] = set()
        existing_names.update(p.process_name for p in config.processors)
        existing_names.update(w.process_name for w in config.topology_workers)
        existing_names.update(w.process_name for w in config.worker_configs)

        new_workers = list(config.topology_workers)

        for pid in topology.process_ids:
            if pid in existing_names:
                logger.debug(
                    "from_topology: процесс '%s' уже существует — пропуск", pid,
                )
                continue

            worker_cfg = ProcessorWorkerConfig(
                process_name=pid,
                worker_index=0,  # Не используется для topology-driven процессов
            )
            # model_post_init переопределяет process_name на основе worker_index,
            # но нам нужен именно pid. Перезаписываем.
            object.__setattr__(worker_cfg, "process_name", pid)

            new_workers.append(worker_cfg)
            logger.debug("from_topology: добавлен ProcessorWorkerConfig '%s'", pid)

        object.__setattr__(config, "topology_workers", new_workers)
        return config


def build_cameras_from_profile(
    camera_count: int = 1,
    camera_source_type: str = "simulator",
    ring_buffer_size: int = 3,
) -> list[CameraConfig]:
    """Построить однородный список камер из settings profile (Phase 0 совместимость).

    Для гетерогенных камер — передавай cameras напрямую из рецепта.
    """
    return [
        CameraConfig(
            camera_id=i,
            camera_type=camera_source_type,
            ring_buffer_size=ring_buffer_size,
        )
        for i in range(camera_count)
    ]


def build_cameras_from_recipe(camera_dicts: list[dict]) -> list[CameraConfig]:
    """Построить гетерогенный список камер из рецепта.

    Каждый dict — полный набор параметров CameraConfig:
    [{"camera_id": 0, "camera_type": "webcam", "device_id": 0, "fps": 30}, ...]
    """
    cameras = []
    for i, d in enumerate(camera_dicts):
        # camera_id из рецепта или по порядку
        if "camera_id" not in d:
            d = {**d, "camera_id": i}
        cameras.append(CameraConfig(**d))
    return cameras
