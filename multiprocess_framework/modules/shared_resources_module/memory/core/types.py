"""
Внутренние типы memory-подмодуля.

_MemoryMeta — метаданные одного shm-блока для standalone-режима (без PSR).
"""


class _MemoryMeta:
    """Метаданные одного shm-блока (params, coll, seqlock).

    Ф7 G.H: поле ``index_usage`` снято — это был МЁРТВЫЙ первый учёт занятости
    (писался только в 0, «used=1» никто не ставил → `find_free_index` всегда 0).
    Реальный free-list — за фасадом `memory.pool.FramePool` (owner-side, loan-протокол).
    """

    __slots__ = ("params", "coll", "seqlock")

    def __init__(self, params: tuple, coll: int, seqlock: bool = False) -> None:
        self.params = params  # (num_images, image_shape, dtype)
        self.coll: int = coll
        # Ф7 G.3(b): формат слота seqlock (8-байтовый SLOT-header). Стампуется при
        # создании — write/read/size блока самосогласованы (ADR-SRM-011).
        self.seqlock: bool = seqlock
