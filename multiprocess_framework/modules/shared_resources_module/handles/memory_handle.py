"""
MemoryHandle — обёртка над SharedMemory для конкретного блока памяти.

Использование:
    mem = handle.memory("frame")
    mem.write(images, index=idx)
    imgs = mem.read(index=0)
"""

from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from ..memory.core import MemoryManager


class MemoryHandle:
    """
    Обёртка над MemoryManager для одного блока SharedMemory.

    Привязана к конкретному process_name + memory_name.
    Делегирует вызовы в MemoryManager.
    """

    __slots__ = ("_mm", "_process_name", "_memory_name")

    def __init__(
        self,
        memory_manager: "MemoryManager",
        process_name: str,
        memory_name: str,
    ) -> None:
        self._mm = memory_manager
        self._process_name = process_name
        self._memory_name = memory_name

    def write(
        self,
        images: "List[np.ndarray]",
        index: int,
        *,
        pack_fast: bool = True,
    ) -> Optional[str]:
        """Записать изображения в слот. Возвращает shm.name или None."""
        return self._mm.write_images(
            self._process_name,
            self._memory_name,
            images,
            index,
            pack_fast=pack_fast,
        )

    def read(
        self,
        index: int,
        n: int = -1,
        *,
        copy: bool = True,
    ) -> Optional[List[Any]]:
        """Прочитать изображения из слота."""
        return self._mm.read_images(
            self._process_name,
            self._memory_name,
            index,
            n,
            copy=copy,
        )

    def release(self, index: int) -> None:
        """Освободить слот (очистить). Ф7 G.H: find_free_index снят (мёртвый учёт);
        реальный free-list — за фасадом `memory.pool.FramePool` (loan-протокол)."""
        self._mm.release_memory(self._process_name, self._memory_name, index)

    def close(self) -> None:
        """Закрыть и освободить SharedMemory блок."""
        self._mm.close_memory(self._process_name, self._memory_name)

    @property
    def exists(self) -> bool:
        """Проверить, существует ли данный блок памяти."""
        data = self._mm.get_memory_data(self._process_name, self._memory_name)
        return data is not None

    def __repr__(self) -> str:
        return f"MemoryHandle('{self._process_name}', '{self._memory_name}')"
