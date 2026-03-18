# multiprocess_prototype\tests\test_configs_build.py
"""
Тест build() конфигов — проверка без запуска процессов.

Проверяет: ProcessConfigBase._build_proc_dict, memory в Camera/Renderer,
process() возвращает (name, proc_dict) с class, queues, managers.
"""

from multiprocess_framework.refactored.modules.data_schema_module import process
from multiprocess_prototype.configs import (
    CameraConfig,
    ProcessorConfig,
    RendererConfig,
    RobotConfig,
    GuiConfig,
)


def test_camera_config_build():
    """CameraConfig.build() возвращает proc_dict с memory, class, managers."""
    name, proc_dict = process(CameraConfig(fps=10, resolution_width=320, resolution_height=240))
    assert name == "camera"
    assert proc_dict["class"] == "multiprocess_prototype.backend.processes.unified_camera_process.UnifiedCameraProcess"
    assert "memory" in proc_dict
    assert "camera_frame" in proc_dict["memory"]
    assert "managers" in proc_dict
    assert "logger" in proc_dict["managers"]


def test_renderer_config_build():
    """RendererConfig.build() возвращает proc_dict с memory."""
    name, proc_dict = process(RendererConfig())
    assert name == "renderer"
    assert "memory" in proc_dict
    assert "rendered_frame" in proc_dict["memory"]


def test_processor_config_build():
    """ProcessorConfig.build() — memory с processor_mask."""
    name, proc_dict = process(ProcessorConfig())
    assert name == "processor"
    assert "memory" in proc_dict
    assert "processor_mask" in proc_dict["memory"]


def test_robot_config_build():
    """RobotConfig.build() — кастомные queues, priority low."""
    name, proc_dict = process(RobotConfig())
    assert name == "robot"
    assert proc_dict["priority"] == "low"
    assert proc_dict["queues"]["system"]["maxsize"] == 50


def test_gui_config_build():
    """GuiConfig.build() — стандартные queues."""
    name, proc_dict = process(GuiConfig())
    assert name == "gui"
    assert proc_dict["queues"]["system"]["maxsize"] == 100
