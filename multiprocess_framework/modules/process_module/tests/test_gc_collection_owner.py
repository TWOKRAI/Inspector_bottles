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
def _owner_slot_suspended():
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
                leftover.release()
            gc.unfreeze()


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
    }
    assert len(d) == 13
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
    door.collect_on(ex)  # главный поток — владелец
    got: list[str] = []
    frozen_before = gc.get_freeze_count()
    box = _in_daemon(lambda: door.GcDiscipline(log=got.append).freeze_after_startup())
    assert box.get("r") is False, box
    assert got == ["GcDiscipline: freeze_after_startup пропущен — сборкой владеет другой поток"]
    assert gc.get_freeze_count() == frozen_before


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
