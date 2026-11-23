"""Тесты плагина HikvisionCameraPlugin: конфиг, register, метаданные.

Поведение плагина на ядре `camera_device` (команды Р7, сеанс, кадры) -- в test_plugin_on_core.py.
Тесты команд и кадров старого пути (мок `HikvisionCamera` внутри plugin.py) удалены в Task 4.2b.
"""

from __future__ import annotations


# ===========================================================================
# TestHikvisionCameraConfig
# ===========================================================================


class TestHikvisionCameraConfig:
    """Тесты конфигурации плагина."""

    def test_default_values(self):
        """Дефолтные значения конфига: camera_id=0, resolution=1920x1080, fps=25, auto_start=False."""
        from Services.hikvision_camera.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig()
        assert cfg.camera_id == 0
        assert cfg.camera_index == 0
        assert cfg.resolution_width == 1920
        assert cfg.resolution_height == 1080
        assert cfg.fps == 25
        assert cfg.auto_start is False

    def test_memory_property(self):
        """memory возвращает dict с правильным slot_name и shape для camera_id=0."""
        from Services.hikvision_camera.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig()
        mem = cfg.memory
        assert mem is not None
        # Ключ слота: hikvision_0_frame
        assert "hikvision_0_frame" in mem
        # Размерность: (height, width, 3)
        assert mem["hikvision_0_frame"] == (1080, 1920, 3)

    def test_memory_custom_camera_id(self):
        """SHM slot_name учитывает camera_id: camera_id=3 → hikvision_3_frame."""
        from Services.hikvision_camera.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig(camera_id=3)
        mem = cfg.memory
        assert "hikvision_3_frame" in mem
        # Старый ключ не должен присутствовать
        assert "hikvision_0_frame" not in mem

    def test_memory_ring_buffer_size(self):
        """memory['coll'] равен ring_buffer_size."""
        from Services.hikvision_camera.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig(ring_buffer_size=5)
        assert cfg.memory["coll"] == 5

    def test_plugin_class_path(self):
        """plugin_class указывает на правильный класс."""
        from Services.hikvision_camera.plugin.config import HikvisionCameraConfig

        cfg = HikvisionCameraConfig()
        assert cfg.plugin_class == ("Services.hikvision_camera.plugin.plugin.HikvisionCameraPlugin")


# ===========================================================================
# TestHikvisionCameraRegisters
# ===========================================================================


class TestHikvisionCameraRegisters:
    """Тесты runtime-параметров."""

    def test_default_values(self):
        """Дефолтные значения: exposure_time=10000, gain=0, frame_rate=25."""
        from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

        reg = HikvisionCameraRegisters()
        assert reg.exposure_time == 10_000.0
        assert reg.gain == 0.0
        assert reg.frame_rate == 25.0

    def test_field_names(self):
        """Ожидаемые поля присутствуют в model_fields."""
        from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

        fields = set(HikvisionCameraRegisters.model_fields.keys())
        assert "exposure_time" in fields
        assert "gain" in fields
        assert "frame_rate" in fields

    def test_mutability(self):
        """Регистры можно менять (нужно для GUI-биндинга)."""
        from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

        reg = HikvisionCameraRegisters()
        reg.exposure_time = 50_000.0
        reg.gain = 5.0
        reg.frame_rate = 60.0

        assert reg.exposure_time == 50_000.0
        assert reg.gain == 5.0
        assert reg.frame_rate == 60.0


# ===========================================================================
# TestHikvisionCameraPlugin
# ===========================================================================


class TestHikvisionCameraPlugin:
    """Тесты метаданных source-плагина."""

    def test_plugin_meta(self):
        """name='hikvision', category='source'."""
        from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        assert plugin.name == "hikvision"
        assert plugin.category == "source"

    def test_outputs(self):
        """Один output: frame, dtype=image/bgr."""
        from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        assert len(plugin.outputs) == 1
        assert plugin.outputs[0].name == "frame"
        assert plugin.outputs[0].dtype == "image/bgr"

    def test_no_inputs(self):
        """Source plugin — нет inputs."""
        from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

        plugin = HikvisionCameraPlugin()
        assert plugin.inputs == []

    def test_register_class_is_hikvision_registers(self):
        """register_class указывает на HikvisionCameraRegisters."""
        from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin
        from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

        assert HikvisionCameraPlugin.register_class is HikvisionCameraRegisters

    def test_nested_config_нормализуется_оркестратором_в_плоский(self):
        """Вложенный blueprint-формат pdef разворачивается ОРКЕСТРАТОРОМ в плоский ctx.config.

        Регресс FPS=0: GUI-нормализованный рецепт кладёт параметры под ключ "config";
        PluginOrchestrator._extract_plugin_config разворачивает их, плагину не нужно знать про два формата.
        """
        from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
            PluginOrchestrator,
        )

        pdef = {
            "plugin_name": "hikvision",
            "plugin_class": "Services.hikvision_camera.plugin.plugin.HikvisionCameraPlugin",
            "category": "source",
            "config": {
                "camera_id": 1,
                "camera_index": 0,
                "resolution_width": 1440,
                "resolution_height": 1080,
                "fps": 25,
                "auto_start": True,
            },
        }
        flat = PluginOrchestrator._extract_plugin_config(pdef)
        assert "config" not in flat
        assert flat["camera_id"] == 1
        assert flat["resolution_width"] == 1440
        assert flat["auto_start"] is True
