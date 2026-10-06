"""Независимые приёмочные тесты Task 0.3: ``Subscribers`` (event_module), строки S1-S15.

Написаны вслепую, ДО реализации, по plans/2026-10-03_lifecycle-owner-scope/task-0.3.md
(«Контракт реализации» и «Acceptance criteria и инъекции»). Ожидаемые значения —
литералы из спека, не вычисляются из кода под тестом.

Правила набора:
- ``Subscribers`` и ``open_scope`` берутся через публичные двери пакетов, импорт — внутри
  хелперов: пока реализации нет, собирается весь файл, а каждый тест падает сам
  (``AttributeError: ... has no attribute 'Subscribers'``), а не одной ошибкой сбора;
- наблюдаем эффект через публичное API (``add``, ``emit``, ``errors``, ``len``, отчёты
  reporter'а, ``live()``), а не через внутренние имена;
- каждый вызов, который может зависнуть, идёт в daemon-потоке с join(timeout);
  зависание = assert с текстом, а не таймаут прогона;
- одна строка спека — один тест; id строки в имени (``test_s5_...``).
"""

from __future__ import annotations

import gc
import importlib
import inspect
import re
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import paused_gc

EVT = "multiprocess_framework.modules.event_module"
BM = "multiprocess_framework.modules.base_manager"
BM_IFACE = BM + ".interfaces"

SPEC_COMMIT = "fb9ce56b5"
REPO_ROOT = Path(__file__).resolve().parents[4]
FROZEN_EVENT_MODULE_FILES = (
    "multiprocess_framework/modules/event_module/event_bus.py",
    "multiprocess_framework/modules/event_module/interfaces.py",
)
EVENT_BUS_TEST = "multiprocess_framework/modules/event_module/tests/test_event_bus.py"


# ======================================================================== двери и инфраструктура


def _subscribers_cls():
    return importlib.import_module(EVT).Subscribers


def _pub(name="pub"):
    return _subscribers_cls()(name)


def _open_scope(path, **kw):
    return importlib.import_module(BM).open_scope(path, **kw)


def _scope_closed_error():
    return importlib.import_module(BM_IFACE).ScopeClosedError


