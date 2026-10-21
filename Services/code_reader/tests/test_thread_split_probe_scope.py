# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты C-13 (3): потоки пробы ``thread_split_probe`` живут под областью жизни.

Написаны ДО правки, по брифу, без чтения будущей реализации.

Контракт:
  * страж G6 (правило R1) не находит ``threading.Thread`` в ``Services/code_reader/tools/thread_split_probe.py``;
  * поведение пробы не меняется: исходные значения узлов читаются до записи, при ЛЮБОМ выходе
    (в т.ч. Ctrl+C) возврат узлов и ``close`` всё равно выполняются;
  * рабочие потоки пробы принадлежат области: имя потока содержит ``/`` (путь области), и после
    возврата ``main()`` ни один из них не жив.

Проба запускается через публичный ``main()`` с ``--fake``; наблюдается журнал вызовов фейка
(``FakeNodeApi.calls``), а не внутренние методы пробы. Ctrl+C моделируется асинхронным
``KeyboardInterrupt`` в потоке, исполняющем ``main()`` (настоящий Ctrl+C на Windows нестабилен).
Всё, что может зависнуть, идёт в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import ctypes
import io
import sys
import threading
import time
from pathlib import Path

import pytest

from Services.code_reader.tests.test_sdk_trigger import FakeNodeApi

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE_REL = "Services/code_reader/tools/thread_split_probe.py"
JOIN_DEADLINE_S = 30.0

# Журнал записей узлов на фейке (начальные значения прибора: Mode=0, Source=0, Period=300).
# Запись: Mode=On, Source=SelfTrigger, Period=40; возврат в обратном порядке с исходными значениями.
EXPECTED_SET_CALLS = [
    ("set_enum_str", "TriggerMode", "On"),
    ("set_enum_str", "TriggerSource", "SelfTrigger"),
    ("set_int", "TriggerSelfTriggerPeriod", 40),
    ("set_int", "TriggerSelfTriggerPeriod", 300),
    ("set_enum", "TriggerSource", 0),
    ("set_enum", "TriggerMode", 0),
]
ORIGINAL_VALUES = {"TriggerMode": 0, "TriggerSource": 0, "TriggerSelfTriggerPeriod": 300}
LIFECYCLE_METHODS = ("open", "start_grabbing", "get_frame", "stop_grabbing", "close")


# --------------------------------------------------------------------------
# Харнесс: прогон main() в daemon-потоке с наблюдением за фейком
# --------------------------------------------------------------------------


class Run:
    """Результат прогона: код возврата, исключение, вывод, фейк, потоки, исполнявшие вызовы."""

    def __init__(self) -> None:
        self.rc: int | None = None
        self.exc: BaseException | None = None
        self.finished = False
        self.elapsed = 0.0
        self.output = ""
        self.fakes: list[FakeNodeApi] = []
        self.records: list[tuple[str, threading.Thread]] = []  # (метод, поток), порядок вызова
        self.runner: threading.Thread | None = None

    @property
    def fake(self) -> FakeNodeApi:
        assert len(self.fakes) == 1, f"ожидался один фейк, создано {len(self.fakes)}"
        return self.fakes[0]

    def set_calls(self) -> list[tuple]:
        return [c for c in self.fake.calls if c[0].startswith("set_")]

    def threads_of(self, method: str) -> list[threading.Thread]:
        return [t for m, t in list(self.records) if m == method]


def _install_fake_observers(monkeypatch: pytest.MonkeyPatch, run: Run, on_call=None) -> None:
    """Перехват конструктора и публичных методов жизненного цикла ``FakeNodeApi`` (класс из tests/)."""
    original_init = FakeNodeApi.__init__

    def init(self, *a, **kw):
        original_init(self, *a, **kw)
        run.fakes.append(self)

    monkeypatch.setattr(FakeNodeApi, "__init__", init)

    def wrap(name: str):
        original = getattr(FakeNodeApi, name)

        def method(self, *a, **kw):
            run.records.append((name, threading.current_thread()))
            if on_call is not None:
                on_call(name)
            return original(self, *a, **kw)

        monkeypatch.setattr(FakeNodeApi, name, method)

    for name in LIFECYCLE_METHODS:
        wrap(name)


def _inject_keyboard_interrupt(thread: threading.Thread) -> None:
    """Асинхронный KeyboardInterrupt в поток (модель Ctrl+C: приходит туда, где ждёт main())."""
    assert thread.ident is not None
    n = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident), ctypes.py_object(KeyboardInterrupt))
    assert n == 1, f"PyThreadState_SetAsyncExc вернул {n}"


