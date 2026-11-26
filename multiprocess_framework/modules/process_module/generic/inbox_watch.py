# -*- coding: utf-8 -*-
"""inbox_watch — «груз ждёт в очереди, а прогресс стоит» (Task 2.2e, ADR-PM-065).

Purpose: сторож застоя входа (data-очередь) и обработки (``chain_queue``) одного процесса.
Процесс жив, heartbeat идёт, а груз не берётся — сторож отдаёт причину ``out_of_spec``.

Public API: ``INBOX_STALL_KEY`` (ключ конфига процесса), ``parse_stall_s`` (разбор ключа),
``InboxWatch`` (``observe(running, progress, depth) -> list[dict]``).

Stability: lite

Pre: ``observe()`` одного экземпляра зовёт один поток (поток снимка готовности).
Post: ``observe`` возвращает ``[]`` или ровно одну причину ``{node, severity, reason, source}``
(каждый раз новый dict). ``parse_stall_s`` возвращает ``(порог | None, текст | None)`` и не бросает.
Invariants: причина только при ``running``, известных ``progress``/``depth``, ``depth > 0`` и
``progress`` без изменений не меньше ``stall_s`` подряд; не ``running`` или неизвестный вход
сбрасывает накопленный срок.
"""

from __future__ import annotations

import time
from collections.abc import Callable

__all__ = ["INBOX_STALL_KEY", "InboxWatch", "parse_stall_s"]

INBOX_STALL_KEY = "inbox_stall_s"
_MIN_S, _MAX_S = 1.0, 600.0
_BAD = f"{INBOX_STALL_KEY} негоден: ждали число {_MIN_S}–{_MAX_S} с или 0 — предупреждение выключено"
_clock = time.monotonic  # тесты подменяют атрибут модуля


def parse_stall_s(raw: object) -> tuple[float | None, str | None]:
    """(порог, текст WARNING). None и 0 — выключено молча; негодное — выключено, текст без значения входа."""
    if raw is None or (type(raw) in (int, float) and raw == 0):
        return None, None
    if type(raw) not in (int, float) or not (_MIN_S <= raw <= _MAX_S):
        return None, _BAD
    return float(raw), None


class InboxWatch:
    """Pre: observe() зовёт один поток (снимок готовности). Post: [] или ровно одна причина out_of_spec.
    Invariant: причина только при running, известных progress/depth, depth > 0 и progress без изменений >= stall_s."""

    def __init__(
        self, node: str, reason: str, source: str, stall_s: float, clock: Callable[[], float] | None = None
    ) -> None:
        self._stall_s = stall_s
        self._clock = clock
        self._since: float | None = None
        self._last: int | None = None
        self._reason = {"node": node, "severity": "out_of_spec", "reason": reason, "source": source}

    def observe(self, running: bool, progress: int | None, depth: int | None) -> list[dict]:
        if not running or progress is None or depth is None:
            self._since = self._last = None
            return []
        now = self._clock() if self._clock is not None else _clock()
        moved = progress != self._last
        self._last = progress
        if moved or depth <= 0:
            self._since = now if depth > 0 else None
            return []
        if self._since is None:
            self._since = now
            return []
        return [dict(self._reason)] if now - self._since >= self._stall_s else []
