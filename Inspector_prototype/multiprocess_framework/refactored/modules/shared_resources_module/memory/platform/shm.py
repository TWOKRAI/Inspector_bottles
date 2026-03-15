"""
Платформенные операции SharedMemory.

Windows: unlink() — no-op; память освобождается при close последнего handle.
POSIX (Linux/macOS): unlink() освобождает сегмент; stale shm персистит до unlink.
"""

import platform
from multiprocessing import shared_memory
from typing import List, Optional

# Тип для SharedMemory (Any для избежания прямого импорта в интерфейсах)
ShmType = shared_memory.SharedMemory


def is_windows() -> bool:
    """Проверка платформы Windows."""
    return platform.system() == "Windows"


def is_posix() -> bool:
    """Проверка POSIX-платформы (Linux, macOS)."""
    return platform.system() in ("Linux", "Darwin")


def cleanup_stale_shm(name: str) -> None:
    """
    Попытка удалить устаревший POSIX shm сегмент.

    На Windows — no-op (память освобождается при завершении процесса).
    На POSIX — открыть + close + unlink для очистки после аварийного завершения.
    """
    if is_windows():
        return
    try:
        stale = shared_memory.SharedMemory(name=name, create=False)
        stale.close()
        stale.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def create_shm_block(name: str, size: int) -> ShmType:
    """
    Создать блок SharedMemory.

    Перед созданием на POSIX выполняется cleanup_stale_shm для удаления
    устаревших сегментов от предыдущих запусков.

    Returns:
        SharedMemory

    Raises:
        Exception: при ошибке создания
    """
    cleanup_stale_shm(name)
    return shared_memory.SharedMemory(name=name, create=True, size=size)


def open_shm_block(name: str) -> Optional[ShmType]:
    """
    Открыть (attach) существующий блок SharedMemory.

    Returns:
        SharedMemory или None при ошибке
    """
    try:
        return shared_memory.SharedMemory(name=name, create=False)
    except Exception:
        return None


def close_shm(shm: Optional[ShmType], unlink: bool = False) -> None:
    """
    Закрыть SharedMemory с опциональным unlink.

    На Windows unlink() — no-op (документация Python).
    На POSIX unlink освобождает сегмент.

    FileNotFoundError при unlink игнорируется (сегмент уже удалён).
    """
    if shm is None:
        return
    try:
        shm.close()
    except Exception:
        raise
    if unlink and is_posix():
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            raise


def create_shm_blocks(
    base_name: str, size: int, coll: int
) -> Optional[List[ShmType]]:
    """
    Создать coll блоков SharedMemory с именами {base_name}_0, {base_name}_1, ...

    При ошибке создания любого блока — закрывает и удаляет уже созданные,
    возвращает None.
    """
    shm_list: List[ShmType] = []
    try:
        for i in range(coll):
            name = f"{base_name}_{i}"
            shm = create_shm_block(name, size)
            shm_list.append(shm)
        return shm_list
    except Exception:
        for created in shm_list:
            close_shm(created, unlink=True)
        return None
