"""Ring-buffer для SHM кадров (AD-6).

Writer записывает кадры round-robin по K слотам.
Reader-ы отслеживают свой прогресс через seq_id.
Координация через IPC-сообщения (frame_ready с seq_id/slot_index),
НЕ через shared mutable state.

Политика drop-oldest: если consumer отстаёт на K-1 кадров,
его read_ptr принудительно сдвигается вперёд.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class _ConsumerState:
    """Состояние consumer-а внутри writer (для drop-oldest проверки)."""
    last_read_seq: int = -1
    drops_count: int = 0


class RingBufferWriter:
    """Писатель ring-buffer: round-robin по K SHM-слотам.

    Работает ВНУТРИ одного процесса (CameraProcess).
    Не обращается к SHM напрямую — делегирует в memory_manager.
    """

    def __init__(
        self,
        memory_manager,
        owner: str,
        slot_prefix: str,
        k: int = 3,
    ) -> None:
        self._mm = memory_manager
        self._owner = owner
        self._slot_prefix = slot_prefix
        self._k = k
        self._write_ptr: int = 0
        self._seq_id: int = 0
        self._consumers: dict[str, _ConsumerState] = {}

    @property
    def k(self) -> int:
        return self._k

    @property
    def seq_id(self) -> int:
        return self._seq_id

    def register_consumer(self, consumer_id: str) -> None:
        """Зарегистрировать consumer для отслеживания drop-oldest."""
        if consumer_id not in self._consumers:
            self._consumers[consumer_id] = _ConsumerState(last_read_seq=-1)

    def unregister_consumer(self, consumer_id: str) -> None:
        self._consumers.pop(consumer_id, None)

    def _slot_name(self) -> str:
        """Имя SHM-слота: единственный слот с coll=K индексами."""
        return self._slot_prefix

    def can_write(self) -> bool:
        """Можно ли безопасно писать в текущий слот (все consumers прочли)."""
        if not self._consumers:
            return True
        # Кадр в текущем write_ptr был записан с seq_id = self._seq_id - K
        # (K шагов назад). Если все consumers уже прочли этот seq_id — безопасно.
        old_seq = self._seq_id - self._k
        if old_seq < 0:
            return True  # Буфер ещё не заполнен полностью
        return all(c.last_read_seq >= old_seq for c in self._consumers.values())

    def _force_advance_lagging(self) -> None:
        """Drop-oldest: принудительно сдвинуть отставших consumer-ов."""
        threshold = self._seq_id - self._k + 1
        if threshold < 0:
            return
        for c in self._consumers.values():
            if c.last_read_seq < threshold:
                gap = threshold - c.last_read_seq - 1
                c.drops_count += gap
                c.last_read_seq = threshold - 1

    def write(self, frame: np.ndarray) -> tuple[int, int]:
        """Записать кадр в ring-buffer.

        Returns:
            (slot_index, seq_id) — индекс слота и монотонный номер кадра.
        """
        self._force_advance_lagging()

        slot_index = self._write_ptr
        self._mm.write_images(self._owner, self._slot_name(), [frame], slot_index)

        current_seq = self._seq_id
        self._seq_id += 1
        self._write_ptr = (self._write_ptr + 1) % self._k

        return slot_index, current_seq

    def get_consumer_drops(self, consumer_id: str) -> int:
        """Количество дропнутых кадров для consumer-а."""
        state = self._consumers.get(consumer_id)
        return state.drops_count if state else 0

    def get_total_drops(self) -> dict[str, int]:
        """Дропы всех consumer-ов."""
        return {cid: c.drops_count for cid, c in self._consumers.items()}


@dataclass
class RingBufferReader:
    """Читатель ring-buffer: отслеживает свой seq_id прогресс.

    Работает на стороне consumer-а (Processor, Display, etc.).
    Не координируется с writer напрямую — только через IPC-сообщения.
    """
    memory_manager: object
    owner: str
    slot_prefix: str
    k: int
    consumer_id: str
    _last_read_seq: int = field(default=-1, init=False)
    _drops_count: int = field(default=0, init=False)

    @property
    def last_read_seq(self) -> int:
        return self._last_read_seq

    @property
    def drops_count(self) -> int:
        return self._drops_count

    def read(self, slot_index: int, seq_id: int) -> Optional[np.ndarray]:
        """Прочитать кадр из SHM по slot_index.

        Проверяет seq_id на пропуски (drops). Если seq_id не следующий за
        last_read — считаем кадры между ними пропущенными.

        Returns:
            np.ndarray кадр или None при ошибке чтения.
        """
        expected_seq = self._last_read_seq + 1
        if seq_id > expected_seq:
            self._drops_count += seq_id - expected_seq

        frames = self.memory_manager.read_images(self.owner, self.slot_prefix, slot_index)
        if frames is None:
            return None

        self._last_read_seq = seq_id
        return frames[0] if isinstance(frames, list) and frames else frames
