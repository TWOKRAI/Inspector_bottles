# -*- coding: utf-8 -*-
"""Task 2.2e — hazard-тесты автора (REDS 8–10): снимок под сбоем хука, настоящие объекты, проводка GenericProcess.

Ожидаемые значения — литералы. Время сторожа — подставные часы, реального ожидания застоя нет.
Воркеры настоящего процесса зарегистрированы, но НЕ запущены: снимок считает сам тест.
"""

from __future__ import annotations

import multiprocessing
import queue
import sys
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager.types import ProcessStatus
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.generic import inbox_watch as iw
from multiprocess_framework.modules.process_module.generic.collector_registry import build_collector
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker

R = {"node": "recog", "severity": "out_of_spec", "reason": "recog: кадры не принимаются", "source": "inbox"}
E = {"node": "recog", "severity": "out_of_spec", "reason": "recog: обработка стоит", "source": "pipeline"}


class HzPass(ProcessModulePlugin):
    name = "hz_pass"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items: list[dict]) -> list[dict]:
        return items


_PLUGINS = [{"plugin_class": f"{__name__}.HzPass", "plugin_name": "hz_pass"}]


# --------------------------------------------------------------------------- #
# REDS 8. Сбой хука не останавливает снимок
# --------------------------------------------------------------------------- #


def _boom() -> list[dict]:
    raise RuntimeError("хук")


@pytest.mark.parametrize(
    ("hook", "error_type"),
    [
        (_boom, "RuntimeError"),
        (lambda: [{"node": 1, "severity": "out_of_spec", "reason": "x", "source": "inbox"}], "ValueError"),
        (lambda: [{"node": "recog", "severity": "bad", "reason": "x", "source": "inbox"}], "ValueError"),
    ],
    ids=["raises", "node_not_str", "bad_severity"],
)
def test_snapshot_survives_failing_process_reasons(hook, error_type) -> None:
    orch = PluginOrchestrator(services=MockProcessServices(name="recog"))
    orch.load_and_configure_managers(_PLUGINS)
    orch.boot()
    proc = ProcessModule(name="recog", config={})
    proc._orchestrator = orch
    errors: list[str] = []
    proc._log_error = lambda message, **_kw: errors.append(message)  # type: ignore[method-assign]
    proc._process_readiness_reasons = hook  # type: ignore[method-assign]
    try:
        stamps = []
        for _ in range(3):
            time.sleep(0.05)  # ``at`` — time.time(): на Windows шаг часов ~16 мс
            proc._refresh_readiness_snapshot()
            snapshot = proc._readiness_snapshot
            assert snapshot is not None
            assert snapshot["reasons"] == []
            stamps.append(snapshot["at"])
        assert stamps[0] < stamps[1] < stamps[2]
        assert errors == [f"Process 'recog': причины процесса не посчитаны: {error_type}"]

        proc._process_readiness_reasons = lambda: [dict(R)]  # type: ignore[method-assign]
        proc._refresh_readiness_snapshot()
        assert proc._readiness_snapshot["reasons"][0] == R
    finally:
        orch.shutdown()


# --------------------------------------------------------------------------- #
# REDS 9. Настоящие объекты: осиротевший замок очереди и настоящий исполнитель
# --------------------------------------------------------------------------- #


def _grab_rlock(q: Any, taken: Any) -> None:
    q._rlock.acquire()
    taken.set()
    time.sleep(60)


@pytest.mark.skipif(sys.platform == "darwin", reason="qsize на macOS недоступен")
@pytest.mark.timeout(60)
@pytest.mark.parametrize("orphaned", [True, False], ids=["orphaned_rlock", "control_free_lock"])
def test_real_receiver_on_real_queue(orphaned: bool) -> None:
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    if orphaned:
        taken = ctx.Event()
        child = ctx.Process(target=_grab_rlock, args=(q, taken), daemon=True)
        child.start()
        assert taken.wait(30), "помощник не взял замок"
        child.kill()
        child.join(5)
        assert not child.is_alive()
    for frame_id in range(3):
        q.put_nowait({"type": "data", "data": {"frame_id": frame_id}})

    def receive(timeout: float, **_kw: Any) -> Any:
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    chain: queue.Queue = queue.Queue(maxsize=16)
    collector = build_collector({}, lambda _m: None, lambda _m: None, lambda *_a, **_kw: None)
    receiver = DataReceiver(receive_fn=receive, shm_middleware=None, item_collector=collector, chain_queue=chain)
    collector._on_ready = receiver.on_items_ready
    stop = threading.Event()
    thread = threading.Thread(target=receiver.run_loop, args=(stop, threading.Event()), daemon=True)
    thread.start()
    try:
        # Приёмнику дают 2 с: со свободным замком он забирает всё, с осиротевшим — ничего.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and receiver.get_cycle_metrics()["cycles"] < 3:
            time.sleep(0.02)

        now = [1000.0]
        watch = iw.InboxWatch("recog", "recog: кадры не принимаются", "inbox", 15.0, clock=lambda: now[0])
        got = []
        for t in (1000.0, 1014.5, 1015.0):
            now[0] = t
            got.append(watch.observe(True, receiver.get_cycle_metrics()["cycles"], BuiltinCommands._queue_size(q)))
        if orphaned:
            assert receiver.get_cycle_metrics()["cycles"] == 0
            assert got == [[], [], [R]]
        else:
            assert receiver.get_cycle_metrics()["cycles"] == 3
            assert got == [[], [], []]
    finally:
        stop.set()
        thread.join(5)
        q.cancel_join_thread()
        q.close()
    assert not thread.is_alive()


