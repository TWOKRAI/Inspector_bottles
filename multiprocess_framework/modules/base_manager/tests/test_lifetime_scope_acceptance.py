"""Независимые приёмочные тесты Task 0.2: область владения (open_scope / Scope / Handle / unclosed_roots).

Написаны вслепую, ДО реализации, по plans/2026-10-03_lifecycle-owner-scope/task-0.2-acceptance.md,
разделу «Контракт реализации» task-0.2.md и docstring'ам base_manager/interfaces.py.
Ожидаемые значения — литералы из спека.

Правила набора:
- вход только через дверь пакета (``open_scope`` / ``unclosed_roots``); импорт — внутри хелперов,
  поэтому до реализации сбор проходит, а каждый тест падает сам на двери;
- фейки — настоящие классы с общим журналом событий, не Mock;
- каждый вызов, который может зависнуть, идёт в daemon-потоке с join(timeout);
  зависание = assert с текстом, а не таймаут прогона;
- пути корней уникальны (uuid), поэтому литерал спека «root/w» читается как f"{rp}/w".
"""

from __future__ import annotations

import ast
import gc
import importlib
import inspect
import logging
import pickle
import queue
import threading
import time
import uuid
import weakref
from pathlib import Path

import pytest

PKG = "multiprocess_framework.modules.base_manager"
IFACE = PKG + ".interfaces"

EMPTY = inspect.Parameter.empty
POS_OR_KW = "POSITIONAL_OR_KEYWORD"
KW_ONLY = "KEYWORD_ONLY"


# ======================================================================== дверь и инфраструктура


def _open(path, **kw):
    return importlib.import_module(PKG).open_scope(path, **kw)


def _unclosed():
    return importlib.import_module(PKG).unclosed_roots()


def _iface(name):
    return getattr(importlib.import_module(IFACE), name)


def _report_cls():
    return _iface("CloseReport")


@pytest.fixture
def rp():
    """Уникальный путь корня."""
    return f"t02{uuid.uuid4().hex[:10]}"


@pytest.fixture
def release():
    """Событие, которое отпускает все «застрявшие» потоки теста при завершении."""
    ev = threading.Event()
    yield ev
    ev.set()


