# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.9a: контракт ``KeyedExecutor`` (REDS R1-R6, R11, R12, R12b).

Написаны независимым тестером ТОЛЬКО по публичному контракту (D1 брифа
``plans/lifecycle-stop-ownership/tasks/T1.9a.md`` и раздел REDS); устройство
исполнителя тестеру не показывалось и здесь не предполагается.

Ожидание до реализации: каждый тест КРАСНЫЙ (``ModuleNotFoundError`` на
``worker_module.keyed_executor``). Импорт нового имени сделан в фабрике-фикстуре,
а не на уровне модуля, чтобы каждый тест докладывал свой красный, а не один
ошибкой сбора на весь файл.

Правила стенда: каждый вызов, который может ждать, идёт в daemon-потоке с дедлайном
``join`` (зависание = упавший assert, а не зависший прогон); ожидания — литералы;
часы — ``time.perf_counter()``; метки времени берутся изнутри самих действий;
исполнитель строится с настоящим ``WorkerManager``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.base_manager.interfaces import Stoppable
from multiprocess_framework.modules.worker_module import WorkerManager

A = frozenset({"a"})
B = frozenset({"b"})
AB = frozenset({"a", "b"})

SYSTEM_STOPPING = {"success": False, "error": "system_stopping"}
EXECUTOR_BUSY = {"success": False, "error": "executor_busy"}


# ---------------------------------------------------------------------------
# Стенд
# ---------------------------------------------------------------------------


def run_bounded(fn: Callable[[], Any], timeout: float = 5.0) -> tuple[Any, int]:
    """Выполнить ``fn`` в daemon-потоке; вернуть ``(результат, ident потока)``.

    Не уложилась в ``timeout`` — провал теста, не зависание набора.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        box["ident"] = threading.get_ident()
        try:
            box["ret"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в потоке теста
            box["exc"] = exc

    t = threading.Thread(target=target, name="caller-probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"вызов не вернулся за {timeout} с (зависание)")
    if "exc" in box:
        raise box["exc"]
    return box.get("ret"), box["ident"]


class Rec:
    """Метки времени и потоки изнутри действий (``perf_counter``)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.start: dict[str, float] = {}
        self.end: dict[str, float] = {}
        self.thread: dict[str, int] = {}
        self.started: dict[str, threading.Event] = {}

    def started_event(self, label: str) -> threading.Event:
        with self._lock:
            return self.started.setdefault(label, threading.Event())

    def action(self, label: str, duration: float, result: Any = None) -> Callable[[], Any]:
        ev = self.started_event(label)

        def run() -> Any:
            with self._lock:
                self.start[label] = time.perf_counter()
                self.thread[label] = threading.get_ident()
            ev.set()
            if duration > 0:
                threading.Event().wait(duration)
            with self._lock:
                self.end[label] = time.perf_counter()
            return label if result is None else result

        return run


