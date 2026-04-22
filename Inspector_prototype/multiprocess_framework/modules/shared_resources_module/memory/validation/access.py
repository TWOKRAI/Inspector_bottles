"""
Валидация доступа к SharedMemory и операций write/read.
"""

from typing import Any, Dict, List, Optional

from ...types.types import MemoryAccessStatus


def validate_memory_access(
    memory_data: Optional[Dict],
    shm_name: str,
    index: int,
) -> MemoryAccessStatus:
    """
    Проверить доступ к слоту памяти.

    Returns:
        MemoryAccessStatus.OK если доступ валиден, иначе конкретная причина.
    """
    if not memory_data:
        return MemoryAccessStatus.NO_DATA
    if index < 0:
        return MemoryAccessStatus.INVALID_INDEX
    coll = memory_data.get("coll", {})
    if shm_name not in coll or index >= coll[shm_name]:
        return MemoryAccessStatus.INDEX_OUT_OF_RANGE
    handles = memory_data.get("handles")
    if handles is None or index >= len(handles) or handles[index] is None:
        return MemoryAccessStatus.HANDLE_MISSING
    return MemoryAccessStatus.OK


def validate_write_operation(
    memory_data: Optional[Dict],
    shm_name: str,
    index: int,
    num_images: int,
) -> MemoryAccessStatus:
    """
    Проверить возможность записи num_images изображений в слот.
    """
    if not memory_data:
        return MemoryAccessStatus.NO_DATA
    access = validate_memory_access(memory_data, shm_name, index)
    if access != MemoryAccessStatus.OK:
        return access
    params = memory_data.get("params", {})
    if shm_name not in params:
        return MemoryAccessStatus.PARAM_MISSING
    max_images = params[shm_name][0]
    if num_images > max_images:
        return MemoryAccessStatus.EXCEEDS_MAX_IMAGES
    return MemoryAccessStatus.OK


def clear_memory_slot(
    handles: Optional[List[Any]],
    index: int,
) -> None:
    """Обнулить буфер слота памяти."""
    if not handles or index >= len(handles) or handles[index] is None:
        return
    shm = handles[index]
    try:
        shm.buf[:] = b"\x00" * shm.size
    except Exception:
        pass
