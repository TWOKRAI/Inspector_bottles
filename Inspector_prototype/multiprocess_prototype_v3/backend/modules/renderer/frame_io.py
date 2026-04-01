"""Чтение original + mask из detection_result (SHM)."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from multiprocess_prototype_v2.backend.shared import message_as_dict
from multiprocess_prototype_v2.utils.shm_utils import read_frame_from_shm


def read_frames_from_detection_result(
    msg,
    memory_manager,
    *,
    log_info: Optional[Callable[..., None]] = None,
    log_warning: Optional[Callable[..., None]] = None,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], dict]:
    if msg is None:
        return None, None, {}
    msg_dict = message_as_dict(msg)
    if msg_dict.get("data_type") != "detection_result":
        return None, None, {}
    data = msg_dict.get("data", {})
    frame_id = data.get("frame_id", 0)
    if log_info and (frame_id <= 3 or frame_id % 50 == 0):
        log_info(f"[DEBUG] renderer: detection_result received frame_id={frame_id}")
    shm_index = data.get("shm_index", 0)
    width = data.get("width", 640)
    height = data.get("height", 480)
    shm_actual_name = data.get("shm_actual_name")
    mask_shm_index = data.get("mask_shm_index", 0)
    mask_shm_actual_name = data.get("mask_shm_actual_name")
    mm = memory_manager

    frame = None
    if mm:
        images = mm.read_images("camera", "camera_frame", shm_index, n=1)
        if images:
            frame = images[0].copy()
    if frame is None and shm_actual_name:
        frame = read_frame_from_shm(shm_actual_name, width, height)
        if frame is not None:
            frame = frame.copy()
    if frame is None:
        if log_warning:
            log_warning(f"[DEBUG] renderer: frame is None for frame_id={frame_id}")
        return None, None, {}

    if (frame.shape[0] != height or frame.shape[1] != width) and cv2 is not None:
        frame = cv2.resize(
            frame,
            (width, height),
            interpolation=cv2.INTER_LINEAR,
        )

    mask_frame = None
    if mm and mask_shm_actual_name:
        images = mm.read_images("processor", "processor_mask", mask_shm_index, n=1)
        if images:
            mask_frame = images[0].copy()
    if mask_frame is None and mask_shm_actual_name:
        mask_frame = read_frame_from_shm(mask_shm_actual_name, width, height)
        if mask_frame is not None:
            mask_frame = mask_frame.copy()
    if mask_frame is None:
        mask_frame = np.zeros((height, width, 3), dtype=np.uint8)

    return frame, mask_frame, data
