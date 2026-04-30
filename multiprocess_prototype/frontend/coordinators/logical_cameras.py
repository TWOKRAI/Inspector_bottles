# multiprocess_prototype/frontend/coordinators/logical_cameras.py
"""Логические id камер для ROI/постобработки и сидирование vision_pipeline."""

from __future__ import annotations

from typing import List, Optional

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER
from multiprocess_prototype.registers.schemas.pipeline.widget_bridge import (
    apply_crop_nested_to_pipeline,
    crop_nested_from_pipeline,
    pipeline_config_from_register,
)
from multiprocess_prototype.registers.schemas.processing_tab import PROCESSOR_REGISTER

DEFAULT_FULL_REGION_NAME = "full"


def compute_logical_camera_id(
    camera_type: str,
    *,
    device_id: int = 0,
    camera_index: int = 0,
) -> str:
    """Стабильный id: simulator | webcam_<n> | hikvision_<n>."""
    ct = (camera_type or "simulator").strip().lower()
    if ct == "simulator":
        return "simulator"
    if ct == "webcam":
        return f"webcam_{max(0, int(device_id))}"
    if ct == "hikvision":
        return f"hikvision_{max(0, int(camera_index))}"
    return "default"


def ensure_logical_camera_and_seed_roi(
    rm: Optional[IRegistersManagerGui],
) -> None:
    """
    Добавить текущую логическую камеру в logical_camera_ids и при отсутствии —
    регион ``full`` на весь кадр в ``vision_pipeline``.

    Вызывать после смены типа камеры (и при необходимости после старта захвата).
    """
    if rm is None:
        return
    cam = rm.get_register(CAMERA_REGISTER)
    proc = rm.get_register(PROCESSOR_REGISTER)
    if cam is None or proc is None:
        return

    camera_type = str(getattr(cam, "camera_type", "simulator"))
    device_id = int(getattr(cam, "device_id", 0) or 0)
    camera_index = int(getattr(cam, "camera_index", 0) or 0)
    w = max(1, int(getattr(cam, "resolution_width", 640) or 640))
    h = max(1, int(getattr(cam, "resolution_height", 480) or 480))
    if camera_type.strip().lower() == "hikvision":
        w = max(1, int(getattr(cam, "hikvision_resolution_width", w) or w))
        h = max(1, int(getattr(cam, "hikvision_resolution_height", h) or h))

    logical_id = compute_logical_camera_id(
        camera_type,
        device_id=device_id,
        camera_index=camera_index,
    )

    ids: List[str] = list(getattr(proc, "logical_camera_ids", None) or [])
    if logical_id not in ids:
        ids = list(ids) + [logical_id]
        ok, _ = rm.set_field_value(PROCESSOR_REGISTER, "logical_camera_ids", ids)
        if not ok:
            return
        proc = rm.get_register(PROCESSOR_REGISTER)
        if proc is None:
            return

    proc = rm.get_register(PROCESSOR_REGISTER)
    if proc is None:
        return
    nested = crop_nested_from_pipeline(pipeline_config_from_register(proc))
    inner = nested.get(logical_id)
    need_seed = not isinstance(inner, dict) or len(inner) == 0
    if need_seed:
        cfg = apply_crop_nested_to_pipeline(
            pipeline_config_from_register(proc),
            {logical_id: {DEFAULT_FULL_REGION_NAME: [0, 0, w, h]}},
            color_lower=list(proc.color_lower),
            color_upper=list(proc.color_upper),
            min_area=int(proc.min_area),
            max_area=int(proc.max_area),
        )
        rm.set_field_value(
            PROCESSOR_REGISTER,
            "vision_pipeline",
            cfg.model_dump(mode="python"),
        )
