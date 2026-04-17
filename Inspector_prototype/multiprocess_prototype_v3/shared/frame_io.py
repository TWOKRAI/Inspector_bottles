"""Unified SHM frame I/O for all services."""

from __future__ import annotations

import struct
from multiprocessing import shared_memory
from typing import Callable, Optional, Tuple

import numpy as np


def read_frame_from_shm(shm_actual_name: str, width: int, height: int) -> Optional[np.ndarray]:
    """Read a frame from SharedMemory by name (MemoryManager format)."""
    if not shm_actual_name or not isinstance(shm_actual_name, str):
        return None
    try:
        shm = shared_memory.SharedMemory(name=shm_actual_name, create=False)
        try:
            buffer = shm.buf
            num_images = struct.unpack("I", buffer[0:4])[0]
            if num_images == 0:
                return None
            offset = 4
            h, w, c = struct.unpack("III", buffer[offset:offset + 12])
            offset += 12
            dtype_char = chr(buffer[offset])
            dtype = np.dtype(dtype_char)
            offset += 1
            arr = np.frombuffer(buffer, dtype=dtype, count=h * w * c, offset=offset)
            result = arr.reshape((h, w, c)).copy()
            del arr
            return result
        finally:
            shm.close()
    except FileNotFoundError:
        return None
    except Exception:
        return None


def read_frame_from_msg(
    msg,
    memory_manager,
    *,
    expected_data_type: str = "frame_ready",
    owner: str = "camera",
    slot: str = "camera_frame",
) -> Tuple[Optional[np.ndarray], dict]:
    """Read a frame from a message (MemoryManager first, SHM fallback)."""
    if msg is None:
        return None, {}
    msg_dict = message_as_dict(msg)
    data_type = msg_dict.get("data_type") or (msg_dict.get("data") or {}).get("data_type")
    if data_type != expected_data_type:
        return None, {}
    data = msg_dict.get("data", {})
    shm_index = data.get("shm_index", 0)
    width = data.get("width", 640)
    height = data.get("height", 480)
    shm_actual_name = data.get("shm_actual_name")

    frame = None
    if memory_manager:
        images = memory_manager.read_images(owner, slot, shm_index, n=1)
        if images:
            frame = images[0]
    if frame is None and shm_actual_name:
        frame = read_frame_from_shm(shm_actual_name, width, height)
    return frame, data


def write_frame_to_shm(
    memory_manager,
    owner: str,
    slot: str,
    frame: np.ndarray,
) -> Tuple[Optional[str], int]:
    """Write a frame to SHM. Returns (shm_name, index) or (None, 0)."""
    if frame is None or not memory_manager:
        return None, 0
    free_idx = memory_manager.find_free_index(owner, slot) or 0
    shm_name = memory_manager.write_images(owner, slot, [frame], free_idx)
    return (shm_name, free_idx) if shm_name else (None, 0)


def message_as_dict(msg) -> dict:
    """Convert message to dict (dict passthrough, .to_dict() fallback)."""
    if msg is None:
        return {}
    if isinstance(msg, dict):
        return msg
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    return {}
