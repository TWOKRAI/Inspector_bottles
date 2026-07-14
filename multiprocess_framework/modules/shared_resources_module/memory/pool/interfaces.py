"""Публичный контракт пула кадровых слотов (Ф7 H-задача, консолидация памяти).

`FramePool` — **семантика владения слотом кольца SHM** за фасадом в модуле памяти.
До H-задачи эта логика (~200 строк: free-list, refcount, released-множества, loan-cursor,
reclaim) жила в транспортном `router_module/FrameShmMiddleware` — размазанность памяти по
двум модулям. Здесь она — одна из реализаций (`LoanLedger`) под Protocol; транспорт держит
пул через DI и делегирует. Замена на боевой Rust-транспорт (iceoryx2 loan/publish/release,
триггер TECH_STACK §7) = новая реализация под ЭТИМ ЖЕ Protocol, middleware/executor не трогаются.

**Контракт 1:1 с iceoryx2/DDS loan/publish/release:**
  - ``acquire`` = loan (взять свободный слот у источника);
  - ``commit`` = publish (опубликовать, поставить refcount = число потребителей fan-out);
  - ``release`` = release (потребитель дочитал → декремент; refcount→0 = слот свободен);
  - ``reclaim`` = reclaim займов мёртвого потребителя (kill-9 без release).

**Модель конкурентности (важно):** refcount мутирует ТОЛЬКО процесс-владелец (owner-side) —
кросс-процессного atomic RMW в CPython нет по построению (см. §8 g5-плана, отклонение В2).
`acquire`/`commit` зовёт writer-поток источника; `release`/`reclaim` — тот же owner по IPC-
тикетам/смерти соседа. Безопасность от torn-кадра даёт seqlock (G.3) + post-use re-check (В1),
НЕ этот учёт: любая ошибка учёта здесь безопасна (преждевременное освобождение → writer
перезапишет → generation drift → drop, НЕ порча).
"""

from __future__ import annotations

from typing import Callable, Protocol, TypedDict, runtime_checkable


class LoanTicket(TypedDict):
    """Тикет release от потребителя (pickle-safe dict, Dict at Boundary).

    Потребитель, дочитав view слота, шлёт владельцу пачку тикетов. ``generation`` —
    поколение слота на момент чтения (seqlock); ``-1`` = слот без seqlock (guard-no-op).
    """

    index: int
    generation: int
    reader: str


class PoolStats(TypedDict):
    """Снимок счётчиков пула для наблюдаемости (→ get_stats → heartbeat → state.shm)."""

    slots_released: int
    slots_reclaimed: int
    loan_exhausted: int


# Читатель ТЕКУЩЕГО поколения СВОЕГО слота idx (owner-side seqlock-generation).
# Инжектируется в реализацию → пул остаётся SHM-агностичным (не знает про формат слота).
# Возвращает -1 при недоступности/отсутствии seqlock.
GenerationReader = Callable[[int], int]


@runtime_checkable
class FramePool(Protocol):
    """Пул слотов кольца SHM с владением по цепочке (loan/publish/release/reclaim).

    Реализация — per-owner (у каждой камеры своё независимое кольцо, изоляция по
    построению; общего слота нет). Активен ТОЛЬКО когда включён loan-протокол
    (``FW_SHM_LOAN_PROTOCOL``); при выключенном флаге транспорт не создаёт пул и идёт
    прежним слепым round-robin (откат бит-в-бит).
    """

    @property
    def depth(self) -> int:
        """Глубина кольца (число слотов). Нужна потребителю для порога флаша release."""
        ...

    def acquire(self) -> int | None:
        """Взять СВОБОДНЫЙ слот (refcount==0) от ротационного курсора (справедливость).

        ``None`` → все слоты заняты (потребители отстали больше глубины) → инкремент
        счётчика ``loan_exhausted``; вызывающий делает ГРОМКИЙ drop-на-источнике
        (back-pressure, кадр не уходит — НЕ pickle-fallback). Успех — общий путь, счётчики
        не трогает.
        """
        ...

    def commit(self, idx: int, num_consumers: int) -> None:
        """Опубликовать записанный слот: refcount = число loan-aware потребителей (fan-out).

        copy-out терминалы (GUI, zero_copy off) release НЕ шлют → в ``num_consumers`` их
        НЕ включать (иначе слот завис бы навсегда). Зовётся сразу после успешной записи.
        """
        ...

    def release(self, tickets: list[LoanTicket]) -> int:
        """Owner-side release пачки тикетов: декремент refcount освобождённых слотов.

        Guard'ы (без костылей): refcount уже 0 → пропуск (stale/дубликат); generation
        тикета ≠ текущему поколению слота → release ПРОШЛОГО займа (слот переиспользован)
        → пропуск; reader уже в released-множестве этого займа → дубликат → пропуск.
        refcount→0 → слот назад в free-list. Возвращает число реально освобождённых займов.
        """
        ...

    def reclaim(self, dead_reader: str) -> int:
        """Реклейм ВСЕХ незакрытых займов мёртвого потребителя (kill-9 без release).

        При fan-out мёртвый reader держал все слоты, которые ещё не отпустил → декремент
        за него (тот же учёт, инициатор — владелец по confirmed-death/incarnation).
        Идемпотентно (повторный вызов после реклейма → 0). Возвращает число реклеймленных.
        """
        ...

    def reset(self) -> None:
        """Сброс в «всё свободно» (realloc кольца: старые сегменты unlink'нуты, займы void).

        Старые тикеты прошлого кольца безопасны: сегменты ушли, потребители инвалидируют
        кэш по incarnation, В1 re-check дропнет — generation-guard release тоже отсечёт.
        """
        ...

    def snapshot_stats(self) -> PoolStats:
        """Снимок счётчиков (наблюдаемость). Пул — единственный источник этих чисел."""
        ...


__all__ = ["FramePool", "LoanTicket", "PoolStats", "GenerationReader"]