@pytest.mark.parametrize(
    ("items", "cycles_delta"),
    [
        ([build_marker({"frame_id": 1}, reason="lag", source="up")], 0),
        ([{"frame_id": 2}], 1),
    ],
    ids=["marker_only", "frame"],
)
def test_progress_count_on_real_run_loop(items: list[dict], cycles_delta: int) -> None:
    sent: list[Any] = []
    executor = PipelineExecutor(
        plugins=[HzPass()], chain_targets=["next"], shm_middleware=None, send_fn=lambda *a, **_kw: sent.append(a)
    )
    chain: queue.Queue = queue.Queue()
    before_progress = executor.progress_count
    before_cycles = executor.get_cycle_metrics()["cycles"]
    chain.put(items)
    stop = threading.Event()
    thread = threading.Thread(target=executor.run_loop, args=(chain, stop, threading.Event()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and executor.progress_count == before_progress:
        time.sleep(0.02)
    stop.set()
    thread.join(5)
    assert not thread.is_alive()
    assert executor.progress_count - before_progress == 1
    assert executor.get_cycle_metrics()["cycles"] - before_cycles == cycles_delta


# --------------------------------------------------------------------------- #
# REDS 10. Проводка настоящего GenericProcess
# --------------------------------------------------------------------------- #


class _FakeQueueRegistry:
    def send_to_queue(self, *_a: Any, **_kw: Any) -> bool:
        return True

    def register_process_queues(self, *_a: Any, **_kw: Any) -> None: ...


class _Harness:
    """Настоящий ``GenericProcess.initialize()``; фейковый только транспорт; ни один воркер не стартует."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, extra_config: dict) -> None:
        self.now = [1000.0]
        self.size_calls = 0
        self.warnings: list[str] = []
        monkeypatch.setattr(iw, "_clock", lambda: self.now[0])

        def queue_size(_q: Any) -> int:
            self.size_calls += 1
            return 5

        monkeypatch.setattr(BuiltinCommands, "_queue_size", staticmethod(queue_size))

        config = {"config": {"plugins": _PLUGINS, "chain_targets": [], **extra_config}}
        proc = GenericProcess(name="recog", config=config)

        def init_queues() -> None:
            proc.queues = {"data": object()}
            proc.queue_registry = _FakeQueueRegistry()
            proc.memory_manager = None

        original_managers = proc._init_managers

        def init_managers() -> None:
            original_managers()
            create = proc.worker_manager.create_worker

            def create_stopped(*args: Any, **kwargs: Any) -> bool:
                kwargs["auto_start"] = False
                return create(*args, **kwargs)

            proc.worker_manager.create_worker = create_stopped

        original_warning = proc._log_warning

        def log_warning(message: str, **kwargs: Any) -> None:
            self.warnings.append(message)
            original_warning(message, **kwargs)

        proc._init_queues = init_queues  # type: ignore[method-assign]
        proc._init_managers = init_managers  # type: ignore[method-assign]
        proc._log_warning = log_warning  # type: ignore[method-assign]
        self.proc = proc
        assert proc.initialize() is True
        proc._run_event = threading.Event()
        proc._run_event.set()
        proc._readiness_announced = True
        proc._current_process_status = "running"

    def snapshot_at(self, t: float) -> list[dict]:
        self.now[0] = t
        self.proc._refresh_readiness_snapshot()
        return [r for r in self.proc._readiness_snapshot["reasons"] if r["source"] in ("inbox", "pipeline")]


@pytest.fixture
def make_process(monkeypatch: pytest.MonkeyPatch):
    made: list[GenericProcess] = []

    def make(extra_config: dict) -> _Harness:
        harness = _Harness(monkeypatch, extra_config)
        made.append(harness.proc)
        return harness

    yield make
    for proc in made:
        proc.shutdown()


@pytest.mark.timeout(60)
def test_generic_process_wiring(make_process) -> None:
    h = make_process({"inbox_stall_s": 15.0})
    proc = h.proc
    assert h.snapshot_at(1000.0) == []
    assert h.snapshot_at(1014.5) == []
    assert h.snapshot_at(1015.0) == [R]
    assert proc._readiness_snapshot["reasons"][0] == R
    assert proc._readiness_snapshot["ready"] is True

    def silent(start: float) -> None:
        assert [h.snapshot_at(start + dt) for dt in (0.0, 15.0, 16.0)] == [[], [], []]

    proc._run_event.clear()  # СТОП системы
    silent(2000.0)
    proc._run_event.set()

    proc._readiness_announced = False
    proc._current_process_status = "ready"
    silent(3000.0)
    proc._readiness_announced = True

    proc._current_process_status = ProcessStatus.PAUSED.value
    silent(4000.0)
    proc._current_process_status = "running"

    # Обе очереди стоят: только «обработка стоит».
    proc._chain_queue.put([{"frame_id": 1}])
    proc._chain_queue.put([{"frame_id": 2}])
    assert h.snapshot_at(5000.0) == []
    assert h.snapshot_at(5015.0) == [E]
    assert proc._readiness_snapshot["reasons"][0] == E


@pytest.mark.timeout(60)
def test_generic_process_without_key_reads_nothing(make_process) -> None:
    h = make_process({})
    assert h.proc._inbox_watch is None
    assert h.proc._pipeline_watch is None
    for t in (1000.0, 1015.0, 1030.0):
        assert h.snapshot_at(t) == []
    assert h.size_calls == 0


@pytest.mark.timeout(60)
def test_generic_process_bad_key_warns_once(make_process) -> None:
    h = make_process({"inbox_stall_s": "abc"})
    assert h.proc._inbox_watch is None
    assert h.proc._pipeline_watch is None
    assert len([w for w in h.warnings if "inbox_stall_s" in w]) == 1
