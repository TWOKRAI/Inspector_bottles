"""Публичные контракты phone_gateway.

Protocol вместо ABC — structural subtyping. Единственный файл, от которого
должны зависеть внешние модули (плагин-мост).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class FrameSource(Protocol):
    """Источник кадров, принятых от телефона (то, что нужно плагину-мосту)."""

    def take_frame(self, consume: bool = False) -> np.ndarray | None:
        """Последний принятый кадр (BGR ndarray) или None.

        Args:
            consume: если True — вернуть кадр только один раз на каждую загрузку
                     (дискретный режим); при False — отдавать каждый раз (hold).
        """
        ...

    def word_snapshot(self) -> dict:
        """Последнее принятое слово: {"word": str, "seq": int, "ts": float}."""
        ...
