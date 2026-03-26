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

from multiprocess_framework.modules.data_schema_module import process
from multiprocess_prototype.backend.configs import (
    CameraConfig,
    GuiConfig,
    ProcessorConfig,
    RendererConfig,
    RobotConfig,
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


def test_gui_config_recipes_in_process_config():
    """GuiConfig: recipes_path и recipe_access попадают в config процесса (для FrontendLauncher)."""
    name, proc_dict = process(
        GuiConfig(
            recipes_path="C:/tmp/recipes.yaml",
            recipe_access={"level": 10, "bypass_readonly": True},
        )
    )
    assert name == "gui"
    cfg = proc_dict["config"]
    assert cfg["recipes_path"] == "C:/tmp/recipes.yaml"
    assert cfg["recipe_access"]["level"] == 10
    assert cfg["recipe_access"]["bypass_readonly"] is True


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
        "recipes_tab",
        "cropped_regions_tab",
        "post_processing_tab",
        "recipes_path",
        "settings_recipes_path",
        "recipe_access",
        "loading_window",
        "camera_type",
        "poll_interval_ms",
        "ui_diagnostics",
    ):
        assert key in d
    assert d["ui_diagnostics"] == {}
    assert len(d["tabs"]) == 6
    assert [t["widget"] for t in d["tabs"]] == [
        "recipes",
        "settings",
        "processing",
        "post_processing",
        "cropped_regions",
        "camera",
    ]
    assert d["tabs"][1]["title"] == "Настройки"


def test_frontend_build_dict_merges_gui_recipe_fields():
    """То, что приходит из GuiConfig.model_dump(), мержится в build_dict (пути и recipe_access)."""
    from multiprocess_prototype.frontend.configs.frontend_config import FrontendConfig

    app_cfg = GuiConfig(
        recipes_path="D:/data/recipes.yaml",
        settings_recipes_path="D:/data/ui.yaml",
        recipe_access={"level": 5, "show_hidden": False},
    ).model_dump()
    d = FrontendConfig().build_dict(app_cfg)
    assert d["recipes_path"] == "D:/data/recipes.yaml"
    assert d["settings_recipes_path"] == "D:/data/ui.yaml"
    assert d["recipe_access"]["level"] == 5


def test_frontend_build_dict_ui_diagnostics_from_gui(monkeypatch):
    """ui_diagnostics из GuiConfig и опционально env INSPECTOR_UI_DIAGNOSTICS."""
    from multiprocess_prototype.frontend.configs.frontend_config import FrontendConfig

    monkeypatch.delenv("INSPECTOR_UI_DIAGNOSTICS", raising=False)
    app_cfg = GuiConfig(
        ui_diagnostics={"enabled": True, "buffer_max": 0, "log_level": "DEBUG"},
    ).model_dump()
    d = FrontendConfig().build_dict(app_cfg)
    assert d["ui_diagnostics"]["enabled"] is True
    assert d["ui_diagnostics"]["log_level"] == "DEBUG"

    monkeypatch.setenv("INSPECTOR_UI_DIAGNOSTICS", "1")
    d2 = FrontendConfig().build_dict({})
    assert d2["ui_diagnostics"].get("enabled") is True


def test_settings_tab_widget_accepts_recipe_bindings():
    """Контракт: SettingsTabWidget принимает recipe_manager, recipe_access и recipes_tab (фабрика передаёт их из config)."""
    import inspect

    from multiprocess_prototype.frontend.widgets.tabs_setting.recipes_settings_tab.widget import (
        SettingsTabWidget,
    )

    sig = inspect.signature(SettingsTabWidget.__init__)
    names = set(sig.parameters.keys())
    assert "recipe_manager" in names
    assert "recipe_access" in names
    assert "recipes_tab" in names
