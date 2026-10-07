# -*- coding: utf-8 -*-
"""T1 / A1: приёмка механизма «сборкой владеет поток-исполнитель» (без Qt).

Источник — plans/2026-10-03_lifecycle-owner-scope/task-T1.md («Контракт реализации», «A1»).
Тест слепой: написан до реализации, ожидаемые значения — литералы спека.

Дверь (``gc_discipline``) импортируется лениво: пока имён нет, КАЖДЫЙ тест падает
``ImportError`` на фикстуре, а не весь файл разом на сборе.

Фикстуры файла:

* ``_owner_slot_suspended`` — слот владельца на время теста пуст (``suspend_collection_owner``);
  под сессионной политикой (Brief B) без этого ``collect_on`` в тесте упёрся бы в чужого владельца.
* ``_gc_state_and_flags`` — тест стартует с ВЫКЛЮЧЕННОЙ автосборкой и вернёт то, с чем начал
  (через ``paused_gc``), снимает забытого владельца и заморозку, чистит флаги ``FW_GC_*``.

``gc.enable()`` в файле ровно три: строки 1, 4, 8 — их разрешает allowlist стража
(``tests/test_gc_policy_guard.py``). Не добавлять четвёртый.
"""

from __future__ import annotations

import functools
import gc
import importlib
import threading

import pytest

_DOOR = "multiprocess_framework.modules.process_module.lifecycle.gc_discipline"


@functools.cache
def _door():
    """Модуль ядра; ``ImportError`` — красный до реализации."""
    return importlib.import_module(_DOOR)


