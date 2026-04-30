"""
Внутренние типы memory-подмодуля.

_MemoryMeta — метаданные одного shm-блока для standalone-режима (без PSR).
"""

from typing import List


class _MemoryMeta:
    """Метаданные одного shm-блока (params, index_usage, coll)."""

    __slots__ = ("params", "index_usage", "coll")

    def __init__(self, params: tuple, coll: int) -> None:
        self.params = params  # (num_images, image_shape, dtype)
        self.index_usage: List[int] = [0] * coll
        self.coll: int = coll
