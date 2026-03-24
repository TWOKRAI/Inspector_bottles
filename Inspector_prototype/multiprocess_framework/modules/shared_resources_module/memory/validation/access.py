"""
Валидация доступа к SharedMemory и операций write/read.
"""

from typing import Any, Dict, List, Optional


def validate_memory_access(
    memory_data: Optional[Dict],
    shm_name: str,
    index: int,
) -> bool:
    """
    Проверить доступ к слоту памяти.

    Args:
        memory_data: результат get_memory_data (handles, params, coll, ...)
        shm_name: имя блока памяти
        index: индекс слота

    Returns:
        True если доступ валиден
    """
    if not memory_data:
        return False
    if index < 0:
        return False
    coll = memory_data.get("coll", {})
    if shm_name not in coll or index >= coll[shm_name]:
        return False
    handles = memory_data.get("handles")
    if handles is None or index >= len(handles) or handles[index] is None:
        return False
    return True


def validate_write_operation(
    memory_data: Optional[Dict],
    shm_name: str,
    index: int,
    num_images: int,
) -> bool:
    """
    Проверить возможность записи num_images изображений в слот.

    Args:
        memory_data: результат get_memory_data
        shm_name: имя блока
        index: индекс слота
        num_images: количество изображений для записи

    Returns:
        True если операция допустима
    """
    if not memory_data:
        return False
    if not validate_memory_access(memory_data, shm_name, index):
        return False
    params = memory_data.get("params", {})
    if shm_name not in params:
        return False
    max_images = params[shm_name][0]
    return num_images <= max_images


def clear_memory_slot(
    handles: Optional[List[Any]],
    index: int,
) -> None:
    """
    Обнулить буфер слота памяти.

    Args:
        handles: список SharedMemory объектов
        index: индекс слота
    """
    if not handles or index >= len(handles) or handles[index] is None:
        return
    shm = handles[index]
    try:
        shm.buf[:] = b"\x00" * shm.size
    except Exception:
        pass
