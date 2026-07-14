"""``LoanLedger`` — реализация `FramePool` руками на CPython (Ф7 H-задача).

Перенос семантики владения слотом из `router_module/FrameShmMiddleware` (G.5.d/e) за фасад
модуля памяти БЕЗ смены поведения: refcount / released-множества / loan-cursor / reclaim.
Чистая структура данных — БЕЗ логирования и БЕЗ знания про формат SHM (generation читается
через инжектированный ``gen_reader``). Логирование/троттлинг — дело транспорта-владельца.

Модель конкурентности — см. `interfaces.FramePool`: refcount мутирует ТОЛЬКО owner-процесс,
кросс-процессного atomic RMW нет; безопасность от torn даёт seqlock+В1, не этот учёт.
"""

from __future__ import annotations

from .interfaces import GenerationReader, LoanTicket, PoolStats


def _null_gen_reader(_idx: int) -> int:
    """Дефолт: seqlock недоступен → -1 (generation-guard становится no-op)."""
    return -1


class LoanLedger:
    """Free-list слотов кольца с владением по цепочке (loan/publish/release/reclaim).

    Args:
        depth: глубина кольца (число слотов, ≥1).
        gen_reader: читатель текущего поколения СВОЕГО слота idx (owner-side seqlock).
            По умолчанию -1 (без seqlock → guard на generation отключён, как в прежнем
            коде: тикеты тоже несут -1, ``-1 != -1`` ложно → пропуска нет).
    """

    def __init__(self, depth: int, gen_reader: GenerationReader | None = None) -> None:
        self._depth = max(1, int(depth))
        self._gen_reader = gen_reader or _null_gen_reader
        # refcount мутирует ТОЛЬКО owner-процесс (см. класс-докстринг interfaces).
        self._refcount: list[int] = [0] * self._depth
        # Множество читателей, уже отпустивших ТЕКУЩИЙ займ слота (dedup release;
        # чистится при refcount→0).
        self._released: list[set] = [set() for _ in range(self._depth)]
        self._cursor = 0
        # Счётчики наблюдаемости (пул — единственный источник).
        self._released_count = 0
        self._reclaimed_count = 0
        self._exhausted_count = 0

    @property
    def depth(self) -> int:
        return self._depth

    def acquire(self) -> int | None:
        """Взять свободный слот (refcount==0) от ротационного курсора. None → исчерпание."""
        n = self._depth
        for i in range(n):
            idx = (self._cursor + i) % n
            if self._refcount[idx] == 0:
                self._cursor = (idx + 1) % n
                return idx
        self._exhausted_count += 1
        return None

    def commit(self, idx: int, num_consumers: int) -> None:
        """Опубликовать слот: refcount = число loan-aware потребителей (fan-out)."""
        if 0 <= idx < self._depth:
            self._refcount[idx] = max(1, int(num_consumers))

    def release(self, tickets: list[LoanTicket]) -> int:
        """Owner-side release пачки тикетов. Возвращает число освобождённых займов."""
        if not tickets:
            return 0
        freed = 0
        for t in tickets:
            try:
                idx = int(t.get("index", -1))
                gen = int(t.get("generation", -1))
            except (TypeError, ValueError):
                continue
            reader = t.get("reader", "")
            if not (0 <= idx < self._depth) or self._refcount[idx] == 0:
                continue  # свободен (stale/дубликат прошлого займа)
            if self._gen_reader(idx) != gen:
                continue  # release ПРОШЛОГО займа (слот переиспользован)
            if reader in self._released[idx]:
                continue  # дубликат release того же читателя
            self._released[idx].add(reader)
            self._refcount[idx] -= 1
            freed += 1
            if self._refcount[idx] <= 0:
                self._refcount[idx] = 0
                self._released[idx].clear()
        self._released_count += freed
        return freed

    def reclaim(self, dead_reader: str) -> int:
        """Реклейм всех незакрытых займов мёртвого читателя. Идемпотентно."""
        if not dead_reader:
            return 0
        reclaimed = 0
        for idx in range(self._depth):
            if self._refcount[idx] > 0 and dead_reader not in self._released[idx]:
                self._released[idx].add(dead_reader)
                self._refcount[idx] -= 1
                reclaimed += 1
                if self._refcount[idx] <= 0:
                    self._refcount[idx] = 0
                    self._released[idx].clear()
        self._reclaimed_count += reclaimed
        return reclaimed

    def reset(self) -> None:
        """Сброс в «всё свободно» (realloc кольца). Счётчики наблюдаемости НЕ обнуляются."""
        self._refcount = [0] * self._depth
        self._released = [set() for _ in range(self._depth)]
        self._cursor = 0

    def snapshot_stats(self) -> PoolStats:
        return {
            "slots_released": self._released_count,
            "slots_reclaimed": self._reclaimed_count,
            "loan_exhausted": self._exhausted_count,
        }


__all__ = ["LoanLedger"]
