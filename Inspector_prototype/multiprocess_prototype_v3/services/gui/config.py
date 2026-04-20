"""GUI service configuration."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import ProcessLaunchConfig
from pydantic import Field


@register_schema("GuiConfigV3")
class GuiConfig(ProcessLaunchConfig):
    process_name: str = "gui"
    process_class: str = "multiprocess_prototype_v3.backend.processes.gui.process.GuiProcess"
    camera_type: str = "simulator"
    window_title: str = "Inspector Prototype"
    window_width: int = 1024
    window_height: int = 600
    poll_interval_ms: int = 16
    recipes_path: str | None = None
    settings_recipes_path: str | None = None
    recipe_access: dict[str, Any] | None = None
    touch_keyboard: dict[str, Any] | None = Field(default_factory=lambda: {"mode": "full"})
