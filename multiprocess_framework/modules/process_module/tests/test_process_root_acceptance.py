"""Слепая приёмка корня процесса (lifecycle-owner-scope, Task 1.2a).

Контракт: корень процесса из трёх областей ``planes | transport | work``;
``stop()`` = ``cancel()`` (не блокирует); гасит ``shutdown()`` одним закрытием
корня; бюджет остановки приходит из конфига ребёнка; выжившие дают код 76.

Тесты написаны ДО реализации и пишутся по брифу, а не по коду. Ожидаемые
значения — литералы. Каждый собранный процесс закрывается в ``finally``.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.base_manager.interfaces import CloseReport
from multiprocess_framework.modules.process_manager_module.runner import process_runner
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

GOLDEN_ORDER = [
    "workers",
    "plugins",
    "hooks",
    "flush",
    "console",
    "command",
    "router",
    "srm",
    "observation",
    "stats",
    "error",
    "logger",
]
CHILD_BUDGET = {"work_s": 0.6, "infra_s": 0.2, "pm_graceful_s": 1.0, "pm_total_s": 3.0, "outer_s": 4.5}

# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка, длительность)."""
    box: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed")


class Recorder:
    """Журнал событий: порядок записей и отметки времени."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.times: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, event: str) -> None:
        with self._lock:
            self.events.append(event)
            self.times[event] = time.monotonic()

    def count(self, event: str) -> int:
        return self.events.count(event)


class _ManagerDouble:
    def __init__(self, journal: Recorder, event: str) -> None:
        self._journal = journal
        self._event = event

    def shutdown(self, *args, **kwargs) -> bool:
        self._journal.add(self._event)
        return True


class _WorkerManagerDouble:
    def __init__(self, journal: Recorder) -> None:
        self._journal = journal

    def stop_all_workers(self, timeout=None) -> None:
        self._journal.add("workers")

    def list_workers(self) -> list:
        return []

    def get_worker_status(self, name) -> dict:
        return {"is_alive": False}


def install_doubles(proc, journal: Recorder) -> dict:
    """Заменить менеджеры и хуки процесса записывающими дублёрами (ПОСЛЕ ``initialize()``).

    Возвращает прежние объекты, чтобы тест мог погасить настоящие менеджеры в ``finally``.
    """
    originals = {
        name: getattr(proc, name, None)
        for name in (
            "worker_manager",
            "_orchestrator",
            "shared_resources",
            "router_manager",
            "command_manager",
            "console_manager",
            "error_manager",
            "stats_manager",
            "observation_manager",
            "logger_manager",
        )
    }
    proc.worker_manager = _WorkerManagerDouble(journal)
    proc._orchestrator = _ManagerDouble(journal, "plugins")
    proc.shared_resources = _ManagerDouble(journal, "srm")
    proc.router_manager = _ManagerDouble(journal, "router")
    proc.command_manager = _ManagerDouble(journal, "command")
    proc.console_manager = _ManagerDouble(journal, "console")
    proc.error_manager = _ManagerDouble(journal, "error")
    proc.stats_manager = _ManagerDouble(journal, "stats")
    proc.observation_manager = _ManagerDouble(journal, "observation")
    proc.logger_manager = _ManagerDouble(journal, "logger")
    proc._uninstall_process_hooks = lambda *a, **k: journal.add("hooks")
    proc._flush_observability = lambda *a, **k: journal.add("flush")
    return originals


def release_originals(originals: dict) -> None:
    """Погасить настоящие менеджеры, оставшиеся после подмены (сборка их поднимала)."""
    for name, obj in originals.items():
        if name == "shared_resources" or obj is None:
            continue
        try:
            obj.shutdown()
        except Exception:  # noqa: BLE001 - уборка, не предмет теста
            pass


class HoldingStoppable:
    """Stoppable: ``request_stop`` не блокирует, ``join_until`` держит выход ``hold_s``."""

    def __init__(self, journal: Recorder, tag: str, hold_s: float, release: threading.Event | None = None) -> None:
        self._journal = journal
        self._tag = tag
        self._hold_s = hold_s
        self._release = release or threading.Event()

    def request_stop(self) -> None:
        self._journal.add(f"{self._tag}.request_stop")

    def join_until(self, deadline: float) -> bool:
        wait = min(self._hold_s, max(0.0, deadline - time.monotonic()))
        self._release.wait(wait)
        done = wait >= self._hold_s or self._release.is_set()
        if done:
            self._journal.add(f"{self._tag}.join_end")
        return done


class NeverStopsStoppable:
    """Не останавливается никогда: ждёт срок и возвращает False; ``kill`` нет."""

    def __init__(self, journal: Recorder | None = None) -> None:
        self._journal = journal

    def request_stop(self) -> None:
        if self._journal is not None:
            self._journal.add("stuck.request_stop")

    def join_until(self, deadline: float) -> bool:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        return False


def make_process(budget: dict | None = None) -> ProcessModule:
    proc = ProcessModule("p", config={})
    if budget is not None:
        proc.attach_stop_budget(budget)
    assert proc.initialize() is True
    return proc


# ---------------------------------------------------------------------------
# 1. Порядок закрытия (golden G7)
# ---------------------------------------------------------------------------


def test_root_close_order_golden() -> None:
    journal = Recorder()
    proc = make_process()
    originals = install_doubles(proc, journal)
    status: list[str] = []

    def update_process_state(*args, **kwargs) -> None:
        flat = [str(a).lower() for a in args] + [str(v).lower() for v in kwargs.values()]
        if any("stopped" in item for item in flat):
            journal.add("status:stopped")
            status.append("stopped")

    proc.update_process_state = update_process_state
    try:
        done, result, error, _ = call_bounded(proc.shutdown, 15.0)
        assert done, "shutdown() завис"
        assert error is None, repr(error)
        assert result is True
        assert [e for e in journal.events if e != "status:stopped"] == GOLDEN_ORDER
        assert status == ["stopped"], "STOPPED пишется ровно один раз"
        stopped_at = journal.events.index("status:stopped")
        assert journal.events.index("error") < stopped_at < journal.events.index("logger")
    finally:
        call_bounded(proc.shutdown, 15.0)
        release_originals(originals)


# ---------------------------------------------------------------------------
# 2. Барьеры: planes останавливается после того, как закрыт work
# ---------------------------------------------------------------------------


def test_barrier_planes_stop_after_work_done() -> None:
    journal = Recorder()
    proc = make_process()
    try:
        segments = proc.lifetime_segments
        assert set(segments) == {"planes", "transport", "work"}
        sink = HoldingStoppable(journal, "sink", hold_s=0.0)
        work_res = HoldingStoppable(journal, "work", hold_s=0.3)
        segments["planes"].own(sink, name="sink", kind="sink")
        segments["work"].own(work_res, name="w", kind="worker")

        done, result, error, _ = call_bounded(proc.shutdown, 20.0)
        assert done, "shutdown() завис"
        assert error is None, repr(error)

        assert "work.join_end" in journal.events, journal.events
        assert "sink.request_stop" in journal.events, journal.events
        # Сток получает request_stop только после выхода записи work (держала 0,3 с).
        assert journal.events.index("sink.request_stop") > journal.events.index("work.join_end"), journal.events
    finally:
        call_bounded(proc.shutdown, 20.0)


def test_lifetime_segments_empty_before_initialize() -> None:
    proc = ProcessModule("p", config={})
    assert dict(proc.lifetime_segments) == {}


def test_shutdown_without_initialize_returns_true_and_closes_nothing() -> None:
    proc = ProcessModule("p", config={})
    journal = Recorder()
    originals = install_doubles(proc, journal)
    try:
        done, result, error, _ = call_bounded(proc.shutdown, 10.0)
        assert done
        assert error is None, repr(error)
        assert result is True
        assert journal.events == []
    finally:
        release_originals(originals)


# ---------------------------------------------------------------------------
# 3. stop() = cancel(): не блокирует, менеджеры ещё живы
# ---------------------------------------------------------------------------


def test_stop_is_cancel_nonblocking() -> None:
    journal = Recorder()
    release = threading.Event()
    proc = make_process()
    originals = install_doubles(proc, journal)
    try:
        holder = HoldingStoppable(journal, "holder", hold_s=2.0, release=release)
        proc.lifetime_segments["work"].own(holder, name="holder", kind="worker")

        done, _, error, elapsed = call_bounded(proc.stop, 5.0)
        assert done, "stop() завис"
        assert error is None, repr(error)
        assert elapsed <= 0.2, f"stop() заблокировал на {elapsed:.3f} с"
        # Ресурс-Stoppable получил фазу 1, но ничего ещё не погашено.
        assert "holder.request_stop" in journal.events, journal.events
        shut = [e for e in journal.events if e in GOLDEN_ORDER]
        assert shut == [], f"stop() погасил менеджеры: {shut}"
    finally:
        release.set()
        call_bounded(proc.shutdown, 20.0)
        release_originals(originals)


# ---------------------------------------------------------------------------
# 4. shutdown() дважды — закрытие один раз
# ---------------------------------------------------------------------------


def test_shutdown_twice_closes_once() -> None:
    journal = Recorder()
    proc = make_process()
    originals = install_doubles(proc, journal)
    try:
        first = call_bounded(proc.shutdown, 15.0)
        second = call_bounded(proc.shutdown, 15.0)
        assert first[0] and second[0], "shutdown() завис"
        assert first[2] is None and second[2] is None, (first[2], second[2])
        assert isinstance(first[1], bool) and isinstance(second[1], bool)
        for event in GOLDEN_ORDER:
            assert journal.count(event) == 1, f"{event}: {journal.count(event)} раз"
        report = proc.close_root()
        assert isinstance(report, CloseReport)
        assert report.survivors == ()
        assert report.errors == ()
        assert proc.close_root() is report, "повтор close_root() должен вернуть тот же отчёт"
    finally:
        call_bounded(proc.shutdown, 15.0)
        release_originals(originals)


# ---------------------------------------------------------------------------
# 5. Бюджет корня ребёнка из stop_budget
# ---------------------------------------------------------------------------


def test_child_root_budget_from_stop_budget() -> None:
    journal = Recorder()
    proc = make_process(budget=CHILD_BUDGET)
    originals = install_doubles(proc, journal)
    try:
        proc.lifetime_segments["work"].own(NeverStopsStoppable(journal), name="stuck", kind="worker")

        done, report, error, elapsed = call_bounded(proc.close_root, 10.0)
        assert done, "close_root() завис"
        assert error is None, repr(error)
        assert 0.5 <= elapsed <= 0.95, f"close_root() занял {elapsed:.3f} с при work_s=0.6, infra_s=0.2"
        assert "proc/p/work/stuck" in report.survivors, report.survivors
        assert report.ok is False
    finally:
        call_bounded(proc.shutdown, 10.0)
        release_originals(originals)


# ---------------------------------------------------------------------------
# 6-8. Раннер: один закрытый корень, код выживших, бюджет из конфига
# ---------------------------------------------------------------------------


class _Probe:
    """Состояние класса-наследника для наблюдения снаружи (раннер собирает процесс сам)."""

    instances: list = []
    seen_budgets: list = []
    close_calls: int = 0

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.seen_budgets = []
        cls.close_calls = 0


class _StuckRunnerProc(ProcessModule):
    """Процесс с записью в work, которая не останавливается к сроку."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _Probe.instances.append(self)

    def _own_work(self, work) -> None:
        work.own(NeverStopsStoppable(), name="w", kind="worker")

    def attach_stop_budget(self, budget: dict) -> None:
        _Probe.seen_budgets.append(dict(budget))
        super().attach_stop_budget(budget)


