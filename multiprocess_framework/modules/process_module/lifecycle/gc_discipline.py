"""GC-дисциплина процесса (Ф7 G.9(a)).

Проблема (перф-ревью 2026-07-12 п.2): CPython запускает сборку мусора «когда захочет» —
по порогам поколений. На hot-path кадров это даёт непредсказуемые паузы = выбросы p99.

Дисциплина (за флагами, дефолт off = штатный GC бит-в-бит):

1. **``gc.freeze()`` после старта воркеров** (``FW_GC_FREEZE``). Все долгоживущие
   startup-объекты (менеджеры, плагины, роутер, кэши) уже созданы → переносим их в
   permanent-поколение: сборщик их больше НЕ сканирует на каждом цикле. Меньше объектов в
   обходе → короче каждая пауза GC. Безопасно и почти без риска — cadence сборки не
   меняется, только объём обхода.

2. **Сборка по расписанию** (``collect_scheduled``, отдельный флаг ``FW_GC_SCHEDULED``) —
   ``gc.disable()`` автоматики + явный ``gc.collect()`` по дедлайну в паузах воркера, чтобы
   пауза случалась в ИЗВЕСТНЫЙ момент (idle), а не посреди кадра. **Measurement-gated:**
   отключать автоматику рискованно (рост RSS при протечке ссылок), поэтому включаем только
   ПОСЛЕ замера harness'ом G.9(b), доказавшего снижение p99-выбросов. По умолчанию — off.

Pydantic остаётся на конфигах/границах (правила 1/5); per-frame путь уже без Pydantic-
пересборки (G.5 ``FW_DATA_PLANE_DICTS``) — эта дисциплина ортогональна и про сам GC.

3. **Сборкой владеет поток-исполнитель** (T1, ADR «Сборкой владеет поток-исполнитель»).
   ``collect_on(executor)`` занимает **слот процесса** (один: ``gc`` глобален): автосборка
   выключается, сборку зовёт тик исполнителя на ЕГО потоке (в GUI — ``QTimer`` главного
   потока, адаптер ``frontend_module/core/qt_gc_policy.py``). Пока слот занят,
   ``GcDiscipline.collect_scheduled`` уступает владельцу, а ``freeze_after_startup`` с чужого
   потока отказывается. Слот пуст → ``GcDiscipline`` бит-в-бит как раньше.

Stability: lite.

Потоки: кроме ``stats()``, ``collection_owner()`` и ``paused_gc()`` — только поток, позвавший
``collect_on``. Под локом модуля — только чтение/запись ссылки слота (никаких аллокаций: при
живой автосборке аллокация под локом запускает сборку → финализатор входит в лок →
взаимоблокировка; прецедент ``qt_lifetime.py``). Хук ``gc.callbacks`` — только ``+= 1``.
"""

from __future__ import annotations

import gc
import logging
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterator, Optional, Protocol


