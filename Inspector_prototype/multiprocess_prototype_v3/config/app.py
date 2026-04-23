"""Root application config: aggregates all process configs.

Phase 3: поддержка гетерогенного списка камер (webcam + hikvision + simulator + file
в одном запуске). Список камер приходит из рецепта или строится по settings profile.

Phase 4 (Task 2.4): N процессоров (по одному на камеру). Каждый Processor привязан
к своей камере через camera_id, все шлют detection_result в общий Renderer.
"""

from __future__ import annotations

import warnings

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module import ProcessLaunchConfig

from multiprocess_prototype_v3.backend.processes.camera.config import CameraConfig
from multiprocess_prototype_v3.backend.processes.database.config import DatabaseConfig
from multiprocess_prototype_v3.backend.processes.gui.config import GuiConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.backend.processes.processor_worker.config import (
    ProcessorWorkerConfig,
)
from multiprocess_prototype_v3.backend.processes.renderer.config import RendererConfig
from multiprocess_prototype_v3.backend.processes.robot.config import RobotConfig

from .logging import LoggingConfig
from .shm_region import ShmRegionSpec


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
    def processor(self) -> ProcessorConfig:
        """Backward compat: доступ к первому процессору.

        DEPRECATED: используйте processors[0] напрямую.
        """
        warnings.warn(
            "AppConfig.processor deprecated, используйте processors[0]",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.processors[0]

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
        """Все конфиги процессов: N камер + N процессоров + [renderer] + robot + database + gui + K воркеров.

        Renderer исключается если display_enabled=False (headless-режим).
        GUI процесс остаётся в любом режиме — он управляет pipeline-логикой.
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
            ]
        )
        return configs


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