class FakeExecutor:
    """Исполнитель-запись: тик сам не собирает, только хранит то, что ему передали."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.tick = None
        self.interval_s = None

    def start(self, tick, *, interval_s) -> None:
        self.events.append("start")
        self.tick = tick
        self.interval_s = interval_s

    def stop(self) -> None:
        self.events.append("stop")


def _in_daemon(fn):
    """Вызвать ``fn`` на daemon-потоке; вернуть ``{"r": результат}`` или ``{"e": исключение}``."""
    box: dict = {}

    def body() -> None:
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение и есть предмет проверки
            box["e"] = exc

    th = threading.Thread(target=body, daemon=True)
    th.start()
    th.join(5)
    assert not th.is_alive(), "вызов на daemon-потоке завис дольше 5 с"
    return box


@pytest.fixture(autouse=True)
def _owner_slot_suspended(gc_freeze_restored):
    # Заморозку возвращает gc_freeze_restored СНАРУЖИ: выход suspend сам зовёт gc.unfreeze().
    with _door().suspend_collection_owner():
        yield


@pytest.fixture(autouse=True)
def _gc_state_and_flags(monkeypatch, _owner_slot_suspended):
    monkeypatch.delenv("FW_GC_FREEZE", raising=False)
    monkeypatch.delenv("FW_GC_SCHEDULED", raising=False)
    door = _door()
    with door.paused_gc():  # автосборка выкл. на тест; на выходе — состояние, с которым начали
        try:
            yield
        finally:
            leftover = door.collection_owner()
            if leftover is not None:
                leftover.release()  # морозивший владелец сам снимает заморозку
            # Голый gc.unfreeze() здесь размораживал сессионную кучу pytest; заморозку
            # к исходной возвращает gc_freeze_restored после выхода suspend.


@pytest.fixture
def ex() -> FakeExecutor:
    return FakeExecutor()


# 1 ---------------------------------------------------------------------------------------------


def test_collect_on_disables_and_release_restores_prior(ex):
    door = _door()
    gc.enable()  # prior сессии — не опора: задаём явно
    owner = door.collect_on(ex)
    assert gc.isenabled() is False
    assert door.collection_owner() is owner
    assert ex.events == ["start"]
    assert ex.interval_s == 1.0
    assert ex.tick == owner.tick
    owner.release()
    assert gc.isenabled() is True
    assert door.collection_owner() is None
    assert ex.events == ["start", "stop"]

    gc.disable()
    ex2 = FakeExecutor()
    owner2 = door.collect_on(ex2)
    assert gc.isenabled() is False
    owner2.release()
    assert gc.isenabled() is False  # ровно prior: был выключен — остался выключен


# 2 ---------------------------------------------------------------------------------------------


def test_same_executor_idempotent_other_rejected(ex):
    door = _door()
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)

    owner = door.collect_on(ex, log=log)
    assert door.collect_on(ex, log=log) is owner
    assert logs == []  # отличий нет — строки нет
    assert door.collect_on(ex, interval_s=2.0, log=log) is owner
    assert logs == ["collect_on: повторный вызов с другими параметрами — оставлены прежние (interval_s)"]
    assert ex.events == ["start"]  # не перезапущен
    assert ex.interval_s == 1.0  # параметры прежние
    assert owner.stats().interval_s == 1.0

    other = FakeExecutor()
    with pytest.raises(RuntimeError) as info:
        door.collect_on(other, log=log)
    assert "уже владеет" in str(info.value)
    assert door.collection_owner() is owner
    assert other.events == []
    assert logs == ["collect_on: повторный вызов с другими параметрами — оставлены прежние (interval_s)"]


# 3 ---------------------------------------------------------------------------------------------


def test_foreign_thread_calls_raise(ex):
    door = _door()
    owner = door.collect_on(ex)
    assert owner.thread_ident == threading.get_ident()
    for name, fn in (("collect", owner.collect), ("release", owner.release)):
        box = _in_daemon(fn)
        exc = box.get("e")
        assert isinstance(exc, RuntimeError), f"{name}() с чужого потока не бросил RuntimeError: {box!r}"
        assert "потока-владельца" in str(exc)
    # отказ не освободил слот и не остановил исполнителя
    assert door.collection_owner() is owner
    assert ex.events == ["start"]


# 4 ---------------------------------------------------------------------------------------------


def test_enforce_heals_and_counts_once(ex):
    door = _door()
    logs: list[str] = []
    owner = door.collect_on(ex, log=logs.append)
    gc.enable()  # «извне» включили автосборку
    owner.tick()
    assert gc.isenabled() is False
    assert owner.stats().enabled_violations == 1
    owner.tick()
    assert owner.stats().enabled_violations == 1
    assert owner.enforce() is False  # включённой автосборки нет — лечить нечего
    assert owner.stats().enabled_violations == 1
    assert any("автосборку включили извне — выключена (нарушений=1)" in m for m in logs), logs


# 5 ---------------------------------------------------------------------------------------------


def test_tick_generation_aware(ex):
    door = _door()
    old = gc.get_threshold()
    try:
        owner = door.collect_on(ex)
        gc.set_threshold(10**9, 10**9, 10**9)  # все три: ни одно поколение порога не достигнет
        assert owner.tick() == 0
        assert owner.stats().collections == 0
        gc.set_threshold(1)  # порог gen0 — 1; gen1/gen2 остаются 10**9
        for _ in range(100):
            cycle: list = []
            cycle.append(cycle)  # цикл: освободит только сборщик
        del cycle
        collected = owner.tick()
        assert owner.stats().collections == 1
        assert collected >= 100
    finally:
        gc.set_threshold(*old)


# 6 ---------------------------------------------------------------------------------------------


def test_scheduled_collect_yields_to_owner(ex, monkeypatch):
    door = _door()
    monkeypatch.setenv("FW_GC_FREEZE", "1")
    monkeypatch.setenv("FW_GC_SCHEDULED", "1")
    try:
        disc = door.GcDiscipline()
        assert disc.freeze_after_startup() is True  # до collect_on — как в проде
        owner = door.collect_on(ex)
        assert disc.collect_scheduled(100.0) is False  # сборкой владеет исполнитель
        owner.release()
        assert disc.collect_scheduled(100.0) is True
    finally:
        gc.unfreeze()


# 7 ---------------------------------------------------------------------------------------------


def test_observe_off_zero_cost_on_counts_foreign(ex):
    door = _door()
    before = len(gc.callbacks)
    owner = door.collect_on(ex)  # observe=False
    assert len(gc.callbacks) == before
    owner.collect(full=True)
    off = owner.stats()
    assert off.collections == 1
    assert off.last_pause_ms == 0.0
    assert off.max_pause_ms == 0.0
    assert off.total_pause_ms == 0.0

    owner.set_observe(True)
    assert len(gc.callbacks) == before + 1
    assert owner.stats().observe is True
    owner.collect(full=True)  # сборка владельца — не чужая
    on = owner.stats()
    assert on.foreign_collections == 0
    assert on.max_pause_ms > 0.0
    box = _in_daemon(gc.collect)
    assert "e" not in box, box
    assert owner.stats().foreign_collections == 1

    owner.release()
    assert len(gc.callbacks) == before  # release снимает хук


# 8 ---------------------------------------------------------------------------------------------


def test_paused_gc_restores_exact_state():
    paused_gc = _door().paused_gc
    began = gc.isenabled()
    with paused_gc():  # внешний: вернёт состояние, с которого начат тест
        with paused_gc():  # prior выключен
            gc.enable()  # внутри блока автосборку включили
            assert gc.isenabled() is True
            with paused_gc():  # prior включён
                assert gc.isenabled() is False
            assert gc.isenabled() is True
        assert gc.isenabled() is False
    assert gc.isenabled() is began


# 9 ---------------------------------------------------------------------------------------------


def test_freeze_deadline_and_rearm(ex):
    door = _door()
    gc.unfreeze()
    assert gc.get_freeze_count() == 0
    owner = door.collect_on(ex, freeze=True, freeze_after_s=0)
    owner.tick()
    assert gc.get_freeze_count() > 0
    owner.rearm_freeze()
    assert gc.get_freeze_count() == 0
    owner.tick()
    assert gc.get_freeze_count() > 0
    owner.release()
    assert gc.get_freeze_count() == 0


# 10 --------------------------------------------------------------------------------------------


def test_stats_dict_primitives(ex):
    door = _door()
    owner = door.collect_on(ex)
    d = owner.stats().to_dict()
    assert set(d) == {
        "active",
        "executor",
        "owner_thread",
        "interval_s",
        "observe",
        "frozen",
        "collections",
        "collected_objects",
        "enabled_violations",
        "foreign_collections",
        "last_pause_ms",
        "max_pause_ms",
        "total_pause_ms",
        "full_collections",
        "max_pause_ms_gen0",
        "max_pause_ms_gen1",
        "max_pause_ms_full",
    }
    assert len(d) == 17
    for key, value in d.items():
        assert type(value) in (bool, int, float, str), f"{key}: {type(value).__name__}"
    assert d["active"] is True
    assert d["interval_s"] == 1.0
    assert d["observe"] is False


# 11 --------------------------------------------------------------------------------------------


def test_suspend_requires_empty_slot(ex):
    door = _door()
    with pytest.raises(RuntimeError) as info:
        with door.suspend_collection_owner():
            door.collect_on(ex)  # без release
    assert "оставил" in str(info.value)
    assert door.collection_owner() is None  # блок освобождён принудительно
    assert ex.events == ["start", "stop"]


# 12 --------------------------------------------------------------------------------------------


def test_freeze_after_startup_foreign_thread_refused(ex, monkeypatch):
    door = _door()
    monkeypatch.setenv("FW_GC_FREEZE", "1")
    # чистая постоянная генерация: замороженные объекты, освобождённые по refcount, покидают её,
    # так что равенство «до/после» дрейфует под сессионной заморозкой (выход suspend — rearm)
    gc.unfreeze()
    assert gc.get_freeze_count() == 0
    door.collect_on(ex)  # главный поток — владелец
    got: list[str] = []
    box = _in_daemon(lambda: door.GcDiscipline(log=got.append).freeze_after_startup())
    assert box.get("r") is False, box
    assert got == ["GcDiscipline: freeze_after_startup пропущен — сборкой владеет другой поток"]
    assert gc.get_freeze_count() == 0  # настоящая заморозка дала бы > 0


# 13 --------------------------------------------------------------------------------------------


def test_suspend_exit_rearms_freeze(ex):
    door = _door()
    gc.unfreeze()
    owner = door.collect_on(ex, freeze=True, freeze_after_s=0)
    owner.tick()
    assert gc.get_freeze_count() > 0
    with door.suspend_collection_owner():
        assert door.collection_owner() is None
        assert owner.tick() == 0  # тик старого владельца на время блока — пустой
        gc.unfreeze()
    assert door.collection_owner() is owner  # владелец вернулся
    owner.collect()
    assert gc.get_freeze_count() > 0


# ── Ред. 4 (ревью р1 №3, CTO D1–D3): авторские тесты строк контракта ─────────────────────────


def test_bounds_rejected(ex):
    door = _door()
    for kwargs in (
        {"interval_s": 0},
        {"interval_s": float("inf")},
        {"interval_s": float("nan")},
        {"freeze_after_s": -1},
        {"full_interval_s": -1},
        {"full_interval_s": float("inf")},
    ):
        with pytest.raises(ValueError) as info:
            door.collect_on(ex, **kwargs)
        assert "конечные" in str(info.value), kwargs
    assert door.collection_owner() is None  # отказ границ слот не занял
    assert ex.events == []


def test_freeze_none_reads_flag(ex, monkeypatch):
    door = _door()
    gc.unfreeze()
    monkeypatch.setenv("FW_GC_FREEZE", "1")
    owner = door.collect_on(ex, freeze_after_s=0)  # freeze=None → флаг
    owner.collect()
    assert gc.get_freeze_count() > 0
    owner.release()
    assert gc.get_freeze_count() == 0

    monkeypatch.delenv("FW_GC_FREEZE")
    ex2 = FakeExecutor()
    owner2 = door.collect_on(ex2, freeze_after_s=0)
    owner2.collect()
    assert gc.get_freeze_count() == 0  # флага нет — заморозки нет
    owner2.release()


def _gen_collections() -> tuple[int, int]:
    stats = gc.get_stats()
    return stats[1]["collections"], stats[2]["collections"]


def _ticks_with_garbage(owner, n: int) -> None:
    for _ in range(n):
        for _ in range(200):  # с запасом: освобождения чужих объектов уменьшают счётчик gen0
            cycle: list = []
            cycle.append(cycle)  # цикл: счётчик gen0 растёт, освободит только сборщик
        del cycle
        owner.tick()


def test_gen2_not_more_often_than_full_interval(ex):
    door = _door()
    old = gc.get_threshold()
    try:
        owner = door.collect_on(ex, full_interval_s=3600)
        owner.collect(full=True)  # счётчики поколений — с нуля
        gc.set_threshold(1, 1, 1)
        gen1_before, gen2_before = _gen_collections()
        _ticks_with_garbage(owner, 10)  # 10 тиков: без ограничения gen2 случился бы на 7-м
        gen1_after, gen2_after = _gen_collections()
        assert gen2_after == gen2_before  # полной сборки тиком не было — рано
        assert gen1_after > gen1_before  # вместо неё — gen1
        owner.release()

        ex2 = FakeExecutor()
        owner2 = door.collect_on(ex2, full_interval_s=0)  # 0 — без ограничения
        gc.set_threshold(*old)
        owner2.collect(full=True)
        gc.set_threshold(1, 1, 1)
        _, gen2_before = _gen_collections()
        _ticks_with_garbage(owner2, 10)
        _, gen2_after = _gen_collections()
        assert gen2_after > gen2_before
        assert owner2.stats().full_collections >= 2  # collect(full=True) + gen2 тиком
    finally:
        gc.set_threshold(*old)


def test_tick_enters_only_above_gen0_threshold_strict(ex):
    door = _door()
    old = gc.get_threshold()
    try:
        owner = door.collect_on(ex)
        owner.collect(full=True)
        owner.collect()
        owner.collect()  # две сборки gen0 → счётчик gen1 = 2
        gc.set_threshold(10**6, 1, 1)  # gen1 «готов», но вход — только по gen0 выше порога
        assert owner.tick() == 0
        assert owner.stats().collections == 3

        gc.set_threshold(1, 2, 10**9)  # gen1: 2 > 2 — нет (строго, как CPython) → gen0
        gen1_before, _ = _gen_collections()
        _ticks_with_garbage(owner, 1)
        gen1_after, _ = _gen_collections()
        assert owner.stats().collections == 4
        assert gen1_after == gen1_before
    finally:
        gc.set_threshold(*old)


def test_collect_full_refreeze(ex):
    door = _door()
    gc.unfreeze()
    owner = door.collect_on(ex, freeze=False)
    owner.collect(full=True, refreeze=True)
    assert gc.get_freeze_count() > 0
    assert owner.stats().frozen is True
    assert owner.stats().full_collections == 1
    owner.release()
    assert gc.get_freeze_count() == 0  # release снимает и заморозку границы


def test_gen2_limited_falls_back_like_cpython(ex):
    door = _door()
    old = gc.get_threshold()
    try:
        owner = door.collect_on(ex, full_interval_s=3600)
        owner.collect(full=True)
        gc.collect(1)
        gc.collect(1)  # счётчик gen2 = 2: gen2 «готов», но ограничен по времени
        gc.set_threshold(1, 10**9, 1)  # gen1 порога не перешёл → как continue CPython: gen0
        gen1_before, gen2_before = _gen_collections()
        _ticks_with_garbage(owner, 1)
        gen1_after, gen2_after = _gen_collections()
        assert (gen1_after, gen2_after) == (gen1_before, gen2_before)
        assert owner.stats().collections == 2  # collect(full=True) + тик gen0

        gc.set_threshold(1, 0, 1)  # gen1 перешёл порог (1 > 0) → gen1
        _ticks_with_garbage(owner, 1)
        gen1_last, gen2_last = _gen_collections()
        assert gen1_last == gen1_after + 1
        assert gen2_last == gen2_after
    finally:
        gc.set_threshold(*old)