class GcDiscipline:
    """GC-дисциплина одного процесса. Держит состояние (заморожен ли, дедлайн сборки)."""

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log or (lambda _m: None)
        self._frozen = False
        self._scheduled = False
        self._next_collect_at: float = 0.0

    @staticmethod
    def _flag(name: str) -> bool:
        from ...config_module.feature_flags import is_enabled

        return is_enabled(name)

    def freeze_after_startup(self) -> bool:
        """``gc.freeze()`` после старта воркеров (``FW_GC_FREEZE``). Идемпотентно.

        Сначала ``gc.collect()`` — собрать мусор старта, чтобы НЕ заморозить его в
        permanent (иначе он никогда не соберётся). Затем ``gc.freeze()`` — живые объекты
        в permanent-поколение. Возвращает True, если заморозка применена.

        Слот владельца занят и зовут НЕ с его потока → ``False`` + строка лога: заморозкой
        и сборкой распоряжается владелец (T1). Слот пуст или поток владельца — как было.
        """
        if self._frozen:
            return False
        owner = _slot  # атомарное чтение без лока
        if owner is not None and owner.thread_ident != threading.get_ident():
            self._log("GcDiscipline: freeze_after_startup пропущен — сборкой владеет другой поток")
            return False
        if not self._flag("FW_GC_FREEZE"):
            # Ф7 ревью фазы G: FW_GC_SCHEDULED без FW_GC_FREEZE — расписание НЕ
            # применяется (сборка по расписанию имеет смысл только после заморозки
            # стартовых объектов). Раньше это был ТИХИЙ no-op — оператор включал
            # расписание и не получал ничего без единого лога («терять можно,
            # молчать нельзя», ADR-SRM-012).
            if self._flag("FW_GC_SCHEDULED"):
                self._log(
                    "GcDiscipline: FW_GC_SCHEDULED запрошен БЕЗ FW_GC_FREEZE — "
                    "расписание НЕ применено (авто-GC остаётся); включите оба флага"
                )
            return False
        gc.collect()
        gc.freeze()
        self._frozen = True
        permanent = gc.get_freeze_count()
        self._log(f"GcDiscipline: gc.freeze применён после старта (permanent-объектов={permanent})")
        # FW_GC_SCHEDULED: перевести сборку в ручной режим (сборка только в паузах воркера).
        if self._flag("FW_GC_SCHEDULED"):
            gc.disable()
            self._scheduled = True
            self._log("GcDiscipline: авто-GC отключён — сборка по расписанию в паузах (FW_GC_SCHEDULED)")
        return True

    def collect_scheduled(self, now: float, *, interval_s: float = 2.0) -> bool:
        """Явная сборка по дедлайну — зовётся из ПАУЗЫ воркера (idle), не на hot-path.

        No-op, если расписание не включено (``FW_GC_SCHEDULED`` off) — тогда работает
        штатный авто-GC. При включённом: собирает не чаще, чем раз в ``interval_s``, и
        только когда воркер в паузе (вызывающий гарантирует). ``now`` — монотонное время
        (инжектируется вызывающим; тестируемо). Возвращает True, если собрал.

        Слот владельца занят → ``False`` первой проверкой, без исключения (heartbeat
        глотает исключения — бросок тут был бы тихим): сборкой владеет исполнитель.
        """
        if _slot is not None:
            return False
        if not self._scheduled:
            return False
        if now < self._next_collect_at:
            return False
        self._next_collect_at = now + max(0.1, interval_s)
        gc.collect()
        return True


# ── Сборкой владеет поток-исполнитель (T1) ───────────────────────────────────────────────────

_THREAD_ERROR = "GcCollectionOwner: вызов не с потока-владельца сборки"
_OTHER_OWNER_ERROR = "collect_on: сборкой уже владеет другой исполнитель — сначала release()"
_LEFTOVER_ERROR = "suspend_collection_owner: блок оставил своего владельца"
_BOUNDS_ERROR = "collect_on: interval_s и freeze_after_s — конечные, interval_s > 0"
_PARAM_NAMES = ("interval_s", "freeze", "freeze_after_s", "observe")  # порядок сигнатуры
_REPORT_EVERY_S = 60.0

# Слот процесса. Лок — ТОЛЬКО чтение/запись этой ссылки (без аллокаций под ним).
_SLOT_LOCK = threading.Lock()
_slot: Optional["GcCollectionOwner"] = None


