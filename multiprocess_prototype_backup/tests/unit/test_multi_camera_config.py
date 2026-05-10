"""Unit-тесты для мульти-камерной конфигурации (Phase 3)."""

from __future__ import annotations

from multiprocess_prototype.backend.processes.camera.config import CameraConfig
from multiprocess_prototype.config.app import (
    AppConfig,
    build_cameras_from_profile,
    build_cameras_from_recipe,
)


class TestCameraConfig:
    def test_default_camera_id(self):
        c = CameraConfig()
        assert c.camera_id == 0
        assert c.process_name == "camera_0"

    def test_custom_camera_id(self):
        c = CameraConfig(camera_id=5)
        assert c.process_name == "camera_5"

    def test_memory_parameterized(self):
        c = CameraConfig(camera_id=2, ring_buffer_size=4)
        assert "camera_2_frame" in c.memory
        assert c.memory["coll"] == 4

    def test_build_includes_camera_id(self):
        c = CameraConfig(camera_id=3, camera_type="hikvision")
        name, proc_dict = c.build()
        assert name == "camera_3"
        assert proc_dict["config"]["camera_id"] == 3
        assert proc_dict["config"]["camera_type"] == "hikvision"

    def test_unique_shm_slots(self):
        """Гетерогенные камеры — SHM-слоты не пересекаются."""
        configs = [CameraConfig(camera_id=i) for i in range(8)]
        slots = [list(c.memory.keys())[0] for c in configs]
        assert len(set(slots)) == 8


class TestAppConfig:
    def test_fallback_single_simulator(self):
        app = AppConfig()
        cams = [c for c in app.all_process_configs() if isinstance(c, CameraConfig)]
        assert len(cams) == 1
        assert cams[0].camera_type == "simulator"

    def test_heterogeneous_cameras(self):
        cameras = [
            CameraConfig(camera_id=0, camera_type="webcam"),
            CameraConfig(camera_id=1, camera_type="hikvision"),
            CameraConfig(camera_id=2, camera_type="simulator"),
        ]
        app = AppConfig(cameras=cameras)
        all_cfgs = app.all_process_configs()
        cam_cfgs = [c for c in all_cfgs if isinstance(c, CameraConfig)]
        assert len(cam_cfgs) == 3
        assert len(all_cfgs) == 8  # 3 cameras + 5 others

    def test_process_names_unique(self):
        cameras = [CameraConfig(camera_id=i) for i in range(4)]
        app = AppConfig(cameras=cameras)
        names = [c.process_name for c in app.cameras]
        assert len(set(names)) == 4


class TestBuildCamerasFromProfile:
    def test_single_camera(self):
        cams = build_cameras_from_profile(camera_count=1)
        assert len(cams) == 1
        assert cams[0].camera_id == 0

    def test_multiple_cameras(self):
        cams = build_cameras_from_profile(camera_count=3, camera_source_type="simulator")
        assert len(cams) == 3
        assert all(c.camera_type == "simulator" for c in cams)

    def test_ring_buffer_size(self):
        cams = build_cameras_from_profile(camera_count=1, ring_buffer_size=5)
        assert cams[0].ring_buffer_size == 5


class TestBuildCamerasFromRecipe:
    def test_heterogeneous(self):
        recipe = [
            {"camera_id": 0, "camera_type": "webcam", "device_id": 0},
            {"camera_id": 1, "camera_type": "hikvision"},
            {"camera_type": "simulator"},  # auto-assign camera_id=2
        ]
        cams = build_cameras_from_recipe(recipe)
        assert len(cams) == 3
        assert cams[0].camera_type == "webcam"
        assert cams[1].camera_type == "hikvision"
        assert cams[2].camera_id == 2

    def test_preserves_params(self):
        recipe = [{"camera_id": 0, "camera_type": "webcam", "fps": 60, "device_id": 2}]
        cams = build_cameras_from_recipe(recipe)
        assert cams[0].fps == 60
        assert cams[0].device_id == 2
