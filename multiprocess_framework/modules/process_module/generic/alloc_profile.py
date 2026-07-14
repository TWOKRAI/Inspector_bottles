# -*- coding: utf-8 -*-
"""alloc_profile — профиль аллокаций на кадр через tracemalloc (Ф7 G.9(b)).

Soak-диагностика (НЕ production hot-path): измеряет, сколько байт/блоков аллоцируется на
кадр на per-frame пути, чтобы (1) дать число «аллокаций/кадр» в baseline.md и (2) увидеть
эффект gc.freeze (G.9(a)) и снятия двойной конверсии (G.5) до/после. tracemalloc сам
аллоцирует и тормозит — поэтому это ИНСТРУМЕНТ ЗАМЕРА, включаемый на soak-прогоне, а не
всегда-on проба (в отличие от latency perf_probes).

Использование (harness G.7-соака):

    prof = AllocProfiler()
    prof.start()
    prof.mark()                      # baseline-снимок
    for _ in range(frames):
        ... прогнать кадр ...
    stats = prof.per_frame(frames)   # {"bytes_per_frame", "blocks_per_frame", "top": [...]}
    prof.stop()

Число «аллокаций/кадр» из ``per_frame`` идёт в ``baseline.md`` (tier помечать, как в G.1).
"""

from __future__ import annotations

import tracemalloc
from typing import Any, Dict, List, Optional, Tuple


class AllocProfiler:
    """Профиль аллокаций между двумя точками через tracemalloc snapshot-diff.

    Инкапсулирует tracemalloc, чтобы harness не дёргал глобальное состояние напрямую и
    случайно не оставил профайлер включённым (``stop`` идемпотентен). Не для production —
    только для soak-замеров G.7.
    """

    def __init__(self, *, nframes_top: int = 10) -> None:
        self._nframes_top = max(1, int(nframes_top))
        self._baseline: Optional[Any] = None
        self._started_here = False

    def start(self) -> None:
        """Включить tracemalloc (если ещё не включён кем-то). Идемпотентно."""
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            self._started_here = True

    def mark(self) -> None:
        """Зафиксировать baseline-снимок (точка отсчёта для diff)."""
        self._baseline = tracemalloc.take_snapshot()

    def per_frame(self, frames: int) -> Dict[str, Any]:
        """Diff текущего снимка с baseline, нормированный на число кадров.

        Возвращает ``{bytes_per_frame, blocks_per_frame, total_bytes, total_blocks, top}``,
        где ``top`` — крупнейшие источники аллокаций (файл:строка, +байт). ``frames`` ≥ 1.
        """
        if self._baseline is None:
            raise RuntimeError("AllocProfiler.per_frame до mark(): нет baseline-снимка")
        frames = max(1, int(frames))
        current = tracemalloc.take_snapshot()
        diff = current.compare_to(self._baseline, "lineno")
        total_bytes = sum(d.size_diff for d in diff)
        total_blocks = sum(d.count_diff for d in diff)
        top: List[Tuple[str, int, int]] = [
            (str(d.traceback), d.size_diff, d.count_diff)
            for d in sorted(diff, key=lambda x: x.size_diff, reverse=True)[: self._nframes_top]
            if d.size_diff > 0
        ]
        return {
            "bytes_per_frame": total_bytes / frames,
            "blocks_per_frame": total_blocks / frames,
            "total_bytes": total_bytes,
            "total_blocks": total_blocks,
            "top": top,
        }

    def stop(self) -> None:
        """Выключить tracemalloc, ЕСЛИ его включил этот профайлер. Идемпотентно."""
        if self._started_here and tracemalloc.is_tracing():
            tracemalloc.stop()
            self._started_here = False
        self._baseline = None


__all__ = ["AllocProfiler"]