def run_probe(monkeypatch: pytest.MonkeyPatch, argv: list[str], *, interrupt_on_first_frame: bool = False) -> Run:
    """Запустить ``thread_split_probe.main()`` в daemon-потоке и дождаться его (дедлайн JOIN_DEADLINE_S)."""
    from Services.code_reader.tools import thread_split_probe

    run = Run()
    state = {"fired": False}

    def on_call(name: str) -> None:
        if interrupt_on_first_frame and name == "get_frame" and not state["fired"]:
            state["fired"] = True
            assert run.runner is not None
            _inject_keyboard_interrupt(run.runner)

    _install_fake_observers(monkeypatch, run, on_call if interrupt_on_first_frame else None)
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "argv", ["thread_split_probe.py", "--fake", *argv])

    def runner() -> None:
        start = time.perf_counter()
        try:
            run.rc = thread_split_probe.main()
        except BaseException as exc:  # noqa: BLE001 -- KeyboardInterrupt тоже наблюдаем
            run.exc = exc
        finally:
            run.elapsed = time.perf_counter() - start
            run.finished = True

    t = threading.Thread(target=runner, name="test-probe-runner", daemon=True)
    run.runner = t
    t.start()
    t.join(JOIN_DEADLINE_S)
    out.flush()
    run.output = out.buffer.getvalue().decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    assert run.finished, f"проба не вернулась за {JOIN_DEADLINE_S} с (вывод):\n{run.output[-3000:]}"
    if interrupt_on_first_frame:
        assert state["fired"], "get_frame не вызывался -- KeyboardInterrupt не был послан"
    return run


def _assert_restored_and_closed(run: Run) -> None:
    assert run.set_calls() == EXPECTED_SET_CALLS, run.output[-3000:]
    assert run.fake.values[run.fake.entries[0].handle] == ORIGINAL_VALUES
    assert run.fake.count("close") == 1
    assert run.fake.calls[-1] == ("close",)


def _first_index(calls: list[tuple], prefix: str, node: str) -> int:
    return next(i for i, c in enumerate(calls) if c[0].startswith(prefix) and c[1] == node)


# --------------------------------------------------------------------------
# A1. Страж G6
# --------------------------------------------------------------------------


def test_a1_g6_reports_nothing_for_probe_path():
    from scripts.lifecycle_guards.g6 import check_g6

    mine = [(f.rule, f.line, f.message) for f in check_g6(REPO_ROOT) if f.path == PROBE_REL]
    assert mine == []


# --------------------------------------------------------------------------
# A2 / A3. Поведение сохранено: split и same
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["split", "same"])
def test_a2_a3_run_restores_every_written_node_and_closes(monkeypatch, mode):
    run = run_probe(monkeypatch, ["--mode", mode, "--seconds", "0.3"])
    assert run.exc is None
    assert run.rc == 0, run.output[-3000:]
    assert "ОШИБКА в потоке" not in run.output
    _assert_restored_and_closed(run)


@pytest.mark.parametrize("mode", ["split", "same"])
def test_a2_a3_originals_are_read_before_each_node_is_written(monkeypatch, mode):
    run = run_probe(monkeypatch, ["--mode", mode, "--seconds", "0.2"])
    calls = run.fake.calls
    for node in ORIGINAL_VALUES:
        assert _first_index(calls, "get_", node) < _first_index(calls, "set_", node), node


# --------------------------------------------------------------------------
# A4. Прерывание фазы захвата: возврат и close всё равно происходят
# --------------------------------------------------------------------------


def test_a4_interrupt_during_capture_still_restores_and_closes(monkeypatch):
    run = run_probe(monkeypatch, ["--mode", "split", "--seconds", "20"], interrupt_on_first_frame=True)
    # reachability: захват реально начался, а прерывание его реально оборвало (20 с заказано)
    assert len(run.threads_of("get_frame")) >= 1
    assert run.elapsed < 15.0, f"захват не оборван, прошло {run.elapsed:.1f} с"
    # проба вернулась с кодом Ctrl+C либо пробросила KeyboardInterrupt
    assert run.rc == 130 or isinstance(run.exc, KeyboardInterrupt), (run.rc, run.exc)
    _assert_restored_and_closed(run)


# --------------------------------------------------------------------------
# A5. После возврата ни один рабочий поток пробы не жив
# --------------------------------------------------------------------------


def test_a5_no_probe_worker_thread_alive_after_split_run(monkeypatch):
    before = set(threading.enumerate())
    run = run_probe(monkeypatch, ["--mode", "split", "--seconds", "0.3"])
    assert run.rc == 0, run.output[-3000:]
    runner = run.runner
    workers = {
        t
        for method in LIFECYCLE_METHODS
        for t in run.threads_of(method)
        if t is not runner and t is not threading.main_thread()
    }
    # reachability: рабочие потоки существовали и исполняли вызовы (иначе отсутствие ничего не доказывает)
    assert len(workers) >= 1, "вызовы фейка не шли из рабочих потоков -- проверка отсутствия пуста"
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline and any(w.is_alive() for w in workers):
        time.sleep(0.02)
    assert [w.name for w in workers if w.is_alive()] == []
    leaked = [t.name for t in set(threading.enumerate()) - before if t is not runner and t.is_alive()]
    assert leaked == []