class CollectionExecutor(Protocol):
    """Где и когда зовётся тик сборки. Сам исполнитель не собирает.

    Stability: lite.

    Pre: ``start`` зовётся один раз из ``collect_on`` на потоке будущего владельца.
    Post: ``tick`` вызывается на потоке владельца примерно раз в ``interval_s``, пока не
    позван ``stop``; после ``stop`` — больше не вызывается.
    """

    def start(self, tick: Callable[[], int], *, interval_s: float) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class GcOwnerStats:
    """Снимок счётчиков владельца сборки. Поля между собой не согласованы (без лока).

    Stability: lite.

    Post: ``to_dict()`` — ровно 13 ключей, значения только ``bool/int/float/str``.
    """

    active: bool
    executor: str
    owner_thread: str
    interval_s: float
    observe: bool
    frozen: bool
    collections: int
    collected_objects: int
    enabled_violations: int
    foreign_collections: int
    last_pause_ms: float
    max_pause_ms: float
    total_pause_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GcCollectionOwner:
    """Владелец сборки процесса: автосборка выключена, сборка — по тику исполнителя.

    Stability: lite.

    Создаётся только ``collect_on``. Все методы, кроме ``stats()``, — только с потока
    ``thread_ident`` (иначе ``RuntimeError``).

    Pre: владелец в слоте (иначе ``tick``/``collect``/``enforce`` — пустые, возвращают 0/False).
    Post ``tick()``: автосборка выключена; собрано старшее поколение, чей счётчик достиг
    порога (как CPython, но на этом потоке), либо ничего (0).
    Post ``release()``: исполнитель остановлен, хук снят, своя заморозка снята,
    ``gc.isenabled()`` ровно как до ``collect_on``.
    """

    def __init__(
        self,
        executor: CollectionExecutor,
        *,
        interval_s: float,
        freeze: bool,
        freeze_after_s: float,
        requested: tuple,
        log: Callable[[str], None],
    ) -> None:
        self.thread_ident: int = threading.get_ident()
        self._thread_name = threading.current_thread().name
        self._executor = executor
        self._interval_s = interval_s
        self._freeze = freeze
        self._freeze_after_s = freeze_after_s
        self._requested = requested
        self._log = log
        self._prior = True
        self._released = False
        self._suspended = False
        self._froze = False
        self._freeze_deadline = 0.0
        self._observe = False
        self._report_at = 0.0
        self._hook = self._on_gc_phase  # одна ссылка — для append/remove в gc.callbacks
        # Счётчики. Выкл. наблюдаемость — растут только первые три (int).
        self._collections = 0
        self._collected_objects = 0
        self._enabled_violations = 0
        self._foreign_collections = 0
        self._last_pause_ms = 0.0
        self._max_pause_ms = 0.0
        self._total_pause_ms = 0.0

    # ── публичное ──

    def tick(self) -> int:
        """Тик исполнителя: ``enforce()``, затем сборка поколения по порогам. Вернёт собранное."""
        self._check_thread()
        if _slot is not self:
            return 0  # приостановлен (suspend) или освобождён
        self.enforce()
        if self._freeze_due():
            return self._freeze_now()
        counts = gc.get_count()
        thresholds = gc.get_threshold()
        for gen in range(min(len(counts), len(thresholds)) - 1, -1, -1):
            limit = thresholds[gen]
            if limit > 0 and counts[gen] >= limit:
                return self._collect(gen)
        return 0

    def collect(self, *, full: bool = False) -> int:
        """Явная сборка на потоке владельца: ``full=True`` — ``gc.collect()``, иначе поколение 0.

        Подошёл срок заморозки → полная сборка + ``gc.freeze()``.
        """
        self._check_thread()
        if _slot is not self:
            return 0
        if self._freeze_due():
            return self._freeze_now()
        return self._collect(None if full else 0)

    def enforce(self) -> bool:
        """Автосборку включили извне → выключить, посчитать, записать в лог. True — лечили."""
        self._check_thread()
        if _slot is not self or not gc.isenabled():
            return False
        self._enabled_violations += 1
        gc.disable()
        self._log(f"gc-policy: автосборку включили извне — выключена (нарушений={self._enabled_violations})")
        return True

    def rearm_freeze(self) -> None:
        """Морозил владелец → ``gc.unfreeze()`` (глобально); отсчёт ``freeze_after_s`` заново."""
        self._check_thread()
        self._rearm()

    def set_observe(self, on: bool) -> None:
        """Наблюдаемость: вкл. — хук ``gc.callbacks`` и замер пауз; выкл. — ноль цены."""
        self._check_thread()
        if on:
            self._hook_on()
        else:
            self._hook_off()

    def stats(self) -> GcOwnerStats:
        """Снимок счётчиков. Любой поток, без лока."""
        return GcOwnerStats(
            active=_slot is self,
            executor=type(self._executor).__name__,
            owner_thread=self._thread_name,
            interval_s=float(self._interval_s),
            observe=bool(self._observe),
            frozen=bool(self._froze),
            collections=int(self._collections),
            collected_objects=int(self._collected_objects),
            enabled_violations=int(self._enabled_violations),
            foreign_collections=int(self._foreign_collections),
            last_pause_ms=float(self._last_pause_ms),
            max_pause_ms=float(self._max_pause_ms),
            total_pause_ms=float(self._total_pause_ms),
        )

    def release(self) -> None:
        """Освободить слот: остановить исполнителя, снять хук и свою заморозку, вернуть prior.

        Не в слоте (уже освобождён) → no-op.
        """
        self._check_thread()
        global _slot
        with _SLOT_LOCK:
            mine = _slot is self
            if mine:
                _slot = None
        if mine:
            self._teardown(restore_gc=True)
        elif self._suspended and not self._released:
            # Освобождён изнутри suspend-блока: gc принадлежит блоку — его не трогаем.
            self._teardown(restore_gc=False)

    # ── внутреннее ──

    def _check_thread(self) -> None:
        if threading.get_ident() != self.thread_ident:
            raise RuntimeError(_THREAD_ERROR)

    def _activate(self) -> None:
        """Вызывается ``collect_on`` ПОСЛЕ записи в слот, вне лока."""
        self._prior = gc.isenabled()
        gc.disable()
        if self._freeze:
            self._freeze_deadline = time.monotonic() + self._freeze_after_s
        try:
            self._executor.start(self.tick, interval_s=self._interval_s)
        except BaseException:
            global _slot
            with _SLOT_LOCK:
                if _slot is self:
                    _slot = None
            self._released = True
            if self._prior:
                gc.enable()
            raise

    def _repeat(self, executor: CollectionExecutor, requested: tuple) -> GcCollectionOwner:
        if executor is not self._executor:
            raise RuntimeError(_OTHER_OWNER_ERROR)
        self._check_thread()
        changed = [name for name, old, new in zip(_PARAM_NAMES, self._requested, requested) if old != new]
        if changed:
            self._log(f"collect_on: повторный вызов с другими параметрами — оставлены прежние ({', '.join(changed)})")
        return self

    def _teardown(self, *, restore_gc: bool) -> None:
        self._released = True
        self._suspended = False
        try:
            self._executor.stop()
        finally:
            self._hook_off()
            if self._froze:
                gc.unfreeze()
                self._froze = False
            if restore_gc:
                if self._prior:
                    gc.enable()
                else:
                    gc.disable()

    def _rearm(self) -> None:
        if self._froze:
            gc.unfreeze()
            self._froze = False
        if self._freeze:
            self._freeze_deadline = time.monotonic() + self._freeze_after_s

    def _freeze_due(self) -> bool:
        return self._freeze and not self._froze and time.monotonic() >= self._freeze_deadline

    def _freeze_now(self) -> int:
        collected = self._collect(None)
        gc.freeze()
        self._froze = True
        self._log(f"gc-policy: gc.freeze применён (permanent-объектов={gc.get_freeze_count()})")
        return collected

    def _collect(self, generation: Optional[int]) -> int:
        if self._observe:
            started = time.perf_counter()
            collected = gc.collect() if generation is None else gc.collect(generation)
            pause_ms = (time.perf_counter() - started) * 1000.0
            self._last_pause_ms = pause_ms
            if pause_ms > self._max_pause_ms:
                self._max_pause_ms = pause_ms
            self._total_pause_ms += pause_ms
        else:
            collected = gc.collect() if generation is None else gc.collect(generation)
        self._collections += 1
        self._collected_objects += collected
        if self._observe:
            self._maybe_report()
        return collected

    def _maybe_report(self) -> None:
        now = time.monotonic()
        if now < self._report_at:
            return
        self._report_at = now + _REPORT_EVERY_S
        self._log(
            f"gc-policy: collections={self._collections} max_pause_ms={self._max_pause_ms:.3f} "
            f"violations={self._enabled_violations} foreign={self._foreign_collections}"
        )

    def _hook_on(self) -> None:
        if self._observe:
            return
        self._report_at = time.monotonic() + _REPORT_EVERY_S
        gc.callbacks.append(self._hook)
        self._observe = True

    def _hook_off(self) -> None:
        if not self._observe:
            return
        self._observe = False
        try:
            gc.callbacks.remove(self._hook)
        except ValueError:
            pass  # хук сняли извне — снимать нечего

    def _on_gc_phase(self, phase: str, _info: dict) -> None:
        # Хук gc.callbacks: без лога, лока, Qt и контейнеров — только += 1.
        if phase == "start" and not self._suspended and threading.get_ident() != self.thread_ident:
            self._foreign_collections += 1


