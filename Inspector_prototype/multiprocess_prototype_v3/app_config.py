"""All process configs for Inspector Prototype v3.

Consolidates ProcessConfigBase, proc_dict assembly, and all 6 process configs.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)
from multiprocess_framework.modules.process_module import (
    ManagersConfig,
    ProcessPriorityLevel,
    managers_from_log_dir,
    managers_payload_for_proc,
)

# ---------------------------------------------------------------------------
# Log dir
# ---------------------------------------------------------------------------

_PROTO_ROOT = Path(__file__).resolve().parent


def _get_log_dir() -> str:
    default = _PROTO_ROOT / "logs"
    return os.environ.get("INSPECTOR_LOG_DIR") or str(default)


# ---------------------------------------------------------------------------
# Managers config (framework defaults + merge)
# ---------------------------------------------------------------------------

def _get_default_managers_config(log_dir: str | None = None) -> Dict[str, Any]:
    ld = log_dir or _get_log_dir()
    return managers_payload_for_proc(managers_from_log_dir(ld, model_cls=ManagersConfig))


def _merge_managers(base: Dict[str, Any], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not overlay:
        return copy.deepcopy(base)

    def _deep(a: dict, b: dict) -> dict:
        out = copy.deepcopy(a)
        for k, v in b.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deep(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
        return out

    return _deep(base, overlay)


# ---------------------------------------------------------------------------
# ProcessConfigBase
# ---------------------------------------------------------------------------

DEFAULT_QUEUES: Dict[str, Any] = {
    "system": {"maxsize": 100},
    "data": {"maxsize": 50},
}


def class_path_from_type(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


class ProcessConfigBase(SchemaBase):
    """Base config for all processes. Subclass and set process_name + class_path."""

    process_name: str = "base"
    class_path: str = ""
    priority: Union[str, ProcessPriorityLevel] = ProcessPriorityLevel.NORMAL
    queues: Optional[Dict[str, Any]] = None

    @property
    def memory(self) -> Optional[Dict[str, Any]]:
        return None

    def managers_overlay(self) -> Optional[Dict[str, Any]]:
        return None

    def build(self) -> tuple[str, dict]:
        queues = self.queues if self.queues is not None else DEFAULT_QUEUES
        priority = self.priority.value if hasattr(self.priority, "value") else self.priority
        proc_dict: dict = {
            "class": self.class_path,
            "queues": queues,
            "priority": priority,
            "workers": {},
            "config": self.model_dump(),
            "managers": _merge_managers(
                _get_default_managers_config(), self.managers_overlay()
            ),
        }
        if self.memory is not None:
            proc_dict["memory"] = self.memory
        return self.process_name, proc_dict


# ---------------------------------------------------------------------------
# SHM constants
# ---------------------------------------------------------------------------

CAMERA_SHM_WIDTH = 1920
CAMERA_SHM_HEIGHT = 1080


# ---------------------------------------------------------------------------
# Concrete configs
# ---------------------------------------------------------------------------

@register_schema("CameraConfigV3")
class CameraConfig(ProcessConfigBase):
    process_name: str = "camera"
    class_path: str = "multiprocess_prototype_v3.services.camera.process.UnifiedCameraProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    camera_type: str = "simulator"
    fps: int = 25
    resolution_width: int = 640
    resolution_height: int = 480
    device_id: int = 0
    camera_index: int = 0
    hikvision_resolution_width: int = 1920
    hikvision_resolution_height: int = 1080
    hikvision_frame_rate: float = 25.0
    hikvision_exposure_time: float = 10000.0
    hikvision_gain: float = 0.0
    use_simulator: bool = False
    simulator_image_path: Optional[str] = None

    @property
    def memory(self) -> dict:
        return {"camera_frame": (CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH, 3), "coll": 2}

    def build(self) -> tuple[str, dict]:
        name, proc_dict = super().build()
        use_sim = self.use_simulator or (self.camera_type == "simulator")
        proc_dict["config"]["use_simulator"] = use_sim
        return name, proc_dict


@register_schema("ProcessorConfigV3")
class ProcessorConfig(ProcessConfigBase):
    process_name: str = "processor"
    class_path: str = "multiprocess_prototype_v3.services.processor.process.ProcessorProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    resolution_width: int = 640
    resolution_height: int = 480
    color_lower: List[int] = Field(default_factory=lambda: [0, 0, 150])
    color_upper: List[int] = Field(default_factory=lambda: [100, 100, 255])
    min_area: int = 500
    max_area: int = 50000

    @property
    def memory(self) -> dict:
        return {"processor_mask": (self.resolution_height, self.resolution_width, 3), "coll": 2}


@register_schema("RendererConfigV3")
class RendererConfig(ProcessConfigBase):
    process_name: str = "renderer"
    class_path: str = "multiprocess_prototype_v3.services.renderer.process.RendererProcess"
    output_dir: str = "./output_frames"
    resolution_width: int = 640
    resolution_height: int = 480
    show_original: bool = True
    show_mask: bool = True
    draw_contours: bool = True
    draw_bboxes: bool = True
    save_frames: bool = False

    @property
    def memory(self) -> dict:
        shape = (self.resolution_height, self.resolution_width, 3)
        return {"rendered_frame": shape, "mask_frame": shape, "coll": 2}


@register_schema("RobotConfigV3")
class RobotConfig(ProcessConfigBase):
    process_name: str = "robot"
    class_path: str = "multiprocess_prototype_v3.services.robot.process.RobotSimulatorProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.LOW
    queues: dict = Field(default_factory=lambda: {"system": {"maxsize": 50}, "data": {"maxsize": 20}})
    log_file: str = "./robot_actions.log"
    reject_delay: Annotated[float, FieldMeta("Задержка отбраковки, сек", min=0.0, max=5.0)] = 0.5


@register_schema("DatabaseConfigV3")
class DatabaseConfig(ProcessConfigBase):
    process_name: str = "database"
    class_path: str = "multiprocess_prototype_v3.services.database.process.DatabaseProcess"
    db_url: str = Field(default_factory=lambda: f"sqlite:///{_PROTO_ROOT / 'database' / 'inspector.db'}")
    db_dialect: str = "sqlite"
    schema_module_path: str = "multiprocess_prototype_v3.services.database.schema.DetectionSchema"
    schema_class_name: str = "DetectionSchema"


@register_schema("GuiConfigV3")
class GuiConfig(ProcessConfigBase):
    process_name: str = "gui"
    class_path: str = "multiprocess_prototype_v3.services.gui.process.GuiProcess"
    camera_type: str = "simulator"
    window_title: str = "Inspector Prototype"
    window_width: int = 1024
    window_height: int = 600
    poll_interval_ms: int = 16
    recipes_path: Optional[str] = None
    settings_recipes_path: Optional[str] = None
    recipe_access: Optional[Dict[str, Any]] = None
    touch_keyboard: Optional[Dict[str, Any]] = Field(default_factory=lambda: {"mode": "full"})
