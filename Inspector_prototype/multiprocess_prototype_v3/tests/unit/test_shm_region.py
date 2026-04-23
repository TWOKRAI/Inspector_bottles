"""Тесты ShmRegionSpec и per-region SHM-размеров (Task 1.1, P8).

Проверяет:
- ShmRegionSpec создаётся и возвращает корректный shape
- CameraConfig.shm_region() генерирует spec из resolution
- 2 камеры с разными разрешениями → разные SHM-регионы
- AppConfig.all_shm_regions() собирает регионы от всех процессов
"""

from __future__ import annotations

from multiprocess_prototype_v3.backend.processes.camera.config import CameraConfig
from multiprocess_prototype_v3.config.app import AppConfig
from multiprocess_prototype_v3.config.shm_region import ShmRegionSpec


class TestShmRegionSpec:
    """ShmRegionSpec — базовые свойства."""

    def test_shape_is_hwc(self) -> None:
        """shape возвращает (height, width, channels) — numpy convention."""
        spec = ShmRegionSpec(name="test", width=640, height=480)
        assert spec.shape == (480, 640, 3)

    def test_custom_channels(self) -> None:
        spec = ShmRegionSpec(name="test", width=100, height=100, channels=1)
        assert spec.shape == (100, 100, 1)

    def test_slots_default_one(self) -> None:
        spec = ShmRegionSpec(name="test", width=640, height=480)
        assert spec.slots == 1


class TestCameraConfigShmRegion:
    """CameraConfig.shm_region() — per-camera SHM spec."""

    def test_default_camera_region(self) -> None:
        cfg = CameraConfig(camera_id=0)
        region = cfg.shm_region()
        assert region.name == "camera_0_frame"
        assert region.width == 640
        assert region.height == 480
        assert region.slots == 3  # ring_buffer_size default

    def test_custom_resolution_region(self) -> None:
        cfg = CameraConfig(camera_id=1, resolution_width=1280, resolution_height=720, ring_buffer_size=5)
        region = cfg.shm_region()
        assert region.name == "camera_1_frame"
        assert region.width == 1280
        assert region.height == 720
        assert region.slots == 5

    def test_two_cameras_different_regions(self) -> None:
        """2 камеры с разными разрешениями → разные SHM-регионы разного размера."""
        cam0 = CameraConfig(camera_id=0, resolution_width=640, resolution_height=480)
        cam1 = CameraConfig(camera_id=1, resolution_width=1280, resolution_height=720)

        r0 = cam0.shm_region()
        r1 = cam1.shm_region()

        assert r0.name != r1.name
        assert r0.shape != r1.shape
        assert r0.shape == (480, 640, 3)
        assert r1.shape == (720, 1280, 3)

    def test_memory_uses_resolution_not_constants(self) -> None:
        """memory property берёт размеры из resolution_width/height, не из констант."""
        cfg = CameraConfig(camera_id=2, resolution_width=1920, resolution_height=1080)
        mem = cfg.memory
        assert "camera_2_frame" in mem
        assert mem["camera_2_frame"] == (1080, 1920, 3)


class TestAppConfigAllShmRegions:
    """AppConfig.all_shm_regions() — реестр всех SHM-регионов."""

    def test_collects_camera_regions(self) -> None:
        """all_shm_regions() собирает регионы от камер."""
        app = AppConfig(
            cameras=[
                CameraConfig(camera_id=0, resolution_width=640, resolution_height=480),
                CameraConfig(camera_id=1, resolution_width=1280, resolution_height=720),
            ]
        )
        regions = app.all_shm_regions()
        camera_regions = [r for r in regions if r.name.startswith("camera_")]
        assert len(camera_regions) == 2
        assert camera_regions[0].shape == (480, 640, 3)
        assert camera_regions[1].shape == (720, 1280, 3)