def _finite(value: float) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def collect_on(
    executor: CollectionExecutor,
    *,
    interval_s: float = 1.0,
    freeze: Optional[bool] = None,
    freeze_after_s: float = 5.0,
    observe: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> GcCollectionOwner:
    """Отдать сборку мусора процесса исполнителю (его поток — владелец).

    Stability: lite.

    Pre: ``interval_s > 0``, ``freeze_after_s >= 0``, оба конечные (иначе ``ValueError``).
    Post (слот был пуст): ``gc.isenabled() is False``; ``executor.start(owner.tick, ...)``
    позван; ``observe`` → хук в ``gc.callbacks``; ``freeze=None`` → флаг ``FW_GC_FREEZE``.
    Post (тот же исполнитель): тот же объект, параметры прежние; отличия — одна строка лога.
    Post (другой исполнитель): ``RuntimeError``, слот не тронут.
    """
    if not (_finite(interval_s) and _finite(freeze_after_s) and interval_s > 0 and freeze_after_s >= 0):
        raise ValueError(_BOUNDS_ERROR)
    global _slot
    requested = (float(interval_s), freeze, float(freeze_after_s), bool(observe))
    current = _slot
    if current is not None:
        return current._repeat(executor, requested)
    resolved_freeze = GcDiscipline._flag("FW_GC_FREEZE") if freeze is None else bool(freeze)
    # Владелец создаётся ДО лока: под локом — только ссылка слота.
    owner = GcCollectionOwner(
        executor,
        interval_s=float(interval_s),
        freeze=resolved_freeze,
        freeze_after_s=float(freeze_after_s),
        requested=requested,
        log=log or logging.getLogger(__name__).info,
    )
    with _SLOT_LOCK:
        current = _slot
        if current is None:
            _slot = owner
    if current is not None:
        return current._repeat(executor, requested)
    owner._activate()
    if observe:
        owner._hook_on()
    return owner


def collection_owner() -> Optional[GcCollectionOwner]:
    """Текущий владелец слота или ``None``. Любой поток, атомарное чтение без лока.

    Stability: lite.
    """
    return _slot


@contextmanager
def paused_gc() -> Iterator[None]:
    """Автосборка выключена на блок; на выходе — ровно прежнее состояние. Любой поток.

    Stability: lite.

    Pre: нет. Post: ``gc.isenabled()`` после блока равен значению до входа.
    Риск вне политики: вложенные блоки на ДВУХ потоках (A вошёл при вкл., B — при выкл.;
    A вышел первым и включил, B вышел и выключил) оставят автосборку выключенной.
    """
    prior = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if prior:
            gc.enable()
        else:
            gc.disable()


@contextmanager
def suspend_collection_owner() -> Iterator[None]:
    """Освободить слот на блок (только тесты механизма); на выходе вернуть владельца.

    Stability: lite.

    Pre: слот занят → зовут с потока владельца (иначе ``RuntimeError``).
    Post на входе: слот пуст; тик прежнего владельца — 0; ``gc.isenabled()`` = его prior.
    Слот был пуст → ``gc`` не трогается.
    Post на выходе: блок оставил своего владельца → тот освобождается, затем
    ``RuntimeError``; прежний владелец снова в слоте, ``gc.disable()``, морозил →
    ``rearm_freeze()``.
    """
    global _slot
    current = _slot
    if current is not None:
        current._check_thread()
    with _SLOT_LOCK:
        previous = _slot
        _slot = None
    if previous is not None:
        previous._suspended = True
        if previous._prior:
            gc.enable()
        else:
            gc.disable()
    try:
        yield
    finally:
        returning = previous is not None and not previous._released
        with _SLOT_LOCK:
            leftover = _slot
            _slot = previous if returning else None
        if leftover is not None:
            leftover._teardown(restore_gc=True)
        if returning:
            previous._suspended = False
            gc.disable()
            if previous._froze:
                previous._rearm()
        if leftover is not None:
            raise RuntimeError(_LEFTOVER_ERROR)


__all__ = [
    "CollectionExecutor",
    "GcCollectionOwner",
    "GcDiscipline",
    "GcOwnerStats",
    "collect_on",
    "collection_owner",
    "paused_gc",
    "suspend_collection_owner",
]