class _CleanRunnerProc(ProcessModule):
    """Процесс без выживших."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _Probe.instances.append(self)

    def attach_stop_budget(self, budget: dict) -> None:
        _Probe.seen_budgets.append(dict(budget))
        super().attach_stop_budget(budget)


class _SelfRunnerProc(ProcessModule):
    """Единственный выживший помечен ``(self)``: раннер не должен выходить с кодом 76."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _Probe.instances.append(self)

    def close_root(self):
        super().close_root()  # корень закрыт по-настоящему
        _Probe.close_calls += 1
        return CloseReport(
            path="proc/r",
            elapsed_s=0.0,
            survivors=("proc/r/work/w (self)",),
            killed=(),
            errors=(),
        )


@pytest.fixture
def runner_probe():
    _Probe.reset()
    yield _Probe
    _Probe.reset()


def _run_child(monkeypatch, proc_cls, process_config: dict, *, patch_hard_exit: bool = True):
    """Прогнать раннер в процессе pytest с подменённым выходом.

    Настоящий ``os._exit`` убил бы весь pytest, поэтому он всегда заменён страховкой;
    ``_hard_exit`` модуля раннера подменяется (без ``raising=False``: до кода его нет,
    и тест должен краснеть честно), если ``patch_hard_exit``.
    Возвращает (вызовы ``_hard_exit`` как (код, exit_report[0] на момент вызова), exit_report).
    """
    import multiprocessing
    import os

    hard_exit_calls: list = []
    exit_report = [0, 0, 0]

    def fake_hard_exit(code) -> None:
        hard_exit_calls.append((code, exit_report[0]))

    monkeypatch.setattr(os, "_exit", lambda code: hard_exit_calls.append(("os._exit", code)))
    if patch_hard_exit:
        monkeypatch.setattr(process_runner, "_hard_exit", fake_hard_exit)

    name = "r"
    srm = SharedResourcesManager()
    srm.process_state_registry.register_process(name)
    srm.get_process_data(name).custom["process_config"] = process_config
    stop_event = multiprocessing.Event()
    stop_event.set()
    class_path = f"{proc_cls.__module__}.{proc_cls.__name__}"

    done, _, error, _ = call_bounded(
        lambda: process_runner.run_process_function(
            class_path, name, stop_event=stop_event, shared_resources_or_bundle=srm, exit_report=exit_report
        ),
        60.0,
    )
    assert done, "run_process_function завис"
    assert error is None, repr(error)
    return hard_exit_calls, exit_report


