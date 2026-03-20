# multiprocess_prototype\tests\test_configs_build.py
"""
Тест build() конфигов — проверка без запуска процессов.

Проверяет: ProcessConfigBase._build_proc_dict, memory в Camera/Renderer,
process() возвращает (name, proc_dict) с class, queues, managers.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_inspector_paths() -> None:
    proto = Path(__file__).resolve().parent.parent
    root = proto.parent
    mods = root / "multiprocess_framework" / "refactored" / "modules"
    for p in (str(root), str(mods)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_inspector_paths()

from multiprocess_framework.refactored.modules.data_schema_module import process
from multiprocess_prototype.backend.configs import (
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
    assert proc_dict["class"] == (
        "multiprocess_prototype.backend.processes.camera.process.UnifiedCameraProcess"
    )
    assert "memory" in proc_dict
    assert "camera_frame" in proc_dict["memory"]
    assert "managers" in proc_dict
    assert "logger" in proc_dict["managers"]


def test_renderer_config_build():
    """RendererConfig.build() возвращает proc_dict с memory."""
    name, proc_dict = process(RendererConfig())
    assert name == "renderer"
    assert proc_dict["class"] == (
        "multiprocess_prototype.backend.processes.render.process.RendererProcess"
    )
    assert "memory" in proc_dict
    assert "rendered_frame" in proc_dict["memory"]


def test_processor_config_build():
    """ProcessorConfig.build() — memory с processor_mask."""
    name, proc_dict = process(ProcessorConfig())
    assert name == "processor"
    assert proc_dict["class"] == (
        "multiprocess_prototype.backend.processes.processor.process.ProcessorProcess"
    )
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


def test_frontend_config_build_dict():
    """FrontendConfig.build_dict — ключи для FrontendManager/MainWindow, вкладки из feature default_tab_item."""
    from multiprocess_prototype.frontend.configs.frontend_config import FrontendConfig

    d = FrontendConfig().build_dict({})
    for key in (
        "window",
        "header",
        "image_panel",
        "tabs",
        "window_registry",
        "settings_tab",
        "loading_window",
        "camera_type",
        "poll_interval_ms",
    ):
        assert key in d
    assert len(d["tabs"]) == 4
    assert [t["widget"] for t in d["tabs"]] == ["recipes", "settings", "processing", "camera"]
    assert d["tabs"][1]["title"] == "Настройки"
