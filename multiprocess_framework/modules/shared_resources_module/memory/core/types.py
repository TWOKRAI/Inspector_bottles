"""
Внутренние типы memory-подмодуля.

_MemoryMeta — метаданные одного shm-блока для standalone-режима (без PSR).
"""

from typing import List


class _MemoryMeta:
    """Метаданные одного shm-блока (params, index_usage, coll, seqlock)."""

    __slots__ = ("params", "index_usage", "coll", "seqlock")

    def __init__(self, params: tuple, coll: int, seqlock: bool = False) -> None:
        self.params = params  # (num_images, image_shape, dtype)
        self.index_usage: List[int] = [0] * coll
        self.coll: int = coll
        # Ф7 G.3(b): формат слота seqlock (8-байтовый SLOT-header). Стампуется при
        # создании — write/read/size блока самосогласованы (ADR-SRM-011).
        self.seqlock: bool = seqlock
