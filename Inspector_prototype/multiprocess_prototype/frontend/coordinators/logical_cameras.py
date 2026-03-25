# multiprocess_prototype/frontend/coordinators/logical_cameras.py
"""Логические id камер для ROI/постобработки и сидирование матрёшки processor."""

from __future__ import annotations

from copy import deepcopy
from typing import List, Optional

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER
from multiprocess_prototype.registers.schemas.processing_tab import PROCESSOR_REGISTER
from multiprocess_prototype.registers.schemas.processing_tab.crop_regions_payload import (
    merge_crop_regions_payload,
)
from multiprocess_prototype.registers.schemas.processing_tab.post_processing_payload import (
    normalize_post_processing_payload,
)

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
    full ROI и пустой список постобработки для этого id.

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

    crop = deepcopy(getattr(proc, "crop_regions", None) or {})
    if not isinstance(crop, dict):
        crop = {}
    inner = crop.get(logical_id)
    need_seed = logical_id not in crop or not isinstance(inner, dict) or len(inner) == 0
    if need_seed:
        merged = merge_crop_regions_payload(
            {
                logical_id: {
                    DEFAULT_FULL_REGION_NAME: [0, 0, w, h],
                },
            }
        )
        crop.update(merged)
        rm.set_field_value(PROCESSOR_REGISTER, "crop_regions", crop)

    proc = rm.get_register(PROCESSOR_REGISTER)
    if proc is None:
        return
    post = deepcopy(getattr(proc, "post_processing_regions", None) or {})
    if not isinstance(post, dict):
        post = {}
    if logical_id not in post:
        post[logical_id] = []
        post = normalize_post_processing_payload(post)
        rm.set_field_value(PROCESSOR_REGISTER, "post_processing_regions", post)
