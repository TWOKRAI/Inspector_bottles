"""Тесты автора ``subscribers.py`` (Task 0.3, Step 4): опасности устройства.

Приёмка по критериям — ``test_subscribers_acceptance.py`` (слепой тестер). Здесь:

- ``add`` против ``owner.close()``: владелец закрылся между ``own`` и вставкой — в
  хранилище не остаётся снятой подписки (детерминированно и гонкой × 200);
- ``_Release`` из gc-финализатора на потоке, который держит лок издателя, —
  без дедлока (``RLock``) и без потери соседних подписок;
- рассылка из нескольких потоков при снятии подписок — счётчики сходятся.

Белый ящик (``pub._lock``, ``pub._store``) — только там, где опасность не видна снаружи.
Каждый вызов, который может зависнуть, идёт в daemon-потоке с ``join(timeout)``.
"""

from __future__ import annotations

import gc
import sys
import threading

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from multiprocess_framework.modules.base_manager.interfaces import ScopeClosedError
from multiprocess_framework.modules.event_module import Subscribers


def _bounded(fn, timeout: float = 10.0):
    box: dict = {}

    def run() -> None:
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["e"] = exc

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    assert not th.is_alive(), f"завис дольше {timeout} с"
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _noop(*args, **kwargs) -> None:
    pass


class _ClosesAfterOwn:
    """Владелец, который закрывается сразу после ``own`` — окно «между own и вставкой»."""

    def __init__(self, scope) -> None:
        self._scope = scope
        self.path = scope.path
        self.closed = False

    def own(self, res, *, name, kind="resource"):
        handle = self._scope.own(res, name=name, kind=kind)
        self._scope.close()
        self.closed = True
        return handle

    def note_emits_after_close(self, n: int) -> None:
        self._scope.note_emits_after_close(n)


def test_owner_closed_between_own_and_insert_is_not_stored() -> None:
    def body() -> None:
        scope = open_scope("own-window", budget_s=1.0)
        owner = _ClosesAfterOwn(scope)
        pub = Subscribers("pub")
        calls: list = []
        pub.add(lambda *a, **k: calls.append("X"), owner=owner)
        assert len(pub) == 0
        assert pub.emit() == 0
        assert calls == []

    _bounded(body)


def test_add_races_owner_close_200_times_leaves_no_inactive() -> None:
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    leaks: list = []
    try:
        for i in range(200):
            scope = open_scope(f"race-{i}", budget_s=1.0)
            pub = Subscribers("pub")
            barrier = threading.Barrier(2)
            errors: list = []

            def adder(pub=pub, scope=scope, barrier=barrier, errors=errors) -> None:
                barrier.wait(5.0)
                try:
                    pub.add(_noop, owner=scope)
                except ScopeClosedError:
                    pass
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            def closer(scope=scope, barrier=barrier) -> None:
                barrier.wait(5.0)
                scope.close()

            threads = [threading.Thread(target=adder, daemon=True), threading.Thread(target=closer, daemon=True)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(5.0)
                assert not th.is_alive(), f"итерация {i}: поток завис"
            assert errors == [], f"итерация {i}: {errors}"
            if len(pub) != 0:
                leaks.append(i)
    finally:
        sys.setswitchinterval(old)
    assert leaks == [], f"снятая подписка осталась в хранилище в итерациях {leaks}"


def test_release_from_gc_finalizer_under_publisher_lock_no_deadlock() -> None:
    """Финализатор (h.close() → _Release) входит в поток, который держит лок издателя."""

    def body() -> None:
        root = open_scope("gc-fin", budget_s=1.0)
        pub = Subscribers("pub")
        calls: list = []
        pub.add(lambda *a, **k: calls.append("A"), owner=root)
        h_b = pub.add(lambda *a, **k: calls.append("B"), owner=root)
        pub.add(lambda *a, **k: calls.append("C"), owner=root)

        class Cycle:
            def __init__(self) -> None:
                self.me = self

            def __del__(self) -> None:
                h_b.close()

        gc.disable()
        try:
            Cycle()
            with pub._lock:  # посреди секции под локом
                gc.collect()
                assert sorted(s.seq for s in pub._store.values()) == sorted(pub._store)
                assert len(pub._store) == 2
            pub.add(lambda *a, **k: calls.append("D"), owner=root)
        finally:
            gc.enable()
        assert pub.emit() == 3
        assert calls == ["A", "C", "D"]
        assert pub.emits_after_close == 0
        root.close()

    _bounded(body)


def test_concurrent_emit_and_handle_close_counters_converge() -> None:
    """4 потока рассылают, пятый снимает и добавляет подписки: ни исключений, ни утечек."""
    root = open_scope("conc", budget_s=1.0)
    pub = Subscribers("pub")
    hits = [0]
    lock = threading.Lock()

    def counting(*args, **kwargs) -> None:
        with lock:
            hits[0] += 1

    pub.add(counting, owner=root)
    errors: list = []
    delivered = [0]

    def emitter() -> None:
        try:
            for _ in range(300):
                n = pub.emit()
                with lock:
                    delivered[0] += n
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def churn() -> None:
        try:
            for _ in range(300):
                h = pub.add(counting, owner=root)
                h.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=emitter, daemon=True) for _ in range(4)]
    threads.append(threading.Thread(target=churn, daemon=True))
    for th in threads:
        th.start()
    for th in threads:
        th.join(10.0)
        assert not th.is_alive()
    assert errors == []
    assert len(pub) == 1
    # Доставка по снимку может прийти в уже снятую чужим потоком подписку (окно
    # чужого потока), но число доставок равно числу вызовов подписчиков.
    assert delivered[0] == hits[0]
    assert pub.emits_after_close == 0  # владелец открыт: снятия ручкой не считаются
    assert root.close().ok is True


def test_name_validation() -> None:
    with pytest.raises(TypeError, match="name — ожидается str, получено int"):
        Subscribers(1)  # type: ignore[arg-type]
    for bad in ("", "a/b"):
        with pytest.raises(ValueError, match="непустая строка без '/'"):
            Subscribers(bad)


class _OwnOnly:
    """Есть ``own``, ``path``, ``closed`` — нет ``note_emits_after_close``."""

    def __init__(self, scope) -> None:
        self._scope = scope
        self.path = scope.path

    @property
    def closed(self) -> bool:
        return self._scope.closed

    def own(self, res, *, name, kind="resource"):
        return self._scope.own(res, name=name, kind=kind)


class _NoPath:
    def own(self, res, *, name, kind="resource"):
        raise AssertionError("add не должен дойти до own")

    closed = False

    def note_emits_after_close(self, n: int) -> None:
        pass


@pytest.mark.parametrize("shape", ["own_only", "no_path"])
def test_add_rejects_incomplete_owner_up_front(shape: str) -> None:
    """Ревью 0.3 р1 п.5: владелец без части IScope отвергается в ``add``, а не падает в ``emit``."""
    scope = open_scope(f"shape-{shape}", budget_s=1.0)
    owner = _OwnOnly(scope) if shape == "own_only" else _NoPath()
    pub = Subscribers("pub")
    with pytest.raises(TypeError, match=f"owner — ожидается IScope, получено {type(owner).__name__}"):
        pub.add(_noop, owner=owner)
    assert len(pub) == 0
    assert scope.close().ok is True