def _run(fn, *args, _timeout=10.0, _what="вызов", **kwargs):
    """Выполнить fn в daemon-потоке с join(timeout); вернуть результат, исключение — в поток теста."""
    box = {}

    def runner():
        try:
            box["r"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["e"] = exc

    th = threading.Thread(target=runner, daemon=True, name="t03-helper")
    th.start()
    th.join(_timeout)
    assert not th.is_alive(), f"{_what} завис дольше {_timeout} с"
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _bounded(body, timeout=10.0):
    """Тело теста целиком в daemon-потоке с дедлайном."""
    return _run(body, _timeout=timeout, _what="тело теста")


def _cb(calls, tag):
    """Подписчик: пишет tag в calls, принимает любые аргументы рассылки."""

    def cb(*args, **kwargs):
        calls.append(tag)

    return cb


@pytest.fixture
def env():
    """Фикстура спека: ``got``, ``root`` (budget 1.0, reporter=got.append), ``calls``; ``extra`` — корни на закрытие."""
    got = []
    root = _open_scope("root", budget_s=1.0, reporter=got.append)
    ns = SimpleNamespace(got=got, root=root, calls=[], extra=[])
    yield ns
    for scope in (ns.root, *ns.extra):
        _run(scope.close, _what="close() в teardown")


def _g(got):
    """``G`` из спека: пары (путь, счётчик) по отчётам reporter'а."""
    return [(r.path, r.emits_after_close) for r in got]


# ======================================================================== S1-S4: порядок, реентрантность


def test_s1_add_returns_subscription_handle(env):
    def body():
        pub = _pub()
        h = pub.add(_cb(env.calls, "A"), owner=env.root)
        assert h.kind == "subscription"
        assert re.fullmatch(r"root/pub#\d+", h.path), h.path
        assert len(pub) == 1

    _bounded(body)


def test_s2_emit_delivers_in_add_order(env):
    def body():
        pub = _pub()
        for tag in ("A", "B", "C"):
            pub.add(_cb(env.calls, tag), owner=env.root)
        assert pub.emit(1) == 3
        assert env.calls == ["A", "B", "C"]

    _bounded(body)


def test_s3_reentrant_close_of_handle_skips_closed_in_rest_of_emit(env):
    def body():
        pub = _pub()
        box = {}

        def a(*args, **kwargs):
            env.calls.append("A")
            box["hB"].close()

        pub.add(a, owner=env.root)
        box["hB"] = pub.add(_cb(env.calls, "B"), owner=env.root)
        pub.add(_cb(env.calls, "C"), owner=env.root)

        assert pub.emit() == 2
        assert env.calls == ["A", "C"]
        assert pub.emits_after_close == 0  # h.close() при открытом владельце — без счёта

        assert pub.emit() == 2
        assert env.calls == ["A", "C", "A", "C"]
        assert pub.emits_after_close == 0
        assert len(pub) == 2

    _bounded(body)


def test_s4_subscription_added_inside_emit_misses_current_emit(env):
    def body():
        pub = _pub()
        state = {"added": False}

        def a(*args, **kwargs):
            env.calls.append("A")
            if not state["added"]:
                state["added"] = True
                pub.add(_cb(env.calls, "D"), owner=env.root)

        pub.add(a, owner=env.root)
        pub.add(_cb(env.calls, "B"), owner=env.root)
        pub.add(_cb(env.calls, "C"), owner=env.root)

        assert pub.emit() == 3
        assert env.calls == ["A", "B", "C"]

        env.calls.clear()
        assert pub.emit() == 4
        assert env.calls == ["A", "B", "C", "D"]

    _bounded(body)


# ======================================================================== S5: исключения подписчиков


def test_s5_subscriber_exception_isolated_counted_capped_at_20(env):
    def body():
        pub = _pub()
        pub.add(_cb(env.calls, "A"), owner=env.root)

        def boom(*args, **kwargs):
            raise ValueError("boom")

        hB = pub.add(boom, owner=env.root)
        pub.add(_cb(env.calls, "C"), owner=env.root)

        assert pub.emit() == 2
        assert env.calls == ["A", "C"]
        assert pub.errors == ((hB.path, "ValueError: boom"),)
        assert pub.error_count == 1

        for _ in range(24):
            pub.emit()
        assert len(pub.errors) == 20
        assert pub.errors == ((hB.path, "ValueError: boom"),) * 20
        assert pub.error_count == 25

    _bounded(body)


# ======================================================================== S6-S7: закрытый владелец в рассылке


def test_s6_closed_child_owner_counted_in_root_report(env):
    def body():
        pub = _pub()
        tab = env.root.child("tab")

        def a(*args, **kwargs):
            env.calls.append("A")
            tab.close()

        pub.add(a, owner=env.root)
        pub.add(_cb(env.calls, "B"), owner=tab)

        assert pub.emit() == 1
        assert env.calls == ["A"]
        assert pub.emits_after_close == 1
        assert env.root.close().emits_after_close == 1
        assert _g(env.got) == [("root/tab", 0), ("root", 1)]

    _bounded(body)


def test_s7_owner_closed_inside_emit_one_note_per_owner(env):
    def body():
        pub = _pub()
        x = _open_scope("x", budget_s=1.0, reporter=env.got.append)
        env.extra.append(x)

        def a(*args, **kwargs):
            env.calls.append("A")
            x.close()

        pub.add(a, owner=x)
        pub.add(_cb(env.calls, "B"), owner=x)
        pub.add(_cb(env.calls, "C"), owner=x)

        assert pub.emit() == 1
        assert env.calls == ["A"]
        assert pub.emits_after_close == 2
        assert _g(env.got) == [("x", 0), ("x", 2)]

    _bounded(body)


# ======================================================================== S8-S9: отказы add


def test_s8_add_rejects_missing_owner_none_owner_and_non_callable(env):
    def body():
        pub = _pub()
        a = _cb(env.calls, "A")

        with pytest.raises(TypeError):
            pub.add(a)

        with pytest.raises(TypeError) as none_owner:
            pub.add(a, owner=None)
        assert "owner" in str(none_owner.value)

        with pytest.raises(TypeError):
            pub.add(1, owner=env.root)

        assert len(pub) == 0

    _bounded(body)


def test_s9_add_to_closed_owner_raises_and_is_not_listed(env):
    def body():
        pub = _pub()
        env.root.close()

        with pytest.raises(_scope_closed_error()):
            pub.add(_cb(env.calls, "A"), owner=env.root)

        assert len(pub) == 0
        assert pub.emit() == 0
        assert env.calls == []

    _bounded(body)


# ======================================================================== S10-S12: сборка мусора


def test_s10_handle_does_not_keep_publisher_alive(env):
    def body():
        with paused_gc():
            pub = _pub()
            h = pub.add(_cb(env.calls, "A"), owner=env.root)
            r = weakref.ref(pub)
            del pub
            assert r() is None, "издатель жив без gc.collect(): ручка/запись держит его сильно"
            assert h.close().ok is True

    _bounded(body)


def test_s11_release_drops_subscriber_so_presenter_dies_without_gc(env):
    class Presenter:
        def __init__(self, pub):
            self.pub = pub  # презентер держит издателя, издатель держит его метод

        def on_event(self, *args, **kwargs):
            pass

    def body():
        with paused_gc():
            p = env.root.child("p")
            pub = _pub()
            presenter = Presenter(pub)
            h = pub.add(presenter.on_event, owner=p)
            ref = weakref.ref(presenter)
            del presenter, pub, h
            # контроль: пока владелец открыт, запись держит подписчика — тест различает
            assert ref() is not None, "контроль: презентер умер до p.close() (подписчик не удерживается записью)"
            p.close()
            assert ref() is None, "презентер жив после p.close(): _Release не убрал подписку из издателя"

    _bounded(body)


def test_s12_collected_owner_gets_no_delivery_and_is_counted(env):
    def body():
        pub = _pub()
        o = _open_scope("o", budget_s=1.0)
        h = pub.add(_cb(env.calls, "A"), owner=o)
        ro = weakref.ref(o)
        del o, h
        gc.collect()
        assert ro() is None, "владелец не собран: что-то держит его сильно"

        assert pub.emit() == 0
        assert env.calls == []
        assert pub.emits_after_close == 1
        assert len(pub) == 0

    _bounded(body)


# ======================================================================== S13: сигнатура


def test_s13_owner_is_keyword_only_required_and_annotated_iscope():
    Subscribers = _subscribers_cls()
    IScope = importlib.import_module(BM_IFACE).IScope

    p = inspect.signature(Subscribers.add).parameters["owner"]

    assert p.kind is inspect.Parameter.KEYWORD_ONLY
    assert p.default is inspect.Parameter.empty
    assert p.annotation in ("IScope", IScope)


# ======================================================================== S14: cb вне лока (конкурентность)


def test_s14_subscriber_runs_outside_lock_add_and_emit_do_not_wait_for_it(env):
    pub = _pub()
    a_in = threading.Event()
    e = threading.Event()
    state = {"first": True, "e_wait": None}
    gate = threading.Lock()
    errors = []

    def a(*args, **kwargs):
        with gate:
            first = state["first"]
            state["first"] = False
        if first:
            a_in.set()
            state["e_wait"] = e.wait(2.0)

    def noop(*args, **kwargs):
        pass

    _run(pub.add, a, owner=env.root, _what="add A")
    _run(pub.add, noop, owner=env.root, _what="add B")
    _run(pub.add, noop, owner=env.root, _what="add C")

    def emitter():
        try:
            for _ in range(500):
                pub.emit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def adder():
        try:
            h = pub.add(noop, owner=env.root)
            e.set()  # сразу после возврата из первого add
            h.close()
            for _ in range(499):
                h = pub.add(noop, owner=env.root)
                h.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    emitters = [threading.Thread(target=emitter, daemon=True, name=f"t03-emit{i}") for i in range(4)]
    adder_thread = threading.Thread(target=adder, daemon=True, name="t03-adder")
    try:
        for th in emitters:
            th.start()
        assert a_in.wait(5.0), "ни один emit не вошёл в первый вызов A за 5 с"
        adder_thread.start()  # стартует только после входа A в подписчика

        end = time.monotonic() + 10.0
        for th in (*emitters, adder_thread):
            th.join(max(0.0, end - time.monotonic()))
        alive = [th.name for th in (*emitters, adder_thread) if th.is_alive()]
    finally:
        e.set()  # отпустить A при любом исходе

    assert alive == [], f"потоки не вышли за 10 с: {alive}"
    assert errors == []
    assert state["e_wait"] is True, "add не вернулся, пока A ждал: cb вызывается под локом издателя"
    assert len(pub) == 3


# ======================================================================== S15: EventBus и interfaces.py не тронуты


def _git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_s15_event_bus_and_event_interfaces_untouched_since_spec_commit():
    committed = _git("diff", "--exit-code", SPEC_COMMIT, "HEAD", "--", *FROZEN_EVENT_MODULE_FILES)
    assert committed.returncode == 0, (
        f"event_bus.py/interfaces.py изменены коммитами после спека:\n{committed.stdout}{committed.stderr}"
    )

    # то же против рабочего дерева: ловит и незакоммиченную правку
    worktree = _git("diff", "--exit-code", SPEC_COMMIT, "--", *FROZEN_EVENT_MODULE_FILES)
    assert worktree.returncode == 0, (
        f"event_bus.py/interfaces.py изменены в рабочем дереве:\n{worktree.stdout}{worktree.stderr}"
    )


def test_s15_test_event_bus_unedited_and_green():
    diff = _git("diff", "--exit-code", SPEC_COMMIT, "--", EVENT_BUS_TEST)
    assert diff.returncode == 0, f"test_event_bus.py правился после спека:\n{diff.stdout}{diff.stderr}"

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", EVENT_BUS_TEST, "-q", "--tb=line", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"test_event_bus.py не зелёный:\n{proc.stdout[-2000:]}{proc.stderr[-1000:]}"