# --------------------------------------------------------------------------
# A6. Рабочие потоки принадлежат области: имя содержит '/'
# --------------------------------------------------------------------------


def test_a6_split_worker_threads_are_scope_owned(monkeypatch):
    run = run_probe(monkeypatch, ["--mode", "split", "--seconds", "0.3"])
    assert run.rc == 0, run.output[-3000:]
    seen = {m: sorted({t.name for t in run.threads_of(m)}) for m in LIFECYCLE_METHODS}
    # reachability: каждый метод жизненного цикла реально вызван (фаза A: open/start, фаза B: кадры/stop/close)
    assert all(seen[m] for m in LIFECYCLE_METHODS), seen
    assert {m: [n for n in names if "/" not in n] for m, names in seen.items()} == {m: [] for m in LIFECYCLE_METHODS}


# --------------------------------------------------------------------------
# H. Гарантии правки, которые слепые тесты не держали (hazard-тесты автора)
# --------------------------------------------------------------------------

PROBE_ROOT = "code_reader.thread_split_probe"


class _CaptureDied(BaseException):
    """Не ``Exception``: ``timed()`` её не глотает, поэтому поток захвата падает до своего возврата узлов."""


def test_h1_probe_scope_is_closed_after_main_returns(monkeypatch):
    from multiprocess_framework.modules.base_manager import unclosed_roots

    seen_during: list[str] = []
    original_start = FakeNodeApi.start_grabbing

    def start_grabbing(self, h):
        seen_during.extend(r["path"] for r in unclosed_roots())
        return original_start(self, h)

    monkeypatch.setattr(FakeNodeApi, "start_grabbing", start_grabbing)
    run = run_probe(monkeypatch, ["--mode", "split", "--seconds", "0.2"])
    assert run.rc == 0, run.output[-3000:]
    # reachability: во время прогона корень области существовал (иначе отсутствие после него ничего не доказывает)
    assert PROBE_ROOT in seen_during, seen_during
    assert [r["path"] for r in unclosed_roots() if r["path"] == PROBE_ROOT] == []


def test_h2_fallback_restore_when_capture_thread_dies_before_restore(monkeypatch):
    original_stop = FakeNodeApi.stop_grabbing
    state = {"died": False}

    def stop_grabbing(self, h):
        if not state["died"]:
            state["died"] = True
            raise _CaptureDied("поток захвата погиб до собственного возврата узлов")
        return original_stop(self, h)

    monkeypatch.setattr(FakeNodeApi, "stop_grabbing", stop_grabbing)
    run = run_probe(monkeypatch, ["--mode", "split", "--seconds", "0.2"])
    # reachability: сбой реально случился в потоке захвата, до его возврата узлов
    assert state["died"] is True
    assert "ОШИБКА в потоке B-capture" in run.output, run.output[-3000:]
    assert run.rc == 1, (run.rc, run.exc)
    # аварийный возврат в главном потоке: запись 3 узла, затем возврат в обратном порядке и close
    _assert_restored_and_closed(run)


def test_h3_keyboard_interrupt_inside_scope_close_still_restores_and_closes(monkeypatch):
    from Services.code_reader.tools import thread_split_probe

    original_stop = FakeNodeApi.stop_grabbing
    state = {"died": False, "interrupted": False}

    def stop_grabbing(self, h):
        if not state["died"]:
            state["died"] = True
            raise _CaptureDied("поток захвата погиб до собственного возврата узлов")
        return original_stop(self, h)

    monkeypatch.setattr(FakeNodeApi, "stop_grabbing", stop_grabbing)

    class InterruptedScope:
        """Настоящая область; Ctrl+C, ждавший в close, приходит по возврату из него."""

        def __init__(self, real) -> None:
            self.real = real

        def spawn(self, *a, **kw):
            return self.real.spawn(*a, **kw)

        def close(self, *a, **kw):
            self.real.close(*a, **kw)
            state["interrupted"] = True
            raise KeyboardInterrupt

    real_open_scope = thread_split_probe.open_scope
    monkeypatch.setattr(thread_split_probe, "open_scope", lambda *a, **kw: InterruptedScope(real_open_scope(*a, **kw)))
    run = run_probe(monkeypatch, ["--mode", "split", "--seconds", "0.2"])
    # reachability: поток захвата погиб, а Ctrl+C в close реально пришёл
    assert state["died"] is True
    assert state["interrupted"] is True
    assert run.rc == 1, (run.rc, run.exc)
    # аварийный возврат и close выполнены, хотя finish() прервали внутри scope.close()
    _assert_restored_and_closed(run)
