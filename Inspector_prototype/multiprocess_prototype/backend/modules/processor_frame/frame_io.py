"""Чтение кадра из сообщения frame_ready (SHM)."""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import numpy as np

from multiprocess_prototype.backend.shared import message_as_dict
from multiprocess_prototype.utils.shm_utils import read_frame_from_shm


def read_frame_from_frame_ready(
    msg,
    memory_manager,
    *,
    log_info: Optional[Callable[..., None]] = None,
    log_warning: Optional[Callable[..., None]] = None,
    log_module: str = "processor_frames",
) -> Tuple[Optional[np.ndarray], dict]:
    if msg is None:
        return None, {}
    msg_dict = message_as_dict(msg)
    data_type = msg_dict.get("data_type") or (msg_dict.get("data") or {}).get(
        "data_type"
    )
    if data_type != "frame_ready":
        return None, {}
    data = msg_dict.get("data", {})
    frame_id_log = data.get("frame_id", 0)
    if log_info and (frame_id_log <= 3 or frame_id_log % 50 == 0):
        log_info(
            f"[DEBUG] processor: frame_ready received frame_id={frame_id_log}",
            module=log_module,
        )
    shm_index = data.get("shm_index", 0)
    width = data.get("width", 640)
    height = data.get("height", 480)
    shm_actual_name = data.get("shm_actual_name")
    shm_name = data.get("shm_name", "camera_frame")
    frame = None
    mm = memory_manager
    if mm:
        images = mm.read_images("camera", shm_name, shm_index, n=1)
        if images:
            frame = images[0]
    if frame is None and shm_actual_name:
        frame = read_frame_from_shm(shm_actual_name, width, height)
    if frame is None and log_warning:
        log_warning(
            f"[DEBUG] processor: frame is None for frame_id={frame_id_log}",
            module=log_module,
        )
    return frame, data


def write_mask_to_process_shm(memory_manager, process_name: str, mask) -> Tuple[Any, int]:
    if mask is None:
        return None, 0
    mm = memory_manager
    if not mm:
        return None, 0
    free_idx = mm.find_free_index(process_name, "processor_mask") or 0
    shm_name = mm.write_images(process_name, "processor_mask", [mask], free_idx)
    return (shm_name, free_idx) if shm_name else (None, 0)
