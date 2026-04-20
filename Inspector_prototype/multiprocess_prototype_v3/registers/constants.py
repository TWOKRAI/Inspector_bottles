"""Single source of truth: register names, routing channels, shared defaults."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import FieldRouting

# --- Register names (keys in RegistersManager / connection_map) ---
CAMERA_REGISTER = "camera"
PROCESSOR_REGISTER = "processor"
RENDERER_REGISTER = "renderer"

# --- Routing channels ---
CAMERA_ROUTING = FieldRouting(channel="control_camera")
CONTROL_PROCESSOR_1_ROUTING = FieldRouting(channel="control_processor_1")
CONTROL_PROCESSOR_2_ROUTING = FieldRouting(channel="control_processor_2")
PIPELINE_PARAMS_ROUTING = FieldRouting(channel="control_processor")
RENDERER_ROUTING = FieldRouting(channel="control_renderer")

# --- Shared defaults ---
DEFAULT_RESOLUTION_WIDTH = 640
DEFAULT_RESOLUTION_HEIGHT = 480
DEFAULT_HIKVISION_WIDTH = 1920
DEFAULT_HIKVISION_HEIGHT = 1080
DEFAULT_FPS = 25
DEFAULT_COLOR_LOWER = [0, 0, 150]
DEFAULT_COLOR_UPPER = [100, 100, 255]
DEFAULT_MIN_AREA = 500
DEFAULT_MAX_AREA = 50000

__all__ = [
    "CAMERA_REGISTER", "PROCESSOR_REGISTER", "RENDERER_REGISTER",
    "CAMERA_ROUTING", "CONTROL_PROCESSOR_1_ROUTING", "CONTROL_PROCESSOR_2_ROUTING",
    "PIPELINE_PARAMS_ROUTING", "RENDERER_ROUTING",
    "DEFAULT_RESOLUTION_WIDTH", "DEFAULT_RESOLUTION_HEIGHT",
    "DEFAULT_HIKVISION_WIDTH", "DEFAULT_HIKVISION_HEIGHT",
    "DEFAULT_FPS",
    "DEFAULT_COLOR_LOWER", "DEFAULT_COLOR_UPPER",
    "DEFAULT_MIN_AREA", "DEFAULT_MAX_AREA",
]
