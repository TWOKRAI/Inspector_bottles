"""``LoanLedger`` — реализация `FramePool` руками на CPython (Ф7 H-задача).

Перенос семантики владения слотом из `router_module/FrameShmMiddleware` (G.5.d/e) за фасад
модуля памяти БЕЗ смены поведения: refcount / released-множества / loan-cursor / reclaim.
Чистая структура данных — БЕЗ логирования и БЕЗ знания про формат SHM (generation читается
через инжектированный ``gen_reader``). Логирование/троттлинг — дело транспорта-владельца.

Модель конкурентности — см. `interfaces.FramePool`. Кратко (закреплено кодом, а не
соглашением, ревью фазы G 2026-07-14):

- **Single-writer enforced.** ``acquire``/``commit``/``abort`` зовёт РОВНО ОДИН поток-
  писатель В КАЖДЫЙ МОМЕНТ. Первый ``acquire`` связывает поток; второй ЖИВОЙ поток →
  ``RuntimeError`` (не тихая порча); мёртвый связанный поток (G.8 drain→replace воркера)
  → перепривязка. Кадровое кольцо — single-writer-multi-reader (seqlock, ADR-SRM-011).
- **State-машина слота (lock-free disjointness).** ``acquire`` РЕЗЕРВИРУЕТ слот
  (``_reserved[idx]=True``, состояние WRITING, refcount==0); ``commit`` публикует
  (refcount=N, reserved→False, READY); ``abort`` отменяет loan без publish (reserved→False).
  ``release``/``reclaim`` (поток message_processor владельца) трогают ТОЛЬКО слоты с
  refcount>0 (READY) → с WRITING-слотом писателя не пересекаются ПО ПОСТРОЕНИЮ, без lock.
- Безопасность от torn-кадра даёт seqlock + post-use re-check (В1), НЕ этот учёт; любая
  ошибка учёта безопасна (преждевременное освобождение → writer перезапишет → drift → drop).
"""

from __future__ import annotations

import threading

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
        # State-машина слота: reserved=True → WRITING (acquire выдал loan, commit ещё
        # не опубликовал). release/reclaim (refcount==0 → skip) WRITING-слот не трогают.
        self._reserved: list[bool] = [False] * self._depth
        # Множество читателей, уже отпустивших ТЕКУЩИЙ займ слота (dedup release;
        # чистится при refcount→0).
        self._released: list[set] = [set() for _ in range(self._depth)]
        self._cursor = 0
        # Single-writer guard: ident потока-писателя (первый acquire связывает; второй
        # иной поток → RuntimeError). release/reclaim (другой поток) сюда не заходят.
        self._writer_ident: int | None = None
        # Счётчики наблюдаемости (пул — единственный источник).
        self._released_count = 0
        self._reclaimed_count = 0
        self._exhausted_count = 0

    @property
    def depth(self) -> int:
        return self._depth

    def _bind_writer(self) -> None:
        """Single-writer guard: первый ``acquire`` связывает поток-писатель; ВТОРОЙ
        ЖИВОЙ поток → ``RuntimeError`` (нарушение single-writer, а не тихая
        write-write порча).

        Последовательная СМЕНА писателя легитимна (G.8 drain→detach→stop воркера,
        затем create нового: middleware/пул переживают воркера) — «один писатель
        В КАЖДЫЙ МОМЕНТ», а не «один навсегда». При несовпадении ident проверяем,
        жив ли связанный поток (скан ``threading.enumerate`` — только на холодном
        пути смены, не на hot-path): мёртв → перепривязка; жив → RuntimeError.

        release/reclaim идут на потоке message_processor владельца — они СЮДА не заходят
        (их поток легитимно другой; они трогают только READY-слоты). Проверка — один
        ``get_ident`` + сравнение int (наносекунды против memcpy кадра).
        """
        ident = threading.get_ident()
        if self._writer_ident is None:
            self._writer_ident = ident
            return
        if self._writer_ident == ident:
            return
        # Холодный путь: ident сменился. Прежний писатель мёртв (G.8 drain→replace)
        # → перепривязка; жив → два одновременных писателя, громкий отказ.
        if any(t.ident == self._writer_ident for t in threading.enumerate()):
            raise RuntimeError(
                "LoanLedger: обнаружен ВТОРОЙ писатель кадрового кольца "
                f"(owner-thread={self._writer_ident}, нарушитель={ident}) — кольцо "
                "рассчитано на ОДНОГО писателя (single-writer-multi-reader, seqlock). "
                "Разнесите source и processing по разным процессам."
            )
        self._writer_ident = ident

    def acquire(self) -> int | None:
        """Loan: зарезервировать СВОБОДНЫЙ слот (refcount==0 и не reserved) от курсора.

        Помечает слот WRITING (``_reserved[idx]=True``) — release/reclaim его не трогают
        (refcount==0 → skip), пока ``commit`` не опубликует или ``abort`` не отменит loan.
        None → все слоты заняты/в записи (исчерпание, счётчик). Single-writer enforced.
        """
        self._bind_writer()
        n = self._depth
        for i in range(n):
            idx = (self._cursor + i) % n
            if self._refcount[idx] == 0 and not self._reserved[idx]:
                self._reserved[idx] = True
                self._cursor = (idx + 1) % n
                return idx
        self._exhausted_count += 1
        return None

    def commit(self, idx: int, num_consumers: int) -> None:
        """Publish: опубликовать слот — refcount = число loan-aware потребителей (fan-out).

        Снимает резерв (WRITING→READY): теперь release/reclaim могут декрементить слот.
        """
        if 0 <= idx < self._depth:
            self._refcount[idx] = max(1, int(num_consumers))
            self._reserved[idx] = False

    def abort(self, idx: int) -> None:
        """Отменить loan без publish (write не удался): вернуть слот в free (reserved→False).

        Без этого неудачная запись оставила бы слот WRITING навсегда → утечка ёмкости
        кольца до исчерпания. loan ОБЯЗАН завершиться commit'ом ИЛИ abort'ом (iceoryx2).
        """
        if 0 <= idx < self._depth:
            self._reserved[idx] = False

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
        """Сброс в «всё свободно» (realloc кольца). Счётчики наблюдаемости НЕ обнуляются.

        ``_writer_ident`` НЕ сбрасывается: realloc идёт на том же потоке-писателе (owner),
        связка писателя сохраняется через цикл realloc.
        """
        self._refcount = [0] * self._depth
        self._reserved = [False] * self._depth
        self._released = [set() for _ in range(self._depth)]
        self._cursor = 0

    def snapshot_stats(self) -> PoolStats:
        return {
            "slots_released": self._released_count,
            "slots_reclaimed": self._reclaimed_count,
            "loan_exhausted": self._exhausted_count,
        }


__all__ = ["LoanLedger"]