def test_runner_exits_with_survivors_code(monkeypatch, runner_probe) -> None:
    config = {"stop_budget": {"work_s": 0.3, "infra_s": 0.1, "pm_graceful_s": 0.5, "pm_total_s": 2.0, "outer_s": 3.5}}
    calls, _ = _run_child(monkeypatch, _StuckRunnerProc, config)
    # Ровно один вызов с 76; к этому моменту отчёт о выходе уже записан.
    assert calls == [(76, 1)], calls
    # Константа кода — в stop_budget (импорт здесь: до кода её нет, и красным должен стать один тест, не сбор файла).
    from multiprocess_framework.modules.process_manager_module.core.stop_budget import EXIT_SURVIVORS

    assert EXIT_SURVIVORS == 76


@pytest.mark.parametrize(
    ("proc_cls", "config"),
    [
        pytest.param(
            _CleanRunnerProc,
            {"stop_budget": {"work_s": 0.3, "infra_s": 0.1, "pm_graceful_s": 0.5, "pm_total_s": 2.0, "outer_s": 3.5}},
            id="clean",
        ),
        pytest.param(
            _SelfRunnerProc,
            {"stop_budget": {"work_s": 0.3, "infra_s": 0.1, "pm_graceful_s": 0.5, "pm_total_s": 2.0, "outer_s": 3.5}},
            id="only-self-survivor",
        ),
    ],
)
def test_runner_no_exit_without_survivors_or_self(monkeypatch, runner_probe, proc_cls, config) -> None:
    calls, _ = _run_child(monkeypatch, proc_cls, config)
    assert calls == [], calls
    # Не вхолостую: раннер дошёл до закрытия корня и решил по его отчёту.
    assert len(runner_probe.instances) == 1
    if proc_cls is _SelfRunnerProc:
        assert runner_probe.close_calls >= 1
    else:
        assert runner_probe.instances[0].close_root().survivors == ()


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        pytest.param({"stop_budget": CHILD_BUDGET}, CHILD_BUDGET, id="explicit-stop-budget"),
        pytest.param({"shutdown_timeout": 1.0}, CHILD_BUDGET, id="derived-from-shutdown-timeout"),
    ],
)
def test_runner_passes_stop_budget_from_config(monkeypatch, runner_probe, config, expected) -> None:
    _run_child(monkeypatch, _CleanRunnerProc, config, patch_hard_exit=False)
    assert runner_probe.seen_budgets, "attach_stop_budget не вызван раннером"
    assert runner_probe.seen_budgets[-1] == pytest.approx(expected)
