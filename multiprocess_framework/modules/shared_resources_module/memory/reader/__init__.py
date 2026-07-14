"""Reader-side кадровый тракт SHM за фасадом (Ф7 H-задача, Этап 2).

`FrameReader` (Protocol) + `ShmFrameReader` (реализация): кэш handles + zero-copy view +
post-use re-check. Транспорт (`FrameShmMiddleware`) держит reader через DI и делегирует —
кэш/view больше не размазаны по router-модулю, синхронизация — внутреннее дело reader'а.
"""

from .interfaces import FrameReader
from .shm_frame_reader import ShmFrameReader

__all__ = ["FrameReader", "ShmFrameReader"]