class Replies:
    """Приёмник ``reply``: считает вызовы, помнит полезную нагрузку и поток."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.payloads: dict[str, list[Any]] = {}
        self.threads: dict[str, list[int]] = {}
        self._events: dict[str, threading.Event] = {}

    def _event(self, label: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault(label, threading.Event())

    def reply_for(self, label: str) -> Callable[[Any], None]:
        ev = self._event(label)

        def reply(payload: Any) -> None:
            with self._lock:
                self.payloads.setdefault(label, []).append(payload)
                self.threads.setdefault(label, []).append(threading.get_ident())
            ev.set()

        return reply

    def wait(self, labels: list[str], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        for label in labels:
            if not self._event(label).wait(max(0.0, deadline - time.monotonic())):
                return False
        return True

    def count(self, label: str) -> int:
        with self._lock:
            return len(self.payloads.get(label, []))

    def only(self, label: str) -> Any:
        with self._lock:
            return list(self.payloads.get(label, []))


@pytest.fixture
def make_executor():
    """Фабрика ``KeyedExecutor`` с настоящим ``WorkerManager`` и уборкой."""
    created: list[tuple[Any, WorkerManager]] = []

    def factory(name: str = "t", **kwargs: Any) -> Any:
        # Импорт здесь: до реализации красный у каждого теста отдельно.
        from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor

        wm = WorkerManager(f"wm-{name}-{len(created)}")
        wm.initialize()
        ex = KeyedExecutor(name, worker_manager=wm, **kwargs)
        created.append((ex, wm))
        return ex

    yield factory

    for ex, wm in created:
        try:
            ex.request_stop()
            ex.join_until(time.monotonic() + 2.0)
        except Exception:  # noqa: BLE001 — уборка не должна маскировать провал теста
            pass
        try:
            wm.shutdown()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# R1-R3: порядок и параллельность по ключам
# ---------------------------------------------------------------------------


def test_overlapping_keys_run_in_submit_order(make_executor):
    """R1: {a}, {a,b}, {b} по 0,2 с — завершаются в порядке подачи; None после них — не раньше конца всех."""
    ex = make_executor("r1")
    rec, rep = Rec(), Replies()

    def submit_all() -> None:
        for label, key in (("A", A), ("B", AB), ("C", B), ("D", None)):
            ex.submit(rec.action(label, 0.2), key, rep.reply_for(label))

    run_bounded(submit_all)
    assert rep.wait(["A", "B", "C", "D"], 5.0), "не все ответы пришли за 5 с"

    assert rec.end["A"] <= rec.end["B"] <= rec.end["C"], f"порядок завершения нарушен: {rec.end}"
    assert rec.start["B"] >= rec.end["A"], "{a,b} началась до конца {a}"
    assert rec.start["C"] >= rec.end["B"], "{b} началась до конца {a,b}"
    assert rec.start["D"] >= max(rec.end["A"], rec.end["B"], rec.end["C"]), (
        "None (все ключи) началась до конца ранее поданных"
    )


def test_disjoint_keys_run_in_parallel(make_executor):
    """R2: {a} и {b} по 0,5 с при serial=False — обе кончились за <= 0,8 с."""
    ex = make_executor("r2", serial=False)
    rec, rep = Rec(), Replies()

    t0 = time.perf_counter()

    def submit_all() -> None:
        ex.submit(rec.action("a", 0.5), A, rep.reply_for("a"))
        ex.submit(rec.action("b", 0.5), B, rep.reply_for("b"))

    run_bounded(submit_all)
    assert rep.wait(["a", "b"], 5.0), "не все ответы пришли за 5 с"

    total = max(rec.end["a"], rec.end["b"]) - t0
    assert total <= 0.8, f"непересекающиеся ключи шли не параллельно: {total:.3f} с (> 0.8)"


def test_blocked_head_does_not_hold_disjoint_key(make_executor):
    """R2b: {a} 0,5 с, {a} 0,1 с, {b} 0,1 с — {b} кончилась <= 0,3 с от подачи первой."""
    ex = make_executor("r2b", serial=False)
    rec, rep = Rec(), Replies()

    t0 = time.perf_counter()

    def submit_all() -> None:
        ex.submit(rec.action("a1", 0.5), A, rep.reply_for("a1"))
        ex.submit(rec.action("a2", 0.1), A, rep.reply_for("a2"))
        ex.submit(rec.action("b", 0.1), B, rep.reply_for("b"))

    run_bounded(submit_all)
    assert rep.wait(["a1", "a2", "b"], 5.0), "не все ответы пришли за 5 с"

    waited = rec.end["b"] - t0
    assert waited <= 0.3, f"{{b}} застряла за ждущей {{a}}: кончилась через {waited:.3f} с (> 0.3)"


def test_serial_mode_orders_disjoint_keys(make_executor):
    """R3: serial=True — {a} и {b} по 0,5 с идут друг за другом: start(op2) >= end(op1), всего >= 0,95 с."""
    ex = make_executor("r3", serial=True)
    rec, rep = Rec(), Replies()

    t0 = time.perf_counter()

    def submit_all() -> None:
        ex.submit(rec.action("op1", 0.5), A, rep.reply_for("op1"))
        ex.submit(rec.action("op2", 0.5), B, rep.reply_for("op2"))

    run_bounded(submit_all)
    assert rep.wait(["op1", "op2"], 5.0), "не все ответы пришли за 5 с"

    assert rec.start["op2"] >= rec.end["op1"], "serial=True: вторая началась до конца первой"
    total = rec.end["op2"] - t0
    assert total >= 0.95, f"serial=True: общее время {total:.3f} с (< 0.95) — операции перекрылись"


# ---------------------------------------------------------------------------
# R4: reply ровно один раз на каждой ветке
# ---------------------------------------------------------------------------


def test_reply_called_exactly_once_on_every_branch(make_executor):
    """R4: результат, исключение, отказ (system_stopping и executor_busy) — по одному reply в каждом случае."""
    verdicts: list[str] = []

    def settle() -> None:
        time.sleep(0.25)  # дать лишнему второму reply шанс проявиться

    def check(point: str, rep: Replies, label: str, expected: Any) -> None:
        got = rep.only(label)
        if got != [expected]:
            verdicts.append(
                f"{point}: reply вызывался {len(got)} раз(а), полезные нагрузки {got!r}, ожидали ровно [{expected!r}]"
            )

    # 1. результат
    ex = make_executor("r4-result")
    rep = Replies()
    run_bounded(lambda: ex.submit(lambda: {"v": 1}, A, rep.reply_for("res")))
    assert rep.wait(["res"], 5.0), "точка результат: reply не вызван за 5 с"
    settle()
    check("результат", rep, "res", {"v": 1})

    # 2. исключение
    def boom() -> Any:
        raise ValueError("x")

    ex = make_executor("r4-exc")
    rep = Replies()
    run_bounded(lambda: ex.submit(boom, A, rep.reply_for("exc")))
    assert rep.wait(["exc"], 5.0), "точка исключение: reply не вызван за 5 с"
    settle()
    check("исключение", rep, "exc", {"success": False, "error": "ValueError: x"})

    # 3. отказ system_stopping (после request_stop)
    ex = make_executor("r4-stopped")
    rep = Replies()
    ex.request_stop()
    run_bounded(lambda: ex.submit(lambda: "never", A, rep.reply_for("stp")))
    assert rep.wait(["stp"], 5.0), "точка system_stopping: reply не вызван за 5 с"
    settle()
    check("system_stopping", rep, "stp", SYSTEM_STOPPING)

    # 4. отказ executor_busy (max_pending=1: идёт одна, одна в очереди, третья отвергнута)
    ex = make_executor("r4-busy", max_pending=1)
    rec, rep = Rec(), Replies()
    release = threading.Event()
    try:
        run_bounded(
            lambda: ex.submit(lambda: (rec.started_event("blk").set(), release.wait(3.0))[1], A, rep.reply_for("blk"))
        )
        assert rec.started_event("blk").wait(3.0), "блокирующая операция не началась"
        run_bounded(lambda: ex.submit(lambda: "q", A, rep.reply_for("queued")))
        run_bounded(lambda: ex.submit(lambda: "over", A, rep.reply_for("over")))
        assert rep.wait(["over"], 5.0), "точка executor_busy: reply не вызван за 5 с"
        settle()
        check("executor_busy", rep, "over", EXECUTOR_BUSY)
    finally:
        release.set()

    assert not verdicts, "нарушения по точкам:\n" + "\n".join(verdicts)


# ---------------------------------------------------------------------------
# R5: shutdown снимает очередь и закрывает приём
# ---------------------------------------------------------------------------


def test_shutdown_rejects_queue_and_later_submits(make_executor):
    """R5: 3 ждущих ({a}) + shutdown — system_stopping каждому; submit после — отказ на вызывающем потоке."""
    ex = make_executor("r5")
    rec, rep = Rec(), Replies()

    def submit_all() -> None:
        # Блокер держит ключ {a}, три следующие с тем же ключом — гарантированно ждущие.
        ex.submit(rec.action("blk", 0.5), A, rep.reply_for("blk"))
        assert rec.started_event("blk").wait(3.0), "блокер не начался"
        for label in ("w1", "w2", "w3"):
            ex.submit(rec.action(label, 0.05), A, rep.reply_for(label))

    run_bounded(submit_all)
    run_bounded(lambda: ex.shutdown(time.monotonic() + 3.0), timeout=6.0)

    assert rep.wait(["w1", "w2", "w3"], 3.0), "ждущие не получили ответа после shutdown"
    time.sleep(0.2)
    for label in ("w1", "w2", "w3"):
        assert rep.only(label) == [SYSTEM_STOPPING], (
            f"{label}: ожидали ровно [system_stopping], получили {rep.only(label)!r}"
        )
        assert label not in rec.start, f"{label} исполнилась, хотя должна была быть снята"

    ret, caller = run_bounded(lambda: ex.submit(rec.action("late", 0.0), A, rep.reply_for("late")))
    assert ret is False, f"submit после shutdown вернул {ret!r}, ожидали False"
    assert rep.only("late") == [SYSTEM_STOPPING], f"submit после shutdown: reply {rep.only('late')!r}"
    assert rep.threads["late"] == [caller], "отказ после shutdown должен прийти на вызывающем потоке"
    assert "late" not in rec.start, "операция после shutdown исполнилась"


# ---------------------------------------------------------------------------
# R6: submit не блокирует на потолке
# ---------------------------------------------------------------------------


def test_submit_never_blocks_refuses_at_ceiling(make_executor):
    """R6: max_pending=2, ключ {a}: на потолке submit <= 0,05 с, False, executor_busy ровно раз."""
    ex = make_executor("r6", max_pending=2)
    rec, rep = Rec(), Replies()
    release = threading.Event()
    try:
        run_bounded(
            lambda: ex.submit(lambda: (rec.started_event("blk").set(), release.wait(1.0))[1], A, rep.reply_for("blk"))
        )
        assert rec.started_event("blk").wait(3.0), "блокирующая операция не началась"

        accepted = []
        for label in ("q1", "q2"):
            ret, _ = run_bounded(lambda label=label: ex.submit(rec.action(label, 0.0), A, rep.reply_for(label)))
            accepted.append(ret)
        assert accepted == [True, True], (
            f"две операции в очереди при max_pending=2 должны приниматься (True, True), получили {accepted!r}"
        )

        def over() -> tuple[Any, float]:
            t = time.perf_counter()
            ret = ex.submit(rec.action("over", 0.0), A, rep.reply_for("over"))
            return ret, time.perf_counter() - t

        (ret, elapsed), _ = run_bounded(over, timeout=3.0)
        assert elapsed <= 0.05, f"submit на потолке блокировал {elapsed:.3f} с (> 0.05)"
        assert ret is False, f"submit на потолке вернул {ret!r}, ожидали False"
        time.sleep(0.2)
        assert rep.only("over") == [EXECUTOR_BUSY], (
            f"reply на потолке: {rep.only('over')!r}, ожидали ровно [executor_busy]"
        )
        assert "over" not in rec.start, "отвергнутая операция исполнилась"
    finally:
        release.set()


# ---------------------------------------------------------------------------
# R11: Stoppable
# ---------------------------------------------------------------------------


def test_executor_is_stoppable(make_executor):
    """R11: isinstance Stoppable; request_stop() дважды — без ошибки; join_until после пустой очереди — True."""
    ex = make_executor("r11")

    assert isinstance(ex, Stoppable) is True, "KeyedExecutor должен быть Stoppable"

    ex.request_stop()
    ex.request_stop()  # идемпотентность: без исключения

    ret, _ = run_bounded(lambda: ex.join_until(time.monotonic() + 1.0), timeout=4.0)
    assert ret is True, f"join_until на пустой остановленной очереди вернул {ret!r}, ожидали True"


# ---------------------------------------------------------------------------
# R12 / R12b: inline_if_idle
# ---------------------------------------------------------------------------


def test_inline_if_idle_runs_on_caller_when_key_free(make_executor):
    """R12: свободный ключ — на вызывающем потоке, False; занятый {a} — True, не на вызывающем, после занятой."""
    ex = make_executor("r12", serial=False)
    rec, rep = Rec(), Replies()

    # Часть 1: ключ свободен.
    ret, caller = run_bounded(
        lambda: ex.submit(rec.action("free", 0.05), A, rep.reply_for("free"), inline_if_idle=True)
    )
    assert ret is False, f"свободный ключ: submit(inline_if_idle=True) вернул {ret!r}, ожидали False"
    assert rec.thread.get("free") == caller, "свободный ключ: action исполнена не на вызывающем потоке"
    assert rep.only("free") == ["free"], f"свободный ключ: reply {rep.only('free')!r}, ожидали ровно ['free']"
    assert rep.threads["free"] == [caller], "свободный ключ: reply должен прийти на вызывающем потоке"

    # Часть 2: ключ {a} занят операцией 0,3 с.
    run_bounded(lambda: ex.submit(rec.action("busy", 0.3), A, rep.reply_for("busy")))
    assert rec.started_event("busy").wait(3.0), "занимающая операция не началась"
    ret2, caller2 = run_bounded(
        lambda: ex.submit(rec.action("queued", 0.0), A, rep.reply_for("queued"), inline_if_idle=True)
    )
    assert ret2 is True, f"занятый ключ: submit вернул {ret2!r}, ожидали True (поставлено в очередь)"
    assert rep.wait(["busy", "queued"], 5.0), "не все ответы пришли за 5 с"
    assert rec.thread["queued"] != caller2, "занятый ключ: action исполнена на вызывающем потоке"
    assert rec.start["queued"] >= rec.end["busy"], "занятый ключ: action началась до конца занимающей операции"


def test_inline_if_idle_respects_serial_order(make_executor):
    """R12b: serial=True, рабочий исполняет {a} 0,3 с — submit({b}, inline_if_idle=True) -> True, start(b) >= end(a)."""
    ex = make_executor("r12b", serial=True)
    rec, rep = Rec(), Replies()

    run_bounded(lambda: ex.submit(rec.action("a", 0.3), A, rep.reply_for("a")))
    assert rec.started_event("a").wait(3.0), "операция {a} не началась"

    ret, _ = run_bounded(lambda: ex.submit(rec.action("b", 0.0), B, rep.reply_for("b"), inline_if_idle=True))
    assert ret is True, f"serial=True при занятом рабочем: submit вернул {ret!r}, ожидали True"
    assert rep.wait(["a", "b"], 5.0), "не все ответы пришли за 5 с"
    assert rec.start["b"] >= rec.end["a"], "serial=True: {b} (inline_if_idle) началась до конца {a}"
