# -*- coding: utf-8 -*-
"""Hazard- и контрактные тесты автора Task 1.9a: ``KeyedExecutor`` (H1a, H1b, H2, H5, H7 + контракт D1).

Правила стенда: каждый ждущий вызов — в daemon-потоке с дедлайном join; ожидания — литералы;
часы — ``time.perf_counter()``; исполнитель — с настоящим ``WorkerManager``. Приёмочные R1–R12b —
в ``test_keyed_executor_acceptance.py`` (слепой тестер), здесь — только то, чего они не ловят.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager, WorkerType
from multiprocess_framework.modules.worker_module.interfaces import OrderedExecutor
from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor

A = frozenset({"a"})
B = frozenset({"b"})
AB = frozenset({"a", "b"})
SYSTEM_STOPPING = {"success": False, "error": "system_stopping"}
EXECUTOR_BUSY = {"success": False, "error": "executor_busy"}


def run_bounded(fn: Callable[[], Any], timeout: float = 5.0) -> tuple[Any, int]:
    """Выполнить ``fn`` в daemon-потоке; не уложилась в ``timeout`` — провал, не зависание."""
    box: dict[str, Any] = {}

    def target() -> None:
        box["ident"] = threading.get_ident()
        try:
            box["ret"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в потоке теста
            box["exc"] = exc

    t = threading.Thread(target=target, name="hazard-probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"вызов не вернулся за {timeout} с (зависание)")
    if "exc" in box:
        raise box["exc"]
    return box.get("ret"), box["ident"]


class Replies:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.payloads: dict[str, list[Any]] = {}
        self._events: dict[str, threading.Event] = {}

    def _event(self, label: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault(label, threading.Event())

    def reply_for(self, label: str) -> Callable[[Any], None]:
        ev = self._event(label)

        def reply(payload: Any) -> None:
            with self._lock:
                self.payloads.setdefault(label, []).append(payload)
            ev.set()

        return reply

    def wait(self, labels: list[str], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        return all(self._event(lb).wait(max(0.0, deadline - time.monotonic())) for lb in labels)

    def only(self, label: str) -> list[Any]:
        with self._lock:
            return list(self.payloads.get(label, []))


@pytest.fixture
def make_executor():
    created: list[tuple[KeyedExecutor, WorkerManager]] = []

    def factory(name: str = "h", wm: WorkerManager | None = None, **kwargs: Any) -> KeyedExecutor:
        if wm is None:
            wm = WorkerManager(f"wmh-{name}-{len(created)}")
            wm.initialize()
        ex = KeyedExecutor(name, worker_manager=wm, **kwargs)
        created.append((ex, wm))
        return ex

    yield factory
    for ex, wm in created:
        try:
            ex.request_stop()
            ex.join_until(time.monotonic() + 2.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            wm.shutdown()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# H1: повторный вход
# ---------------------------------------------------------------------------


def test_h1a_reentrant_submit_with_subset_key_runs_inline_without_deadlock(make_executor):
    """H1a: с потока рабочего submit с key ⊆ ключа текущей — на месте (False), до конца родителя; дедлайн 2 с."""
    ex = make_executor("h1a", max_workers=1)
    rep = Replies()
    seen: dict[str, Any] = {}

    def child() -> str:
        seen["child_thread"] = threading.get_ident()
        seen["child_end"] = time.perf_counter()
        return "child"

    def parent() -> str:
        seen["parent_thread"] = threading.get_ident()
        seen["nested_ret"] = ex.submit(child, A, rep.reply_for("child"))
        seen["parent_end"] = time.perf_counter()
        return "parent"

    run_bounded(lambda: ex.submit(parent, AB, rep.reply_for("parent")))
    assert rep.wait(["parent", "child"], 2.0), "дедлок или потерянный ответ при повторном входе (2 с)"
    assert seen["nested_ret"] is False, "вложенная с key ⊆ должна исполниться на месте (возврат False)"
    assert seen["child_thread"] == seen["parent_thread"], "вложенная исполнена не на потоке родителя"
    assert seen["child_end"] <= seen["parent_end"], "вложенная кончилась после родителя — не на месте"
    assert rep.only("child") == ["child"]
    assert rep.only("parent") == ["parent"]


def test_h1b_reentrant_submit_with_wider_key_is_queued_after_parent(make_executor):
    """H1b: serial=False, родитель {a}, вложенная {a,b} → True, start(вложенной) ≥ end(родителя); дедлайн 2 с."""
    ex = make_executor("h1b", serial=False)
    rep = Replies()
    marks: dict[str, Any] = {}

    def child() -> str:
        marks["child_start"] = time.perf_counter()
        return "child"

    def parent() -> str:
        marks["nested_ret"] = ex.submit(child, AB, rep.reply_for("child"))
        threading.Event().wait(0.2)
        marks["parent_end"] = time.perf_counter()
        return "parent"

    run_bounded(lambda: ex.submit(parent, A, rep.reply_for("parent")))
    assert rep.wait(["parent", "child"], 2.0), "вложенная {a,b} не исполнилась за 2 с"
    assert marks["nested_ret"] is True, "вложенная с ключом ⊄ должна ставиться в очередь (True)"
    assert marks["child_start"] >= marks["parent_end"], "вложенная {a,b} началась до конца родителя {a}"


# ---------------------------------------------------------------------------
# H2: shutdown с застрявшей операцией
# ---------------------------------------------------------------------------


def test_h2_shutdown_with_stuck_operation_returns_false_by_deadline(make_executor, caplog):
    """H2: застрявшая + две ждущие: shutdown → False не позже срока + 0,1 с, WARNING, ждущим system_stopping."""
    log = logging.getLogger("test.keyed.h2")
    ex = make_executor("h2", log=log)
    rep = Replies()
    release = threading.Event()
    started = threading.Event()

    def stuck() -> str:
        started.set()
        release.wait(5.0)
        return "stuck"

    try:
        run_bounded(lambda: ex.submit(stuck, A, rep.reply_for("stuck")))
        assert started.wait(3.0), "застрявшая операция не началась"
        run_bounded(lambda: ex.submit(lambda: "w1", A, rep.reply_for("w1")))
        run_bounded(lambda: ex.submit(lambda: "w2", A, rep.reply_for("w2")))

        with caplog.at_level(logging.WARNING, logger="test.keyed.h2"):
            t0 = time.perf_counter()
            (ret, elapsed), _ = run_bounded(
                lambda: (ex.shutdown(time.monotonic() + 0.3), time.perf_counter() - t0), timeout=3.0
            )
        assert ret is False, f"shutdown с застрявшей операцией вернул {ret!r}, ожидали False"
        assert elapsed <= 0.4, f"shutdown вернулся через {elapsed:.3f} с (> срок 0,3 + 0,1)"
        warnings = [r for r in caplog.records if r.name == "test.keyed.h2" and r.levelno == logging.WARNING]
        assert warnings, "нет WARNING о незавершённой операции"
        assert "stuck" in warnings[-1].getMessage(), "WARNING без имени застрявшей операции"
        assert rep.wait(["w1", "w2"], 1.0)
        assert rep.only("w1") == [SYSTEM_STOPPING]
        assert rep.only("w2") == [SYSTEM_STOPPING]
    finally:
        release.set()
    assert rep.wait(["stuck"], 3.0), "застрявшая после отпускания не ответила"
    assert rep.only("stuck") == ["stuck"], "застрявшая операция получила не свой результат"


# ---------------------------------------------------------------------------
# H5: исключение в reply
# ---------------------------------------------------------------------------


def test_h5_exception_in_reply_is_logged_and_next_operation_runs(make_executor, caplog):
    """H5: reply бросает — log.error, рабочий жив: следующая операция того же ключа исполнена."""
    log = logging.getLogger("test.keyed.h5")
    ex = make_executor("h5", serial=True, log=log)
    rep = Replies()
    raised = threading.Event()

    def bad_reply(payload: Any) -> None:
        raised.set()
        raise RuntimeError("reply-boom")

    with caplog.at_level(logging.ERROR, logger="test.keyed.h5"):
        run_bounded(lambda: ex.submit(lambda: "first", A, bad_reply))
        run_bounded(lambda: ex.submit(lambda: "second", A, rep.reply_for("second")))
        assert rep.wait(["second"], 3.0), "после исключения в reply следующая операция не исполнилась"
    assert raised.is_set()
    assert rep.only("second") == ["second"]
    errors = [r for r in caplog.records if r.name == "test.keyed.h5" and r.levelno == logging.ERROR]
    assert len(errors) == 1, f"ожидали ровно один ERROR об исключении в reply, получили {len(errors)}"

    # На вызывающем потоке (отказ после закрытия) — тоже лог, submit возвращается штатно.
    ex.request_stop()
    with caplog.at_level(logging.ERROR, logger="test.keyed.h5"):
        ret, _ = run_bounded(lambda: ex.submit(lambda: "late", A, bad_reply))
    assert ret is False


# ---------------------------------------------------------------------------
# H7: лок исполнителя не держится поверх action / reply / should_reject
# ---------------------------------------------------------------------------


def test_h7_lock_is_free_during_action_reply_and_should_reject(make_executor):
    """H7: пока action, reply или should_reject рабочего ждут 1 с, submit с другого потока ≤ 0,05 с."""
    gate = {"block_reject": False}
    reject_entered = threading.Event()
    reject_release = threading.Event()

    def should_reject() -> bool:
        if gate["block_reject"] and threading.current_thread().name.startswith("wmh-h7"):
            reject_entered.set()
            reject_release.wait(1.0)
        return False

    ex = make_executor("h7", max_workers=2, should_reject=should_reject)
    rep = Replies()

    def timed_submit(label: str, key: frozenset[str]) -> float:
        (_, elapsed), _ = run_bounded(
            lambda: (
                (t := time.perf_counter()),
                ex.submit(lambda: label, key, rep.reply_for(label)),
                time.perf_counter() - t,
            )[1:],
            timeout=3.0,
        )
        return elapsed

    # 1) во время action
    in_action, release_action = threading.Event(), threading.Event()
    run_bounded(lambda: ex.submit(lambda: (in_action.set(), release_action.wait(1.0))[1], A, rep.reply_for("act")))
    assert in_action.wait(3.0)
    elapsed = timed_submit("during_action", B)
    release_action.set()
    assert elapsed <= 0.05, f"submit во время action ждал {elapsed:.3f} с — лок держится поверх action"

    # 2) во время reply
    in_reply, release_reply = threading.Event(), threading.Event()

    def slow_reply(payload: Any) -> None:
        in_reply.set()
        release_reply.wait(1.0)

    run_bounded(lambda: ex.submit(lambda: "r", A, slow_reply))
    assert in_reply.wait(3.0)
    elapsed = timed_submit("during_reply", B)
    release_reply.set()
    assert elapsed <= 0.05, f"submit во время reply ждал {elapsed:.3f} с — лок держится поверх reply"

    # 3) во время should_reject рабочего
    assert rep.wait(["act", "during_action", "during_reply"], 3.0)
    gate["block_reject"] = True
    run_bounded(lambda: ex.submit(lambda: "trigger", A, rep.reply_for("trigger")))
    assert reject_entered.wait(3.0), "рабочий не позвал should_reject перед взятием"
    gate["block_reject"] = False
    elapsed = timed_submit("during_reject", B)
    reject_release.set()
    assert elapsed <= 0.05, f"submit во время should_reject ждал {elapsed:.3f} с — лок держится поверх него"
    assert rep.wait(["trigger", "during_reject"], 3.0)


# ---------------------------------------------------------------------------
# Контракт D1 (module-contract): конструктор, воркеры, отказы, should_reject
# ---------------------------------------------------------------------------


def test_contract_executor_satisfies_ordered_executor_protocol(make_executor):
    ex = make_executor("c-proto")
    assert isinstance(ex, OrderedExecutor) is True


def test_contract_workers_are_permanent_system_workers(make_executor):
    wm = WorkerManager("wmh-c-workers")
    wm.initialize()
    make_executor("cw", wm=wm, max_workers=3)
    make_executor("cs", wm=wm, serial=True, max_workers=9)
    system = set(wm.list_workers(WorkerType.SYSTEM))
    assert {"keyed-cw-0", "keyed-cw-1", "keyed-cw-2", "keyed-cs-0"} <= system
    assert "keyed-cs-1" not in system, "serial=True: рабочий должен быть ровно один"
    assert not wm.list_workers(WorkerType.APPLICATION)


def test_contract_constructor_raises_when_worker_name_taken(make_executor):
    wm = WorkerManager("wmh-c-dup")
    wm.initialize()
    make_executor("dup", wm=wm, max_workers=1)
    with pytest.raises(ValueError):
        make_executor("dup", wm=wm, max_workers=1)


def test_contract_pause_all_does_not_stop_executor(make_executor):
    wm = WorkerManager("wmh-c-pause")
    wm.initialize()
    ex = make_executor("pause", wm=wm)
    rep = Replies()
    wm.pause_all_workers()
    run_bounded(lambda: ex.submit(lambda: "ran", A, rep.reply_for("p")))
    assert rep.wait(["p"], 2.0), "pause_all остановил SYSTEM-воркеры исполнителя"


def test_contract_stop_all_workers_rejects_queue(make_executor):
    """stop_event от WorkerManager → request_stop: очередь получает system_stopping, а не тишину."""
    wm = WorkerManager("wmh-c-stopall")
    wm.initialize()
    ex = make_executor("stopall", wm=wm, max_workers=1)
    rep = Replies()
    release, started = threading.Event(), threading.Event()
    run_bounded(lambda: ex.submit(lambda: (started.set(), release.wait(0.3))[1], A, rep.reply_for("blk")))
    assert started.wait(3.0)
    run_bounded(lambda: ex.submit(lambda: "w", A, rep.reply_for("w")))
    run_bounded(lambda: wm.stop_all_workers(timeout=2.0), timeout=4.0)
    assert rep.wait(["blk", "w"], 2.0)
    assert rep.only("w") == [SYSTEM_STOPPING]
    ret, _ = run_bounded(lambda: ex.submit(lambda: "late", A, rep.reply_for("late")))
    assert ret is False and rep.only("late") == [SYSTEM_STOPPING]


def test_contract_should_reject_true_refuses_submit_and_queue_without_latch(make_executor):
    flag = {"reject": False}
    ex = make_executor("rej", max_workers=1, should_reject=lambda: flag["reject"])
    rep = Replies()
    release, started = threading.Event(), threading.Event()
    run_bounded(lambda: ex.submit(lambda: (started.set(), release.wait(2.0))[1], A, rep.reply_for("blk")))
    assert started.wait(3.0)
    run_bounded(lambda: ex.submit(lambda: "q", A, rep.reply_for("q")))
    flag["reject"] = True
    ret, _ = run_bounded(lambda: ex.submit(lambda: "now", A, rep.reply_for("now")))
    assert ret is False and rep.only("now") == [SYSTEM_STOPPING]
    release.set()
    assert rep.wait(["blk", "q"], 3.0)
    assert rep.only("q") == [SYSTEM_STOPPING], "рабочий не снял очередь по should_reject"
    flag["reject"] = False  # без защёлки: снова принимает
    run_bounded(lambda: ex.submit(lambda: "again", A, rep.reply_for("again")))
    assert rep.wait(["again"], 3.0) and rep.only("again") == ["again"]


def test_contract_should_reject_exception_counts_as_true(make_executor, caplog):
    def broken() -> bool:
        raise RuntimeError("probe")

    log = logging.getLogger("test.keyed.rejexc")
    ex = make_executor("rejexc", should_reject=broken, log=log)
    rep = Replies()
    with caplog.at_level(logging.ERROR, logger="test.keyed.rejexc"):
        ret, _ = run_bounded(lambda: ex.submit(lambda: "x", A, rep.reply_for("x")))
    assert ret is False and rep.only("x") == [SYSTEM_STOPPING]
    assert any(r.name == "test.keyed.rejexc" and r.levelno == logging.ERROR for r in caplog.records)


def test_contract_executor_busy_warns_once_per_episode(make_executor, caplog):
    log = logging.getLogger("test.keyed.busy")
    ex = make_executor("busy", max_pending=1, max_workers=1, log=log)
    rep = Replies()

    def episode(tag: str) -> None:
        release, started = threading.Event(), threading.Event()
        run_bounded(lambda: ex.submit(lambda: (started.set(), release.wait(2.0))[1], A, rep.reply_for(f"{tag}b")))
        assert started.wait(3.0)
        run_bounded(lambda: ex.submit(lambda: "q", A, rep.reply_for(f"{tag}q")))
        for i in range(3):
            run_bounded(lambda i=i: ex.submit(lambda: "o", A, rep.reply_for(f"{tag}o{i}")))
        release.set()
        assert rep.wait([f"{tag}b", f"{tag}q"], 3.0)

    with caplog.at_level(logging.WARNING, logger="test.keyed.busy"):
        episode("e1")
        episode("e2")
    for tag in ("e1", "e2"):
        for i in range(3):
            assert rep.only(f"{tag}o{i}") == [EXECUTOR_BUSY]
    busy = [r for r in caplog.records if r.name == "test.keyed.busy" and r.levelno == logging.WARNING]
    assert len(busy) == 2, f"ожидали по одному WARNING на эпизод (2), получили {len(busy)}"


def test_contract_none_key_waits_for_earlier_and_holds_later(make_executor):
    ex = make_executor("none", max_workers=4)
    rep = Replies()
    marks: dict[str, float] = {}

    def op(label: str, dur: float) -> Callable[[], str]:
        def run() -> str:
            marks[f"{label}_start"] = time.perf_counter()
            threading.Event().wait(dur)
            marks[f"{label}_end"] = time.perf_counter()
            return label

        return run

    def submit_all() -> None:
        ex.submit(op("a", 0.2), A, rep.reply_for("a"))
        ex.submit(op("all", 0.2), None, rep.reply_for("all"))
        ex.submit(op("new", 0.0), frozenset({"never-seen"}), rep.reply_for("new"))

    run_bounded(submit_all)
    assert rep.wait(["a", "all", "new"], 3.0)
    assert marks["all_start"] >= marks["a_end"], "None началась до конца ранее поданной {a}"
    assert marks["new_start"] >= marks["all_end"], "ключ, которого не было в очереди, обогнал None"


def test_contract_default_logger_name(make_executor, caplog):
    ex = make_executor("deflog", max_pending=1, max_workers=1)
    name = "multiprocess_framework.worker_module.keyed_executor.deflog"
    rep = Replies()
    release, started = threading.Event(), threading.Event()
    run_bounded(lambda: ex.submit(lambda: (started.set(), release.wait(2.0))[1], A, rep.reply_for("b")))
    assert started.wait(3.0)
    run_bounded(lambda: ex.submit(lambda: "q", A, rep.reply_for("q")))
    with caplog.at_level(logging.WARNING, logger=name):
        run_bounded(lambda: ex.submit(lambda: "o", A, rep.reply_for("o")))
    release.set()
    assert any(r.name == name and r.levelno == logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# Раунд 2 ревью: H8 (BaseException в action), H9 (should_reject при занятом ключе)
# ---------------------------------------------------------------------------


def test_h8_system_exit_in_action_replies_once_and_closes_executor(make_executor):
    """H8: SystemExit в action — reply ровно раз; ждущая и последующие получают system_stopping."""
    ex = make_executor("h8", max_workers=1)
    rep = Replies()
    go = threading.Event()

    def die() -> Any:
        go.wait(2.0)
        raise SystemExit("h8")

    run_bounded(lambda: ex.submit(die, A, rep.reply_for("die")))
    run_bounded(lambda: ex.submit(lambda: "queued", A, rep.reply_for("queued")))
    go.set()
    assert rep.wait(["die", "queued"], 2.0), "после SystemExit ответы не пришли за 2 с"
    stopped, _ = run_bounded(lambda: ex.join_until(time.monotonic() + 2.0), timeout=4.0)
    assert stopped is True, "рабочий не вышел после SystemExit"
    time.sleep(0.2)
    assert rep.only("die") == [{"success": False, "error": "SystemExit: h8"}]
    assert rep.only("queued") == [SYSTEM_STOPPING]
    ret, _ = run_bounded(lambda: ex.submit(lambda: "later", A, rep.reply_for("later")))
    assert ret is False
    assert rep.only("later") == [SYSTEM_STOPPING]


def test_h9_should_reject_drains_queue_while_key_is_busy(make_executor):
    """H9: {a} исполняется 1 с, вторая {a} ждёт; should_reject=True на 0,2 с → вторая получила отказ ≤ 0,8 с.

    Без защёлки: после сброса флага новая операция исполняется."""
    flag = {"reject": False}
    ex = make_executor("h9", should_reject=lambda: flag["reject"])
    rep = Replies()
    started = threading.Event()
    run_bounded(lambda: ex.submit(lambda: (started.set(), threading.Event().wait(1.0))[1], A, rep.reply_for("long")))
    assert started.wait(3.0)
    t0 = time.perf_counter()
    run_bounded(lambda: ex.submit(lambda: "second", A, rep.reply_for("second")))
    flag["reject"] = True
    threading.Event().wait(0.2)
    flag["reject"] = False
    assert rep.wait(["second"], max(0.0, 0.8 - (time.perf_counter() - t0))), "ждущая за занятым ключом не снята"
    assert rep.only("second") == [SYSTEM_STOPPING]
    run_bounded(lambda: ex.submit(lambda: "third", A, rep.reply_for("third")))
    assert rep.wait(["long", "third"], 3.0)
    assert rep.only("third") == ["third"], "после сброса флага исполнитель не принимает (защёлка)"