def _run(fn, *args, _timeout=10.0, _what="вызов", **kwargs):
    """Выполнить fn в daemon-потоке с join(timeout); вернуть (результат, длительность изнутри потока)."""
    box = {}

    def runner():
        t0 = time.monotonic()
        try:
            box["r"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["e"] = exc
        box["dt"] = time.monotonic() - t0

    th = threading.Thread(target=runner, daemon=True, name="t02-helper")
    th.start()
    th.join(_timeout)
    assert not th.is_alive(), f"{_what} завис дольше {_timeout} с"
    if "e" in box:
        raise box["e"]
    return box["r"], box["dt"]


def _close(scope, *args, **kwargs):
    return _run(scope.close, *args, _what="close()", **kwargs)


def _wait_until(pred, timeout=5.0, text="условие не наступило"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.005)
    assert pred(), text


def _thread_alive(name):
    return any(t.name == name for t in threading.enumerate())


def _wait_gone(name, timeout=3.0):
    _wait_until(lambda: not _thread_alive(name), timeout, f"поток {name!r} не вышел за {timeout} с")


def _live_map(scope):
    return {d["path"]: d["state"] for d in scope.live()}


def _live_paths(scope):
    return [d["path"] for d in scope.live()]


# ======================================================================== фейки


class Journal:
    """Общий журнал событий: (тег, имя, monotonic) в порядке добавления."""

    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def add(self, tag, name):
        with self._lock:
            self.events.append((tag, name, time.monotonic()))

    def positions(self, tag, name):
        with self._lock:
            return [i for i, (t, n, _) in enumerate(self.events) if t == tag and n == name]

    def first(self, tag, name):
        pos = self.positions(tag, name)
        assert pos, f"в журнале нет события {tag}({name}); есть: {self.names()}"
        return pos[0]

    def last(self, tag, name):
        pos = self.positions(tag, name)
        assert pos, f"в журнале нет события {tag}({name}); есть: {self.names()}"
        return pos[-1]

    def count(self, tag, name):
        return len(self.positions(tag, name))

    def time_of_last(self, tag, name):
        return self.events[self.last(tag, name)][2]

    def names(self):
        with self._lock:
            return [(t, n) for t, n, _ in self.events]

    def all_positions_of(self, name):
        with self._lock:
            return [i for i, (_, n, _) in enumerate(self.events) if n == name]


class Res:
    """Stoppable без kill и close.

    stop_delay — через сколько секунд ПОСЛЕ request_stop ресурс «умирает» (None — никогда).
    Время смерти меряется perf_counter, срок join_until — monotonic (контракт: абсолютный monotonic).
    """

    def __init__(self, journal, name, stop_delay=0.0):
        self.j = journal
        self.name = name
        self.stop_delay = stop_delay
        self._die_at = None
        self._lock = threading.Lock()

    def _die_by(self, delay):
        if delay is None:
            return
        at = time.perf_counter() + delay
        with self._lock:
            self._die_at = at if self._die_at is None else min(self._die_at, at)

    def _dead(self):
        with self._lock:
            return self._die_at is not None and time.perf_counter() >= self._die_at

    def request_stop(self):
        self.j.add("request_stop", self.name)
        self._die_by(self.stop_delay)

    def join_until(self, deadline):
        self.j.add("join_until", self.name)
        while True:
            if self._dead():
                result = True
                break
            if time.monotonic() >= deadline:
                result = False
                break
            time.sleep(0.002)
        self.j.add("join_until_return", self.name)
        return result


class ResK(Res):
    """Stoppable с kill(); kill_delay — через сколько после kill ресурс умирает (None — не умирает)."""

    def __init__(self, journal, name, stop_delay=None, kill_delay=None):
        super().__init__(journal, name, stop_delay)
        self.kill_delay = kill_delay

    def kill(self):
        self.j.add("kill", self.name)
        self._die_by(self.kill_delay)


class _CloseMixin:
    def close(self):
        self.j.add("close", self.name)


class ResC(_CloseMixin, Res):
    """Stoppable с close()."""


class ResKC(_CloseMixin, ResK):
    """Stoppable с kill() и close()."""


def _call(journal, name, *, raises=None, action=None):
    """Вызываемое-ресурс: пишет в журнал, при необходимости бросает или выполняет действие."""

    def fn():
        journal.add("call", name)
        if action is not None:
            action()
        if raises is not None:
            raise raises

    return fn


class Sink:
    """Сток: request_stop закрывает вход, потребитель дренирует очередь и выходит; join_until ждёт выхода."""

    _STOP = object()

    def __init__(self):
        self.received = []
        self.rejected = 0
        self._closed = False
        self._lock = threading.Lock()
        self._q = queue.Queue()
        self._consumer = threading.Thread(target=self._consume, daemon=True, name="t02-sink")
        self._consumer.start()

    def _consume(self):
        while True:
            item = self._q.get()
            if item is self._STOP:
                return
            self.received.append(item)

    def put(self, line):
        with self._lock:
            if self._closed:
                self.rejected += 1
                return False
            self._q.put(line)
            return True

    def request_stop(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._q.put(self._STOP)

    def join_until(self, deadline):
        self._consumer.join(max(0.0, deadline - time.monotonic()))
        return not self._consumer.is_alive()


# ======================================================================== дверь и форма


def test_door_open_scope_is_exported_by_package():
    pkg = importlib.import_module(PKG)
    assert "open_scope" in pkg.__all__
    assert callable(pkg.open_scope)


def test_door_unclosed_roots_is_exported_by_package():
    pkg = importlib.import_module(PKG)
    assert "unclosed_roots" in pkg.__all__
    assert callable(pkg.unclosed_roots)


@pytest.mark.parametrize("name", ["Scope", "Handle"])
def test_door_scope_and_handle_classes_are_not_in_all(name):
    assert name not in importlib.import_module(PKG).__all__


@pytest.mark.parametrize("name", ["Scope", "Handle"])
def test_door_scope_and_handle_classes_are_not_package_attributes(name):
    pkg = importlib.import_module(PKG)
    # якорь: дверь на месте, иначе тест красный по правильной причине
    assert callable(pkg.open_scope)
    assert hasattr(pkg, name) is False


def test_open_scope_signature_is_literal_from_spec():
    sig = inspect.signature(importlib.import_module(PKG).open_scope)
    got = [(p.name, p.kind.name, p.default) for p in sig.parameters.values()]
    assert got == [
        ("path", POS_OR_KW, EMPTY),
        ("budget_s", KW_ONLY, EMPTY),
        ("kill_reserve_s", KW_ONLY, 0.0),
        ("reporter", KW_ONLY, None),
    ]


SCOPE_MEMBERS = ["path", "closed", "parent", "own", "child", "barrier", "spawn", "cancel", "close", "live"]
HANDLE_MEMBERS = ["path", "kind", "close"]


@pytest.mark.parametrize("member", SCOPE_MEMBERS)
def test_scope_has_protocol_member(rp, member):
    root = _open(rp, budget_s=1.0)
    assert hasattr(root, member)


@pytest.mark.parametrize("member", HANDLE_MEMBERS)
def test_own_handle_has_protocol_member(rp, member):
    root = _open(rp, budget_s=1.0)
    handle = root.own(lambda: None, name="x")
    assert hasattr(handle, member)


@pytest.mark.parametrize("member", HANDLE_MEMBERS)
def test_spawn_handle_has_protocol_member(rp, member, release):
    root = _open(rp, budget_s=1.0)
    handle = root.spawn(lambda ev: release.wait(5), name="w")
    assert hasattr(handle, member)


# ---------------------------------------------------------------- числа

BAD_BUDGETS = [
    pytest.param(float("nan"), ValueError, id="nan"),
    pytest.param(-1.0, ValueError, id="negative"),
    pytest.param(float("inf"), ValueError, id="inf"),
    pytest.param(float("-inf"), ValueError, id="minus-inf"),
    pytest.param(True, TypeError, id="bool"),
    pytest.param("1.0", TypeError, id="str"),
]


@pytest.mark.parametrize("value,exc", BAD_BUDGETS)
def test_open_scope_rejects_bad_budget(rp, value, exc):
    with pytest.raises(exc):
        _open(rp, budget_s=value)


@pytest.mark.parametrize("value,exc", BAD_BUDGETS)
def test_open_scope_rejects_bad_kill_reserve(rp, value, exc):
    with pytest.raises(exc):
        _open(rp, budget_s=1.0, kill_reserve_s=value)


@pytest.mark.parametrize("value,exc", BAD_BUDGETS)
def test_child_rejects_bad_budget(rp, value, exc):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(exc):
        root.child("c", budget_s=value)


@pytest.mark.parametrize("value,exc", BAD_BUDGETS)
def test_child_rejects_bad_kill_reserve(rp, value, exc):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(exc):
        root.child("c", kill_reserve_s=value)


@pytest.mark.parametrize("value,exc", BAD_BUDGETS)
def test_close_rejects_bad_budget(rp, value, exc):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(exc):
        _run(root.close, value, _what="close(bad budget)")


@pytest.mark.parametrize("value,exc", BAD_BUDGETS)
def test_handle_close_rejects_bad_budget(rp, value, exc):
    root = _open(rp, budget_s=1.0)
    handle = root.own(lambda: None, name="x")
    with pytest.raises(exc):
        _run(handle.close, value, _what="handle.close(bad budget)")


@pytest.mark.parametrize(
    "value,exc",
    [
        pytest.param(float("nan"), ValueError, id="nan"),
        pytest.param(float("inf"), ValueError, id="inf"),
        pytest.param(True, TypeError, id="bool"),
    ],
)
def test_close_rejects_bad_deadline(rp, value, exc):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(exc):
        _run(root.close, deadline=value, _what="close(bad deadline)")


def test_close_with_both_budget_and_deadline_raises_value_error(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(ValueError):
        _run(root.close, budget_s=1.0, deadline=time.monotonic() + 1, _what="close(both)")


def test_close_with_both_budget_and_deadline_releases_nothing(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResC(j, "r"), name="r")
    root.own(_call(j, "cb"), name="cb")
    with pytest.raises(ValueError):
        _run(root.close, budget_s=1.0, deadline=time.monotonic() + 1, _what="close(both)")
    assert j.names() == []


def test_close_with_both_budget_and_deadline_leaves_scope_open(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(ValueError):
        _run(root.close, budget_s=1.0, deadline=time.monotonic() + 1, _what="close(both)")
    assert root.closed is False


def test_root_parent_is_none(rp):
    assert _open(rp, budget_s=1.0).parent is None


def test_child_parent_is_root(rp):
    root = _open(rp, budget_s=1.0)
    assert root.child("c").parent is root


def test_root_is_not_closed_before_close(rp):
    assert _open(rp, budget_s=1.0).closed is False


def test_root_closed_is_true_after_close(rp):
    root = _open(rp, budget_s=1.0)
    _close(root)
    assert root.closed is True


def test_callable_in_phase_two_sees_scope_closed(rp):
    seen = {}
    root = _open(rp, budget_s=1.0)
    root.own(lambda: seen.setdefault("closed", root.closed), name="x")
    _close(root)
    assert seen == {"closed": True}


def test_scope_paths(rp):
    root = _open(rp, budget_s=1.0)
    assert root.path == rp
    assert root.child("c").path == f"{rp}/c"


# ======================================================================== записи


class SomeClass:
    """Вызываемый класс без методов Stoppable; счётчик ловит «освобождение» созданием экземпляра."""

    created = 0

    def __init__(self):
        type(self).created += 1

    def __call__(self):
        return None


class StopLikeClass:
    """Класс (не экземпляр) с именами Stoppable: isinstance(StopLikeClass, Stoppable) is True (проба H3 0.1)."""

    def request_stop(self):
        return None

    def join_until(self, deadline):
        return True


class NotAResource:
    def __repr__(self):
        return "SECRET-REPR-9"


def test_own_class_instead_of_instance_raises_type_error_naming_class(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError) as exc:
        root.own(SomeClass, name="x")
    assert "SomeClass" in str(exc.value)


def test_own_class_is_not_instantiated(rp):
    SomeClass.created = 0
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError):
        root.own(SomeClass, name="x")
    assert SomeClass.created == 0


def test_own_class_creates_no_entry(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError):
        root.own(SomeClass, name="x")
    assert root.live() == []


def test_own_stoppable_looking_class_raises_type_error_naming_class(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError) as exc:
        root.own(StopLikeClass, name="x")
    assert "StopLikeClass" in str(exc.value)


def test_own_int_raises_type_error_naming_type(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError) as exc:
        root.own(42, name="x")
    assert "int" in str(exc.value)


def test_own_type_error_names_type_and_does_not_print_repr(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError) as exc:
        root.own(NotAResource(), name="x")
    text = str(exc.value)
    assert "NotAResource" in text
    assert "SECRET-REPR-9" not in text


@pytest.mark.parametrize("bad", ["", "a/b", "x (self)"], ids=["empty", "slash", "self-suffix"])
@pytest.mark.parametrize("method", ["own", "spawn", "child"])
def test_invalid_entry_name_raises_value_error(rp, method, bad):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(ValueError):
        if method == "own":
            root.own(lambda: None, name=bad)
        elif method == "spawn":
            root.spawn(lambda ev: None, name=bad)
        else:
            root.child(bad)


def test_duplicate_live_name_raises_value_error(rp):
    root = _open(rp, budget_s=1.0)
    root.own(lambda: None, name="x")
    with pytest.raises(ValueError):
        root.own(lambda: None, name="x")


def test_name_is_free_again_after_handle_close(rp):
    root = _open(rp, budget_s=1.0)
    handle = root.own(lambda: None, name="x")
    _run(handle.close, _what="handle.close()")
    root.own(lambda: None, name="x")  # не бросает


def test_handle_path_is_scope_path_slash_name(rp):
    root = _open(rp, budget_s=1.0)
    assert root.own(lambda: None, name="x").path == f"{rp}/x"


def test_handle_kind_defaults_to_resource(rp):
    root = _open(rp, budget_s=1.0)
    assert root.own(lambda: None, name="x").kind == "resource"


def test_handle_kind_custom_string_is_kept(rp):
    root = _open(rp, budget_s=1.0)
    assert root.own(lambda: None, name="x", kind="subscription").kind == "subscription"


def test_spawn_handle_kind_is_thread_and_path(rp, release):
    root = _open(rp, budget_s=1.0)
    handle = root.spawn(lambda ev: release.wait(5), name="w")
    assert (handle.kind, handle.path) == ("thread", f"{rp}/w")


def test_live_shows_child_entry_with_kind_scope(rp):
    root = _open(rp, budget_s=1.0)
    root.child("c")
    assert {"path": f"{rp}/c", "kind": "scope", "state": "open"} in root.live()


def test_live_is_recursive_in_registration_order_child_before_its_entries(rp):
    root = _open(rp, budget_s=1.0)
    root.own(lambda: None, name="a")
    c = root.child("c")
    c.own(lambda: None, name="x")
    root.own(lambda: None, name="b")
    assert _live_paths(root) == [f"{rp}/a", f"{rp}/c", f"{rp}/c/x", f"{rp}/b"]


def test_live_dict_keys_are_exactly_path_kind_state(rp):
    root = _open(rp, budget_s=1.0)
    root.own(lambda: None, name="a")
    assert [set(d) for d in root.live()] == [{"path", "kind", "state"}]


def test_live_is_empty_after_clean_close(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResC(j, "r"), name="r")
    root.own(_call(j, "cb"), name="cb")
    _close(root)
    assert root.live() == []


# ---------------------------------------------------------------- spawn


def test_spawn_thread_name_is_scope_path_slash_name(rp):
    seen = {}
    started = threading.Event()

    def target(ev):
        seen["name"] = threading.current_thread().name
        started.set()
        ev.wait(5)

    root = _open(rp, budget_s=1.0)
    root.spawn(target, name="w")
    assert started.wait(5)
    _close(root)
    assert seen["name"] == f"{rp}/w"


def test_spawn_thread_is_daemon(rp):
    seen = {}
    started = threading.Event()

    def target(ev):
        seen["daemon"] = threading.current_thread().daemon
        started.set()
        ev.wait(5)

    root = _open(rp, budget_s=1.0)
    root.spawn(target, name="w")
    assert started.wait(5)
    _close(root)
    assert seen["daemon"] is True


def test_spawn_target_receives_threading_event(rp):
    seen = {}
    started = threading.Event()

    def target(ev):
        seen["ev"] = ev
        started.set()
        ev.wait(5)

    root = _open(rp, budget_s=1.0)
    root.spawn(target, name="w")
    assert started.wait(5)
    _close(root)
    assert isinstance(seen["ev"], threading.Event)


def test_spawn_event_is_set_by_phase_one(rp):
    seen = {}
    started = threading.Event()

    def target(ev):
        seen["ev"] = ev
        started.set()
        ev.wait(5)

    root = _open(rp, budget_s=1.0)
    root.spawn(target, name="w")
    assert started.wait(5)
    assert seen["ev"].is_set() is False
    _close(root)
    assert seen["ev"].is_set() is True


def test_thread_that_returned_is_absent_from_live(rp):
    root = _open(rp, budget_s=1.0)
    root.spawn(lambda ev: None, name="w")
    _wait_gone(f"{rp}/w")
    _wait_until(lambda: f"{rp}/w" not in _live_paths(root), 3.0, "запись вышедшего потока осталась в live()")


def test_name_is_free_after_thread_returned(rp):
    root = _open(rp, budget_s=1.0)
    root.spawn(lambda ev: None, name="w")
    _wait_gone(f"{rp}/w")
    _wait_until(lambda: f"{rp}/w" not in _live_paths(root), 3.0, "запись вышедшего потока осталась в live()")
    root.spawn(lambda ev: None, name="w")  # не бросает ValueError


def test_handle_close_of_normally_finished_thread_is_ok(rp):
    root = _open(rp, budget_s=1.0)
    handle = root.spawn(lambda ev: None, name="w")
    _wait_gone(f"{rp}/w")
    report, _ = _run(handle.close, _what="handle.close()")
    assert report.ok is True


def test_old_handle_does_not_touch_new_entry_with_same_name(rp, release):
    root = _open(rp, budget_s=1.0)
    old = root.spawn(lambda ev: None, name="w")
    _wait_gone(f"{rp}/w")
    _wait_until(lambda: f"{rp}/w" not in _live_paths(root), 3.0, "запись вышедшего потока осталась в live()")
    root.spawn(lambda ev: release.wait(5), name="w")
    _run(old.close, _what="old.close()")
    assert _live_map(root).get(f"{rp}/w") == "open"


def _failing_thread_scope(rp):
    root = _open(rp, budget_s=1.0)

    def target(ev):
        raise ValueError("x")

    handle = root.spawn(target, name="w")
    _wait_gone(f"{rp}/w")
    return root, handle


def test_thread_exception_pair_goes_to_scope_close_report(rp):
    root, _ = _failing_thread_scope(rp)
    report, _ = _close(root)
    assert (f"{rp}/w", "ValueError: x") in report.errors


def test_thread_exception_pair_goes_to_handle_close_when_closed_first(rp):
    root, handle = _failing_thread_scope(rp)
    report, _ = _run(handle.close, _what="handle.close()")
    assert (f"{rp}/w", "ValueError: x") in report.errors


def test_thread_exception_pair_is_not_repeated_in_scope_report_after_handle_close(rp):
    root, handle = _failing_thread_scope(rp)
    _run(handle.close, _what="handle.close()")
    scope_report, _ = _close(root)
    assert (f"{rp}/w", "ValueError: x") not in scope_report.errors


def test_child_inherits_budget_and_kill_reserve_from_root(rp):
    j = Journal()
    root = _open(rp, budget_s=0.2, kill_reserve_s=0.3)
    c = root.child("c")
    c.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _close(root)
    assert f"{rp}/c/x" in report.killed


# ======================================================================== фазы и порядок


def test_callables_are_called_in_lifo_order(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(_call(j, "a"), name="a")
    root.own(_call(j, "b"), name="b")
    root.own(_call(j, "c"), name="c")
    _close(root)
    assert j.names() == [("call", "c"), ("call", "b"), ("call", "a")]


def test_callable_is_called_exactly_once_even_on_repeated_close(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(_call(j, "a"), name="a")
    _close(root)
    _close(root)
    assert j.count("call", "a") == 1


def test_both_request_stops_precede_first_join_until_in_one_segment(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResC(j, "a"), name="a")
    root.own(ResC(j, "b"), name="b")
    _close(root)
    last_request_stop = max(j.last("request_stop", "a"), j.last("request_stop", "b"))
    first_join = min(j.first("join_until", "a"), j.first("join_until", "b"))
    assert last_request_stop < first_join


def test_stopped_stoppable_gets_close_exactly_once(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResC(j, "a", stop_delay=0.0), name="a")
    _close(root)
    assert j.count("close", "a") == 1


def test_close_is_called_after_successful_join_until(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResC(j, "a", stop_delay=0.0), name="a")
    _close(root)
    assert j.first("close", "a") > j.last("join_until_return", "a")


def test_survivor_stoppable_never_gets_close(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1)
    root.own(ResC(j, "a", stop_delay=None), name="a")
    _close(root)
    assert j.count("close", "a") == 0


def test_survivor_is_reported_in_survivors(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1)
    root.own(ResC(j, "a", stop_delay=None), name="a")
    report, _ = _close(root)
    assert f"{rp}/a" in report.survivors


def test_callable_exception_goes_to_errors_with_type_and_text(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(_call(j, "x", raises=RuntimeError("boom")), name="x")
    report, _ = _close(root)
    assert (f"{rp}/x", "RuntimeError: boom") in report.errors


def test_callable_exception_does_not_leave_earlier_entries_unreleased(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(_call(j, "early"), name="early")
    root.own(ResC(j, "early_res", stop_delay=0.0), name="early_res")
    root.own(_call(j, "x", raises=RuntimeError("boom")), name="x")
    _close(root)
    assert j.count("call", "early") == 1
    assert j.count("close", "early_res") == 1


def test_close_does_not_raise_when_callable_raises(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(_call(j, "x", raises=RuntimeError("boom")), name="x")
    report, _ = _close(root)  # не бросает
    assert report.ok is False


# ======================================================================== G1 (a)-(f)


class _Pub:
    def __init__(self):
        self.subs = []

    def subscribe(self, fn):
        self.subs.append(fn)

        def unsub():
            if fn in self.subs:
                self.subs.remove(fn)

        return unsub


class _Presenter:
    def __init__(self, pub, scope, name):
        self.pub = pub
        self.hits = 0
        scope.own(pub.subscribe(self.on_event), name=name)  # ручку не храним

    def on_event(self):
        self.hits += 1


def _scenario_a(rp):
    """Возвращает (слабая ссылка мертва без gc.collect(), список мусора по типам теста)."""
    gc.collect()
    gc.disable()
    try:
        root = _open(rp, budget_s=1.0)
        pub = _Pub()
        presenter = _Presenter(pub, root, "sub")
        ref = weakref.ref(presenter)
        report, _ = _close(root)
        assert report.ok is True
        del presenter
        dead = ref() is None
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect()
        junk = [o for o in gc.garbage if isinstance(o, (_Pub, _Presenter))]
        return dead, junk
    finally:
        gc.set_debug(0)
        gc.garbage.clear()
        gc.enable()


def test_a_presenter_is_freed_by_refcount_after_close(rp):
    dead, _ = _scenario_a(rp)
    assert dead is True


def test_a_no_test_garbage_is_left_for_the_collector(rp):
    _, junk = _scenario_a(rp)
    assert junk == []


def test_c_own_after_close_calls_resource_before_raising(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    _close(root)
    with pytest.raises(_iface("ScopeClosedError")):
        root.own(_call(j, "cb"), name="late")
    assert j.count("call", "cb") == 1


def test_c_own_stoppable_after_close_is_released_before_raising(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    _close(root)
    with pytest.raises(_iface("ScopeClosedError")):
        root.own(ResC(j, "late", stop_delay=0.0), name="late")
    assert j.count("request_stop", "late") == 1


def test_c_closed_error_text_names_path_name_and_state(rp):
    root = _open(rp, budget_s=1.0)
    _close(root)
    with pytest.raises(_iface("ScopeClosedError")) as exc:
        root.own(lambda: None, name="late")
    text = str(exc.value)
    assert rp in text
    assert "late" in text
    assert "closed" in text


def _closing_probe(rp, action):
    """Вызываемое фазы 2 выполняет action(root) и записывает исключение; возвращает (probe, journal, report)."""
    j = Journal()
    probe = {}
    root = _open(rp, budget_s=1.0)

    def inside():
        try:
            action(root, j)
        except BaseException as exc:  # noqa: BLE001
            probe["exc"] = exc

    root.own(inside, name="inside")
    report, _ = _close(root)
    return probe, j, report


def test_c_own_from_phase_two_callable_raises_scope_closed_error(rp):
    probe, _, _ = _closing_probe(rp, lambda root, j: root.own(_call(j, "cb"), name="late"))
    assert isinstance(probe.get("exc"), _iface("ScopeClosedError"))


def test_c_own_from_phase_two_callable_releases_resource_before_raising(rp):
    _, j, _ = _closing_probe(rp, lambda root, j: root.own(_call(j, "cb"), name="late"))
    assert j.count("call", "cb") == 1


def test_c_closing_error_text_names_path_name_and_state(rp):
    probe, _, _ = _closing_probe(rp, lambda root, j: root.own(_call(j, "cb"), name="late"))
    text = str(probe["exc"])
    assert rp in text
    assert "late" in text
    assert "closing" in text


def test_c_spawn_during_close_raises_scope_closed_error(rp):
    probe, _, _ = _closing_probe(rp, lambda root, j: root.spawn(lambda ev: j.add("target", "w"), name="w"))
    assert isinstance(probe.get("exc"), _iface("ScopeClosedError"))


def test_c_spawn_during_close_never_calls_target(rp):
    _, j, _ = _closing_probe(rp, lambda root, j: root.spawn(lambda ev: j.add("target", "w"), name="w"))
    time.sleep(0.15)
    assert j.count("target", "w") == 0


def test_c_child_during_close_raises_scope_closed_error(rp):
    probe, _, _ = _closing_probe(rp, lambda root, j: root.child("c"))
    assert isinstance(probe.get("exc"), _iface("ScopeClosedError"))


def test_c_spawn_after_close_raises_scope_closed_error_and_target_not_called(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    _close(root)
    with pytest.raises(_iface("ScopeClosedError")):
        root.spawn(lambda ev: j.add("target", "w"), name="w")
    time.sleep(0.15)
    assert j.count("target", "w") == 0


def test_c_child_after_close_raises_scope_closed_error(rp):
    root = _open(rp, budget_s=1.0)
    _close(root)
    with pytest.raises(_iface("ScopeClosedError")):
        root.child("c")


def test_c_own_on_closed_scope_makes_a_separate_reporter_call(rp):
    calls = []
    root = _open(rp, budget_s=1.0, reporter=calls.append)
    _close(root)
    assert len(calls) == 1
    with pytest.raises(_iface("ScopeClosedError")):
        root.own(lambda: None, name="late")
    assert len(calls) == 2


class _Sub:
    def __init__(self, fn=None):
        self.active = True
        self.hits = 0
        self.fn = fn


class _SnapshotPub:
    """Издатель обходит снимок подписчиков и пропускает неактивных."""

    def __init__(self):
        self.subs = []

    def emit(self):
        for s in list(self.subs):
            if not s.active:
                continue
            s.hits += 1
            if s.fn is not None:
                s.fn()


def test_d_subscriber_closing_scope_stops_delivery_to_later_subscriber_in_same_emit(rp):
    root = _open(rp, budget_s=1.0)
    pub = _SnapshotPub()
    a, c = _Sub(), _Sub()
    b = _Sub(fn=lambda: root.close())

    def unsub_c():
        c.active = False
        if c in pub.subs:
            pub.subs.remove(c)

    pub.subs.extend([a, b, c])
    root.own(unsub_c, name="unsub_c")
    _run(pub.emit, _what="emit")
    assert (a.hits, b.hits, c.hits) == (1, 1, 0)


def _reentrant_scenario(rp):
    inner = {}
    root = _open(rp, budget_s=1.0)

    def reenter():
        t0 = time.monotonic()
        inner["r"] = root.close()
        inner["dt"] = time.monotonic() - t0

    root.own(reenter, name="re")
    outer, _ = _close(root)
    return inner, outer


def test_d_reentrant_close_from_phase_two_returns_within_100ms(rp):
    inner, _ = _reentrant_scenario(rp)
    assert inner["dt"] <= 0.1


def test_d_reentrant_close_returns_incomplete_report(rp):
    inner, _ = _reentrant_scenario(rp)
    assert inner["r"].complete is False


def test_d_outer_report_stays_complete_after_reentrant_close(rp):
    _, outer = _reentrant_scenario(rp)
    assert outer.complete is True


def test_b_stubborn_thread_makes_close_return_within_budget_plus_200ms(rp, release):
    root = _open(rp, budget_s=1.0, kill_reserve_s=0.0)
    root.spawn(lambda ev: release.wait(3.0), name="w")
    _, dt = _close(root)
    assert dt <= 1.2


def test_b_close_waits_for_the_budget_before_giving_up_on_a_thread(rp, release):
    # дополнение тестера: close не должен возвращаться сразу, фаза 2 обязана ждать срок
    root = _open(rp, budget_s=1.0, kill_reserve_s=0.0)
    root.spawn(lambda ev: release.wait(3.0), name="w")
    _, dt = _close(root)
    assert dt >= 0.8


def test_b_stubborn_thread_is_in_survivors(rp, release):
    root = _open(rp, budget_s=1.0, kill_reserve_s=0.0)
    root.spawn(lambda ev: release.wait(3.0), name="w")
    report, _ = _close(root)
    assert f"{rp}/w" in report.survivors


def test_b_stubborn_thread_is_listed_as_survivor_in_live(rp, release):
    root = _open(rp, budget_s=1.0, kill_reserve_s=0.0)
    root.spawn(lambda ev: release.wait(3.0), name="w")
    _close(root)
    assert {"path": f"{rp}/w", "kind": "thread", "state": "survivor"} in root.live()


def test_b_stubborn_thread_is_not_in_killed(rp, release):
    root = _open(rp, budget_s=1.0, kill_reserve_s=0.0)
    root.spawn(lambda ev: release.wait(3.0), name="w")
    report, _ = _close(root)
    assert f"{rp}/w" not in report.killed


def _slow_close_scenario(rp, second_args=(), second_kwargs=None):
    """Первый close идёт ~0.3 с; через 0.05 с из другого потока стартует второй."""
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResC(j, "slow", stop_delay=0.3), name="slow")
    b1, b2 = {}, {}

    def runner(box, *a, **kw):
        t0 = time.monotonic()
        box["r"] = root.close(*a, **kw)
        box["t_end"] = time.monotonic()
        box["dt"] = box["t_end"] - t0

    t1 = threading.Thread(target=runner, args=(b1,), daemon=True, name="t02-close-1")
    t1.start()
    time.sleep(0.05)
    t2 = threading.Thread(
        target=runner, args=(b2, *second_args), kwargs=second_kwargs or {}, daemon=True, name="t02-close-2"
    )
    t2.start()
    t1.join(10)
    t2.join(10)
    assert not t1.is_alive(), "первый close завис"
    assert not t2.is_alive(), "второй close завис"
    return b1, b2


def test_e_first_close_takes_the_resource_time(rp):
    b1, _ = _slow_close_scenario(rp)
    assert b1["dt"] >= 0.25  # сценарий настоящий: ресурс выходит через 0.3 с


def test_e_second_close_from_foreign_thread_returns_the_same_report_object(rp):
    b1, b2 = _slow_close_scenario(rp)
    assert b2["r"] is b1["r"]


def test_e_second_close_returns_after_the_first(rp):
    b1, b2 = _slow_close_scenario(rp)
    assert b2["t_end"] >= b1["t_end"] - 0.03  # допуск сетки monotonic Windows


def test_e_second_close_with_tiny_budget_is_incomplete(rp):
    b1, b2 = _slow_close_scenario(rp, second_kwargs={"budget_s": 0.05})
    assert b2["r"].complete is False


def test_e_second_close_with_tiny_budget_is_a_different_report(rp):
    b1, b2 = _slow_close_scenario(rp, second_kwargs={"budget_s": 0.05})
    assert b2["r"] is not b1["r"]


def test_e_first_close_stays_complete_when_second_gives_up(rp):
    b1, _ = _slow_close_scenario(rp, second_kwargs={"budget_s": 0.05})
    assert b1["r"].complete is True


def _scenario_f(rp, via_child, release):
    root = _open(rp, budget_s=1.0)
    owner = root.child("c") if via_child else root
    box = {}
    go = threading.Event()

    def target(ev):
        go.wait(5)
        t0 = time.monotonic()
        box["r"] = root.close()
        box["dt"] = time.monotonic() - t0

    owner.spawn(target, name="w")
    go.set()
    _wait_until(lambda: "r" in box, 6.0, "close() из spawn-потока не вернулся (дедлок)")
    entry = f"{rp}/c/w" if via_child else f"{rp}/w"
    return box, entry


@pytest.mark.parametrize("via_child", [False, True], ids=["own-scope", "child-scope"])
def test_f_thread_closing_its_scope_returns_within_budget_plus_200ms(rp, release, via_child):
    box, _ = _scenario_f(rp, via_child, release)
    assert box["dt"] <= 1.0 + 0.2


@pytest.mark.parametrize("via_child", [False, True], ids=["own-scope", "child-scope"])
def test_f_thread_closing_its_scope_is_marked_self_in_survivors(rp, release, via_child):
    box, entry = _scenario_f(rp, via_child, release)
    assert f"{entry} (self)" in box["r"].survivors


@pytest.mark.parametrize("via_child", [False, True], ids=["own-scope", "child-scope"])
def test_f_thread_closing_its_scope_is_not_in_killed(rp, release, via_child):
    box, entry = _scenario_f(rp, via_child, release)
    assert entry not in box["r"].killed


@pytest.mark.parametrize("via_child", [False, True], ids=["own-scope", "child-scope"])
def test_f_thread_closing_its_scope_gets_complete_report(rp, release, via_child):
    box, _ = _scenario_f(rp, via_child, release)
    assert box["r"].complete is True


def _scenario_f2(rp):
    root = _open(rp, budget_s=1.0)
    c = root.child("c")
    inner = {}

    def target(ev):
        ev.wait(5)
        t0 = time.monotonic()
        inner["r"] = root.close()
        inner["dt"] = time.monotonic() - t0

    c.spawn(target, name="w")
    outer, dt = _close(root)
    _wait_until(lambda: "r" in inner, 3.0, "spawn-поток не вызвал root.close()")
    return inner, outer, dt


def test_f2_subtree_thread_calling_close_returns_within_100ms(rp):
    inner, _, _ = _scenario_f2(rp)
    assert inner["dt"] <= 0.1


def test_f2_subtree_thread_calling_close_gets_incomplete_report(rp):
    inner, _, _ = _scenario_f2(rp)
    assert inner["r"].complete is False


def test_f2_closer_thread_close_takes_at_most_200ms(rp):
    _, _, dt = _scenario_f2(rp)
    assert dt <= 0.2


def test_f2_closer_thread_report_stays_complete(rp):
    _, outer, _ = _scenario_f2(rp)
    assert outer.complete is True


# ======================================================================== сроки (Q3)


def test_q3_child_with_small_budget_finishes_phase_two_by_its_own_deadline(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    c = root.child("c", budget_s=0.2)
    c.own(Res(j, "stuck", stop_delay=None), name="stuck")
    t0 = time.monotonic()
    _close(root)
    assert j.time_of_last("join_until_return", "stuck") - t0 <= 0.35


def test_q3_child_with_big_budget_does_not_outlive_parent_deadline(rp):
    j = Journal()
    root = _open(rp, budget_s=0.3)
    c = root.child("c", budget_s=2.0)
    c.own(Res(j, "stuck", stop_delay=None), name="stuck")
    _, dt = _close(root)
    assert dt <= 0.45


def _two_killable_scenario(rp):
    j = Journal()
    root = _open(rp, budget_s=0.3, kill_reserve_s=0.5)
    root.own(ResK(j, "a", stop_delay=None, kill_delay=0.3), name="a")
    root.own(ResK(j, "b", stop_delay=None, kill_delay=0.3), name="b")
    report, _ = _close(root)
    return report


def test_q3_two_killable_in_one_segment_are_both_killed(rp):
    report = _two_killable_scenario(rp)
    assert f"{rp}/a" in report.killed
    assert f"{rp}/b" in report.killed


def test_q3_two_killable_in_one_segment_fit_budget_plus_reserve(rp):
    report = _two_killable_scenario(rp)
    assert report.elapsed_s <= 0.3 + 0.5 + 0.1


def test_q3_two_killable_wait_is_shared_not_sequential(rp):
    # дополнение тестера: общее ожидание ~0.6 с, по одному (J6) — не меньше 0.9 с
    report = _two_killable_scenario(rp)
    assert report.elapsed_s < 0.75


def test_q3_killed_entries_are_not_survivors(rp):
    report = _two_killable_scenario(rp)
    assert set(report.killed).isdisjoint(report.survivors)


def _two_segments_unkillable(rp):
    j = Journal()
    root = _open(rp, budget_s=0.2, kill_reserve_s=0.3)
    root.own(ResK(j, "low", stop_delay=None, kill_delay=None), name="low")
    root.barrier()
    root.own(ResK(j, "top", stop_delay=None, kill_delay=None), name="top")
    report, _ = _close(root)
    return j, report


def test_q3_two_segments_unkillable_fit_budget_plus_one_reserve(rp):
    _, report = _two_segments_unkillable(rp)
    assert report.elapsed_s <= 0.2 + 0.3 + 0.1


def test_q3_two_segments_unkillable_both_are_survivors(rp):
    _, report = _two_segments_unkillable(rp)
    assert f"{rp}/low" in report.survivors
    assert f"{rp}/top" in report.survivors


def test_q3_kill_is_called_on_every_unstopped_entry(rp):
    j, _ = _two_segments_unkillable(rp)
    assert j.count("kill", "low") == 1
    assert j.count("kill", "top") == 1


def test_q3_lower_segment_after_deadline_gets_one_check_without_waiting(rp):
    j = Journal()
    root = _open(rp, budget_s=0.2, kill_reserve_s=0.3)
    root.own(Res(j, "lower", stop_delay=0.01), name="lower")
    root.barrier()
    root.own(ResK(j, "upper", stop_delay=None, kill_delay=None), name="upper")
    report, _ = _close(root)
    assert f"{rp}/lower" in report.survivors


def test_q3_zero_reserve_calls_kill(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.0)
    root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    _close(root)
    assert j.count("kill", "x") == 1


def test_q3_zero_reserve_unconfirmed_death_is_survivor(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.0)
    root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _close(root)
    assert f"{rp}/x" in report.survivors


def test_q3_zero_reserve_unconfirmed_death_is_not_killed(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.0)
    root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _close(root)
    assert f"{rp}/x" not in report.killed


def test_q3_reserve_0_3_same_resource_is_killed(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.3)
    root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _close(root)
    assert f"{rp}/x" in report.killed


def test_q3_reserve_0_3_killed_resource_is_not_survivor(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.3)
    root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _close(root)
    assert f"{rp}/x" not in report.survivors


def _own_from_phase_two_scenario(rp):
    j = Journal()
    calls = []
    probe = {}
    root = _open(rp, budget_s=0.3, kill_reserve_s=0.0, reporter=calls.append)
    stubborn = Res(j, "late", stop_delay=None)

    def inside():
        try:
            root.own(stubborn, name="late")
        except BaseException as exc:  # noqa: BLE001
            probe["exc"] = exc

    root.own(inside, name="inside")
    report, _ = _close(root)
    return probe, report, calls


def test_q3_own_from_phase_two_stubborn_raises_scope_closed_error(rp):
    probe, _, _ = _own_from_phase_two_scenario(rp)
    assert isinstance(probe.get("exc"), _iface("ScopeClosedError"))


def test_q3_own_from_phase_two_stubborn_is_survivor_of_outer_report(rp):
    _, report, _ = _own_from_phase_two_scenario(rp)
    assert f"{rp}/late" in report.survivors


def test_q3_own_from_phase_two_makes_exactly_one_reporter_call(rp):
    _, _, calls = _own_from_phase_two_scenario(rp)
    assert len(calls) == 1


def test_q3_own_from_phase_two_does_not_stretch_outer_close(rp):
    _, report, _ = _own_from_phase_two_scenario(rp)
    assert report.elapsed_s <= 0.3 + 0.1


def test_q3_handle_close_without_argument_uses_scope_budget_and_reserve(rp):
    j = Journal()
    root = _open(rp, budget_s=0.2, kill_reserve_s=0.3)
    handle = root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _run(handle.close, _what="handle.close()")
    assert f"{rp}/x" in report.killed


def test_q3_handle_close_without_argument_fits_budget_plus_reserve(rp):
    j = Journal()
    root = _open(rp, budget_s=0.2, kill_reserve_s=0.3)
    handle = root.own(ResK(j, "x", stop_delay=None, kill_delay=0.05), name="x")
    report, _ = _run(handle.close, _what="handle.close()")
    assert report.elapsed_s <= 0.6


def test_report_elapsed_s_agrees_with_wall_clock(rp):
    # дополнение тестера: elapsed_s не выдумка DTO
    j = Journal()
    root = _open(rp, budget_s=0.3)
    root.own(Res(j, "stuck", stop_delay=None), name="stuck")
    report, dt = _close(root)
    assert abs(report.elapsed_s - dt) <= 0.15
    assert report.elapsed_s >= 0.25


# ======================================================================== барьер и cancel


def test_barrier_sink_receives_all_lines_including_late_writer_thread(rp):
    sink = Sink()
    root = _open(rp, budget_s=2.0)
    root.own(sink, name="sink")
    root.barrier()
    root.own(lambda: sink.put("final"), name="final")

    def writer(ev):
        ev.wait(5)  # пишет ПОСЛЕ фазы 1 своего сегмента, пока сток нижнего сегмента обязан быть открыт
        for i in range(200):
            sink.put(f"line{i}")

    root.spawn(writer, name="writer")
    _close(root)
    assert len(sink.received) == 201
    assert sink.rejected == 0


def test_barrier_lower_segment_stops_after_last_event_of_upper_segment(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.2)
    root.own(ResKC(j, "lower", stop_delay=0.0, kill_delay=0.0), name="lower")
    root.barrier()
    root.own(ResKC(j, "upper", stop_delay=None, kill_delay=0.05), name="upper")
    _close(root)
    upper_last = max(j.all_positions_of("upper"))
    assert j.first("request_stop", "lower") > upper_last


def test_barrier_upper_segment_phase_three_happens_before_lower_request_stop(rp):
    j = Journal()
    root = _open(rp, budget_s=0.1, kill_reserve_s=0.2)
    root.own(Res(j, "lower", stop_delay=0.0), name="lower")
    root.barrier()
    root.own(ResK(j, "upper", stop_delay=None, kill_delay=0.05), name="upper")
    _close(root)
    assert j.first("kill", "upper") < j.first("request_stop", "lower")


def _nested_barrier_child(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    c = root.child("c")
    c.own(ResC(j, "x"), name="x")
    c.barrier()
    c.own(ResC(j, "y"), name="y")
    return j, root, c


def test_nested_barrier_root_close_stops_lower_x_after_phase_two_of_y(rp):
    j, root, _ = _nested_barrier_child(rp)
    _close(root)
    assert j.first("request_stop", "x") > j.last("join_until_return", "y")


def test_nested_barrier_direct_child_close_stops_lower_x_after_phase_two_of_y(rp):
    j, _, c = _nested_barrier_child(rp)
    _close(c)
    assert j.first("request_stop", "x") > j.last("join_until_return", "y")


def test_nested_barrier_root_close_requests_stop_of_upper_y_first(rp):
    j, root, _ = _nested_barrier_child(rp)
    _close(root)
    assert j.first("request_stop", "y") < j.first("request_stop", "x")


def _stuck_cancel_scenario(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    root.own(ResKC(j, "lower1", stop_delay=None), name="lower1")
    root.barrier()
    root.own(ResKC(j, "upper1", stop_delay=None), name="upper1")
    c = root.child("c")
    c.own(ResKC(j, "lowerC", stop_delay=None), name="lowerC")
    c.barrier()
    c.own(ResKC(j, "upperC", stop_delay=None), name="upperC")
    return j, root


def test_cancel_requests_stop_of_top_segment_entries(rp):
    j, root = _stuck_cancel_scenario(rp)
    _run(root.cancel, _what="cancel()")
    assert j.count("request_stop", "upper1") == 1
    assert j.count("request_stop", "upperC") == 1


def test_cancel_does_not_touch_lower_segments_of_root_and_child(rp):
    j, root = _stuck_cancel_scenario(rp)
    _run(root.cancel, _what="cancel()")
    assert j.count("request_stop", "lower1") == 0
    assert j.count("request_stop", "lowerC") == 0


def test_cancel_returns_within_50ms_with_stuck_resources(rp):
    _, root = _stuck_cancel_scenario(rp)
    _, dt = _run(root.cancel, _what="cancel()")
    assert dt <= 0.05


def test_cancel_twice_does_not_repeat_request_stop(rp):
    j, root = _stuck_cancel_scenario(rp)
    _run(root.cancel, _what="cancel()")
    _run(root.cancel, _what="cancel() #2")
    assert j.count("request_stop", "upper1") == 1
    assert j.count("request_stop", "upperC") == 1


def test_cancel_leaves_scope_open_and_own_works_afterwards(rp):
    j, root = _stuck_cancel_scenario(rp)
    _run(root.cancel, _what="cancel()")
    assert root.closed is False
    root.own(lambda: None, name="after")  # не бросает
    assert _live_map(root)[f"{rp}/after"] == "open"


def test_cancel_marks_top_entries_stopping_and_lower_open_in_live(rp):
    _, root = _stuck_cancel_scenario(rp)
    _run(root.cancel, _what="cancel()")
    states = _live_map(root)
    assert states[f"{rp}/upper1"] == "stopping"
    assert states[f"{rp}/c/upperC"] == "stopping"
    assert states[f"{rp}/lower1"] == "open"
    assert states[f"{rp}/c/lowerC"] == "open"


# ======================================================================== Handle


def test_handle_close_twice_releases_resource_once(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    handle = root.own(_call(j, "x"), name="x")
    _run(handle.close, _what="handle.close()")
    _run(handle.close, _what="handle.close() #2")
    assert j.count("call", "x") == 1


def test_handle_close_twice_returns_same_report_object(rp):
    root = _open(rp, budget_s=1.0)
    handle = root.own(lambda: None, name="x")
    r1, _ = _run(handle.close, _what="handle.close()")
    r2, _ = _run(handle.close, _what="handle.close() #2")
    assert r2 is r1


def test_handle_close_removes_entry_from_live(rp):
    root = _open(rp, budget_s=1.0)
    handle = root.own(lambda: None, name="x")
    _run(handle.close, _what="handle.close()")
    assert f"{rp}/x" not in _live_paths(root)


def test_handle_close_of_stoppable_closes_it_once(rp):
    j = Journal()
    root = _open(rp, budget_s=1.0)
    handle = root.own(ResC(j, "x"), name="x")
    _run(handle.close, _what="handle.close()")
    _run(handle.close, _what="handle.close() #2")
    assert j.count("close", "x") == 1


class _CallableObj:
    def __call__(self):
        return None


def _scenario_handle_refcount(rp, resource_factory):
    gc.collect()
    gc.disable()
    try:
        root = _open(rp, budget_s=1.0)
        res = resource_factory()
        handle = root.own(res, name="x")
        _run(handle.close, _what="handle.close()")
        ref = weakref.ref(res)
        del res
        return ref() is None, handle  # handle ещё жив: он не должен держать ресурс
    finally:
        gc.enable()


def test_handle_does_not_hold_closed_stoppable(rp):
    dead, _handle = _scenario_handle_refcount(rp, lambda: Res(Journal(), "x"))
    assert dead is True


def test_handle_does_not_hold_closed_callable(rp):
    dead, _handle = _scenario_handle_refcount(rp, _CallableObj)
    assert dead is True


def test_early_child_close_detaches_child_from_parent_live(rp):
    root = _open(rp, budget_s=1.0)
    c = root.child("c")
    c.own(lambda: None, name="x")
    _close(c)
    assert not [p for p in _live_paths(root) if p == f"{rp}/c" or p.startswith(f"{rp}/c/")]


def test_early_child_close_calls_reporter_once(rp):
    calls = []
    root = _open(rp, budget_s=1.0, reporter=calls.append)
    c = root.child("c")
    c.own(lambda: None, name="x")
    _close(c)
    assert len(calls) == 1


# ======================================================================== Reporter


def test_root_close_with_child_and_three_entries_calls_reporter_exactly_once(rp):
    j = Journal()
    calls = []
    root = _open(rp, budget_s=1.0, reporter=calls.append)
    root.own(_call(j, "a"), name="a")
    root.own(ResC(j, "b"), name="b")
    c = root.child("c")
    c.own(_call(j, "x"), name="x")
    root.own(ResC(j, "d"), name="d")
    _close(root)
    assert len(calls) == 1


def test_reporter_argument_is_the_returned_report(rp):
    j = Journal()
    calls = []
    root = _open(rp, budget_s=1.0, reporter=calls.append)
    root.own(_call(j, "a"), name="a")
    c = root.child("c")
    c.own(_call(j, "x"), name="x")
    report, _ = _close(root)
    assert calls[0] is report


def test_reporter_is_called_by_closing_thread(rp):
    seen = []
    root = _open(rp, budget_s=1.0, reporter=lambda r: seen.append(threading.current_thread().name))
    _close(root)
    assert seen == ["t02-helper"]


def test_early_handle_close_calls_reporter_once_with_ok_report(rp):
    calls = []
    root = _open(rp, budget_s=1.0, reporter=calls.append)
    handle = root.own(lambda: None, name="x")
    report, _ = _run(handle.close, _what="handle.close()")
    assert len(calls) == 1
    assert calls[0] is report
    assert report.ok is True


def test_reporter_exception_does_not_escape_close(rp):
    def bad(report):
        raise RuntimeError("reporter failed")

    root = _open(rp, budget_s=1.0, reporter=bad)
    report, _ = _close(root)  # не бросает
    assert isinstance(report, _report_cls())


def test_reporter_exception_keeps_report_complete(rp):
    def bad(report):
        raise RuntimeError("reporter failed")

    root = _open(rp, budget_s=1.0, reporter=bad)
    report, _ = _close(root)
    assert report.complete is True


def test_reporter_exception_is_logged_once_at_warning_or_above(rp, caplog):
    def bad(report):
        raise RuntimeError("reporter failed")

    caplog.set_level(logging.DEBUG)
    root = _open(rp, budget_s=1.0, reporter=bad)
    _close(root)
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(loud) == 1


def test_root_report_contains_survivor_path_from_subtree(rp, release):
    root = _open(rp, budget_s=0.2)
    c = root.child("c")
    c.spawn(lambda ev: release.wait(3.0), name="w")
    report, _ = _close(root)
    assert f"{rp}/c/w" in report.survivors


def test_root_report_path_is_root_path(rp):
    root = _open(rp, budget_s=1.0)
    report, _ = _close(root)
    assert report.path == rp


# ======================================================================== unclosed_roots()


def _paths(entries):
    return [d["path"] for d in entries]


def test_unclosed_roots_lists_live_open_root(rp):
    root = _open(rp, budget_s=1.0)
    assert {"path": rp, "state": "open"} in _unclosed()
    assert root.closed is False  # корень жив до конца проверки


def test_unclosed_roots_dict_keys_are_exactly_path_and_state(rp):
    root = _open(rp, budget_s=1.0)
    entries = _unclosed()
    assert {"path": rp, "state": "open"} in entries
    assert all(set(d) == {"path", "state"} for d in entries)
    assert root is not None


def test_unclosed_roots_never_lists_child_scope(rp):
    root = _open(rp, budget_s=1.0)
    root.child("c")
    assert f"{rp}/c" not in _paths(_unclosed())
    assert rp in _paths(_unclosed())


def _create_and_drop(path):
    root = _open(path, budget_s=1.0)
    return weakref.ref(root)


def test_unclosed_roots_reports_dropped_root_as_abandoned(rp):
    ref = _create_and_drop(rp)
    gc.collect()
    assert {"path": rp, "state": "abandoned"} in _unclosed()
    assert ref() is None


def test_unclosed_roots_watch_does_not_keep_root_alive(rp):
    ref = _create_and_drop(rp)
    gc.collect()
    assert ref() is None


def _create_close_and_drop(path):
    root = _open(path, budget_s=1.0)
    _close(root)
    return weakref.ref(root)


def test_closed_root_is_not_listed_while_alive(rp):
    root = _open(rp, budget_s=1.0)
    _close(root)
    assert rp not in _paths(_unclosed())
    assert root.closed is True


def test_closed_root_is_not_listed_after_drop_and_gc(rp):
    ref = _create_close_and_drop(rp)
    gc.collect()
    assert ref() is None
    assert rp not in _paths(_unclosed())


def test_root_with_started_close_is_not_listed_during_close(rp):
    seen = {}
    root = _open(rp, budget_s=1.0)
    root.own(lambda: seen.setdefault("paths", _paths(_unclosed())), name="probe")
    _close(root)
    assert "paths" in seen
    assert rp not in seen["paths"]


def test_root_with_started_close_is_not_abandoned_after_drop(rp):
    gc.collect()
    root = _open(rp, budget_s=1.0)
    root.own(lambda: None, name="x")
    _close(root)
    ref = weakref.ref(root)
    del root
    gc.collect()
    assert ref() is None
    assert rp not in _paths(_unclosed())


# ======================================================================== прочее


def test_pickle_of_scope_raises_type_error_naming_path_and_pickle(rp):
    root = _open(rp, budget_s=1.0)
    with pytest.raises(TypeError) as exc:
        pickle.dumps(root)
    text = str(exc.value)
    assert rp in text
    assert "pickle" in text.lower()


def test_pickle_of_handle_raises_type_error_naming_path_and_pickle(rp):
    root = _open(rp, budget_s=1.0)
    handle = root.own(lambda: None, name="x")
    with pytest.raises(TypeError) as exc:
        pickle.dumps(handle)
    text = str(exc.value)
    assert f"{rp}/x" in text
    assert "pickle" in text.lower()


def _report_kwargs(**over):
    kw = dict(path="p", elapsed_s=0.1, survivors=(), killed=(), errors=())
    kw.update(over)
    return kw


@pytest.mark.parametrize("field", ["survivors", "killed", "errors"])
def test_closereport_none_sequence_raises_type_error_naming_field(field):
    with pytest.raises(TypeError) as exc:
        _report_cls()(**_report_kwargs(**{field: None}))
    assert field in str(exc.value)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "minus-inf"])
def test_closereport_non_finite_elapsed_raises_value_error_naming_field(bad):
    with pytest.raises(ValueError) as exc:
        _report_cls()(**_report_kwargs(elapsed_s=bad))
    assert "elapsed_s" in str(exc.value)


@pytest.mark.parametrize("field", ["survivors", "killed", "errors"])
def test_closereport_frozenset_in_place_of_sequence_raises_type_error(field):
    with pytest.raises(TypeError):
        _report_cls()(**_report_kwargs(**{field: frozenset({"a"})}))


@pytest.mark.parametrize("field", ["survivors", "killed", "errors"])
def test_closereport_set_in_place_of_sequence_raises_type_error(field):
    with pytest.raises(TypeError):
        _report_cls()(**_report_kwargs(**{field: {"a"}}))


ALLOWED_LIFETIME_IMPORTS = {
    "__future__",
    "collections",
    "collections.abc",
    "dataclasses",
    "itertools",
    "logging",
    "math",
    "threading",
    "time",
    "typing",
    "weakref",
}


def _forbidden_lifetime_imports(source):
    """Импорты вне литерального списка. Разрешён относительный `..interfaces` (level=2)."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad.extend(a.name for a in node.names if a.name not in ALLOWED_LIFETIME_IMPORTS)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if (node.module or "") not in ALLOWED_LIFETIME_IMPORTS:
                    bad.append(node.module or "")
            elif node.level == 2 and node.module == "interfaces":
                continue
            elif node.level == 2 and node.module is None and all(a.name == "interfaces" for a in node.names):
                continue
            else:
                bad.append("." * node.level + (node.module or ""))
    return bad


def test_lifetime_import_checker_flags_foreign_and_wrong_relative_imports():
    # контроль самого сторожа
    src = (
        "import os\n"
        "from json import dumps\n"
        "from .sibling import x\n"
        "from ..interfaces import CloseReport\n"
        "from ..mixins import y\n"
        "import threading\n"
    )
    assert _forbidden_lifetime_imports(src) == ["os", "json", ".sibling", "..mixins"]


def test_lifetime_py_imports_only_allowed_modules():
    path = Path(__file__).resolve().parent.parent / "core" / "lifetime.py"
    assert path.exists(), "core/lifetime.py ещё не создан"
    assert _forbidden_lifetime_imports(path.read_text(encoding="utf-8")) == []
