# -*- coding: utf-8 -*-
"""Task 1.2 (`plans/lifecycle-stop-ownership.md`) — авторские тесты внутренних опасностей
метки «читатель ушёл», которую ставит PM (ADR-PMM-030).

Акцептанс (что метка ставится/снимается вообще) — у независимого тестера в
``test_pm_marks_gone_reader_acceptance.py``. Здесь — то, что видно только изнутри
механизма: КОГДА ставится метка относительно смерти, кого она обходит, и что сбой
метки не ломает остановку.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from typing import Any, Callable, List
from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.process_manager_module.runner.process_runner import (
    run_process_function,
)
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..core.process_registry import ProcessRegistry
from ..process.process_manager_process import ProcessManagerProcess


class _ReaderSleepsForever:
    """Не смотрит на stop_event — регистр вынужден дойти до terminate."""

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        time.sleep(120)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _ReaderHonorsStop(_ReaderSleepsForever):
    def run(self) -> None:
        pass


def _class_path(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _bounded(fn: Callable[[], Any], deadline_s: float) -> Any:
    """Выполнить ``fn`` в daemon-потоке с дедлайном — зависание = падение, а не висящий прогон."""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переброс в тестовый поток
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(deadline_s)
    assert not t.is_alive(), f"вызов не завершился за {deadline_s}s"
    if "error" in box:
        raise box["error"]
    return box.get("value")


class _MarkWatcher:
    """Фоновый опрос метки: фиксирует, был ли pid читателя ещё в таблице процессов
    в момент, когда метка впервые стала видна. ``os.kill(pid, 0)`` не реапит, в
    отличие от ``Process.is_alive`` из второго потока."""

    def __init__(self, q, pid: int) -> None:
        self._q = q
        self._pid = pid
        self._stop = threading.Event()
        self.seen_mark = False
        self.pid_present_at_mark: bool | None = None
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._q.is_reader_gone():
                self.seen_mark = True
                try:
                    os.kill(self._pid, 0)
                    self.pid_present_at_mark = True
                except ProcessLookupError:
                    self.pid_present_at_mark = False
                return
            time.sleep(0.001)

    def close(self) -> None:
        self._stop.set()
        self._t.join(2.0)


class _FakeProcess:
    """Процесс без ОС: ``dies_on`` — на каком сигнале умирает (None — бессмертен)."""

    def __init__(self, name: str, dies_on: str | None) -> None:
        self.name = name
        self.pid = 1
        self._alive = True
        self._dies_on = dies_on

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        pass

    def terminate(self) -> None:
        if self._dies_on == "terminate":
            self._alive = False

    def kill(self) -> None:
        if self._dies_on == "kill":
            self._alive = False


def _srm_with(*names: str) -> SharedResourcesManager:
    srm = SharedResourcesManager()
    assert srm.initialize()
    for name in names:
        assert srm.register_process(name, {"queues": {"data": {}}})
    return srm


def _q(srm: SharedResourcesManager, name: str):
    return srm.queue_registry.get_process_queues(name)["data"]


def _close(*queues) -> None:
    for q in queues:
        try:
            q.close()
            q.cancel_join_thread()
        except Exception:
            pass


def _kill(proc) -> None:
    if proc is not None and proc.is_alive():
        proc.kill()
        proc.join(3.0)


# ---------------------------------------------------------------------------


def test_mark_only_after_confirmed_death() -> None:
    """Ломается, если метку ставить ДО terminate/kill-результата (например, сразу после
    ``ev.set()`` или после graceful-join, не дождавшись смерти): живой читатель с меткой —
    писатели отпускают feeder посреди кадра, который он ещё прочтёт битым."""
    ctx = multiprocessing.get_context("spawn")
    srm = _srm_with("Reader")
    q = _q(srm, "Reader")
    registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
    stop = ctx.Event()
    reader = ctx.Process(
        target=run_process_function,
        args=(
            _class_path(_ReaderSleepsForever),
            "Reader",
            stop,
            {"queues": {"data": q}, "config": {}, "custom": {}},
            None,
        ),
        name="Reader",
    )
    registry.add_process(reader)
    registry._stop_events["Reader"] = stop
    watcher = None
    try:
        reader.start()
        time.sleep(0.3)
        watcher = _MarkWatcher(q, reader.pid)
        assert _bounded(lambda: registry.stop_one("Reader", timeout=0.3), 10.0) is True
        time.sleep(0.05)
        assert watcher.seen_mark is True
        assert watcher.pid_present_at_mark is False, "метка стала видна, пока pid читателя ещё существовал"
    finally:
        if watcher:
            watcher.close()
        _kill(reader)
        _close(q)


def test_survivor_is_not_marked_by_stop_one() -> None:
    """Ломается, если маркировать по «эскалация пройдена», а не по результату: процесс,
    переживший kill, всё ещё читает — метка на нём = порча его потока."""
    srm = _srm_with("Immortal")
    q = _q(srm, "Immortal")
    registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
    registry.add_process(_FakeProcess("Immortal", dies_on=None))
    registry._stop_events["Immortal"] = multiprocessing.Event()
    try:
        assert registry.stop_one("Immortal", timeout=0.01) is False
        assert q.is_reader_gone() is False
    finally:
        _close(q)


def test_stop_all_marks_straggler_but_not_survivor() -> None:
    """Системный путь (``stop_all`` → ``stop_many``) с отстающим: ломается, если метки
    ставятся только на graceful-вышедших (straggler, убитый terminate, остался бы без
    метки — его собственный хук не отработал) или на всех подряд (включая выжившего)."""
    srm = _srm_with("Straggler", "Immortal")
    q_s, q_i = _q(srm, "Straggler"), _q(srm, "Immortal")
    registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
    registry.add_process(_FakeProcess("Straggler", dies_on="terminate"))
    registry.add_process(_FakeProcess("Immortal", dies_on=None))
    try:
        results = registry.stop_all(timeout=0.01)
        assert results == {"Straggler": True, "Immortal": False}
        assert q_s.is_reader_gone() is True
        assert q_i.is_reader_gone() is False
    finally:
        _close(q_s, q_i)


def test_restart_never_exposes_mark_on_reused_queue() -> None:
    """Ломается, если ``restart_process`` остановит старое воплощение с меткой (дефолт
    ``stop_process``) и полагается на снятие в ``create_and_register``: между stop и
    новым спавном метка видна писателям — они отпускают feeder, и в переиспользуемом
    pipe остаётся оборванный кадр для нового воплощения."""
    srm = _srm_with("Reader")
    q = _q(srm, "Reader")
    registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
    old = registry.create_and_register("Reader", _class_path(_ReaderHonorsStop), {"queues": {"data": {}}})
    assert old is not None

    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.shared_resources = None
    pm.config = {}
    pm._system_stop_event = None
    pm._process_configs = {"Reader": {"class": _class_path(_ReaderHonorsStop), "queues": {"data": {}}}}
    pm._process_registry = registry
    pm._wire_reissue_enabled = lambda: False
    pm._process_queue_ids = lambda name: {}
    pm.get_config = lambda k: {"stop_process_timeout": 3.0, "start_ready_timeout_s": 0}.get(k)
    for attr in (
        "_bump_incarnation",
        "_priority",
        "_mark_instance_started",
        "_wait_processes_ready",
        "_bump_routing_epoch",
        "_broadcast_routing_refresh",
        "_publish_process_identity",
        "_replay_telemetry_runtime_delta",
    ):
        setattr(pm, attr, MagicMock())
    pm._instance_restarts = {}
    pm._log_info = pm._log_error = pm._log_warning = lambda *a, **k: True

    # Окно «stop -> спавн» короче миллисекунды — фоновый опрос его не ловит (проверено
    # инъекцией). Снимок метки берётся ровно в точке окна: на входе в create_and_register,
    # то есть после остановки старого воплощения и до снятия метки при рождении.
    at_birth: List[bool] = []
    real_create = registry.create_and_register

    def create_spy(*args: Any, **kwargs: Any):
        at_birth.append(q.is_reader_gone())
        return real_create(*args, **kwargs)

    registry.create_and_register = create_spy  # type: ignore[method-assign]
    try:
        old.start()
        time.sleep(0.3)
        assert _bounded(lambda: pm.restart_process("Reader"), 20.0) is True
        assert at_birth == [False], f"метка на переиспользуемой очереди между stop и спавном: {at_birth}"
        assert q.is_reader_gone() is False
    finally:
        _kill(old)
        _kill(registry.get_process_by_name("Reader"))
        _close(q)


def test_marking_failure_does_not_break_stop() -> None:
    """Ломается, если исключение из ``queue_registry`` вылетает из ``stop_one``/
    ``stop_many``: подтверждённая остановка превратилась бы в сбой switch/shutdown из-за
    вторичной метки (cleanup SHM не случился бы)."""
    broken = MagicMock()
    broken.get_process_queues.side_effect = RuntimeError("registry is gone")
    registry = ProcessRegistry(queue_registry=broken)
    registry.add_process(_FakeProcess("A", dies_on="terminate"))
    registry.add_process(_FakeProcess("B", dies_on="terminate"))
    assert registry.stop_one("A", timeout=0.01) is True
    assert registry.stop_many(["B", "Missing"], timeout=0.01) == {"B": True, "Missing": True}
    assert broken.get_process_queues.call_count >= 3  # метку действительно пытались ставить


# ---------------------------------------------------------------------------
# Итерация 2 (живой стенд): метка в stop_many ставится по мере подтверждения смерти,
# а не после всей эскалации — иначе писатель, ждущий в хуке метку мёртвого соседа,
# доживает до terminate.
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

from .test_pm_marks_gone_reader_acceptance import (  # noqa: E402
    _ReaderExitsImmediately,
    _SendBigFrameThenWaitForStop,
)


@pytest.mark.parametrize(
    "reader_kind, reader_first",
    [("dead", True), ("dead", False), ("honors_stop", False)],
    ids=["dead-reader-first", "dead-reader-last", "reader-exits-on-stop-listed-last"],
)
def test_stop_many_unblocks_writer_of_dead_reader_gracefully(reader_kind: str, reader_first: bool) -> None:
    """Живой случай (SIGKILL gui → system.shutdown): писатель висит в хуке выхода над кадром
    для уже мёртвого читателя. Ломается, если ``stop_many`` маркирует только после всей
    эскалации graceful→terminate→kill: писатель не выходит в graceful-окне, его терминируют
    (exitcode -15), а ``stop_many`` длится ≥ timeout. Вариант «читатель выходит по stop, стоит
    ПОСЛЕДНИМ» ловит последовательный блокирующий join на писателе: смерть читателя в том же
    окне не замечается, пока не истечёт дедлайн."""
    ctx = multiprocessing.get_context("spawn")
    srm = _srm_with("Reader")
    q = _q(srm, "Reader")
    registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
    reader_cls = _ReaderExitsImmediately if reader_kind == "dead" else _ReaderHonorsStop
    r_stop, w_stop = ctx.Event(), ctx.Event()
    reader = ctx.Process(
        target=run_process_function,
        args=(_class_path(reader_cls), "Reader", r_stop, {"queues": {"data": q}, "config": {}, "custom": {}}, None),
        name="Reader",
    )
    writer = ctx.Process(
        target=run_process_function,
        args=(
            _class_path(_SendBigFrameThenWaitForStop),
            "Writer",
            w_stop,
            {"queues": {}, "config": {}, "custom": {}, "routing_map": {"Reader": {"data": q}}},
            None,
        ),
        name="Writer",
    )
    registry.add_process(reader)
    registry.add_process(writer)
    registry._stop_events.update({"Reader": r_stop, "Writer": w_stop})
    names = ["Reader", "Writer"] if reader_first else ["Writer", "Reader"]
    try:
        reader.start()
        writer.start()
        time.sleep(0.5)  # writer положил 1 MiB; читатель не читает
        if reader_kind == "dead":
            reader.join(5.0)
            assert not reader.is_alive(), "подготовка: читатель не вышел сам"
        t0 = time.monotonic()
        results = _bounded(lambda: registry.stop_many(names, timeout=5.0), 20.0)
        elapsed = time.monotonic() - t0
        assert results == {"Reader": True, "Writer": True}
        assert writer.exitcode == 0, f"писатель не вышел штатно (exitcode={writer.exitcode}) — его добивали"
        assert elapsed < 2.0, f"stop_many длился {elapsed:.3f}s при timeout=5.0"
    finally:
        _kill(reader)
        _kill(writer)
        _close(q)


# ---------------------------------------------------------------------------
# Итерация 3 (ревью): системный стоп посреди рестарта; метка — только своему воплощению.
# ---------------------------------------------------------------------------


def test_system_stop_mid_restart_refuses_the_spawn() -> None:
    """Сценарий ревьюера: ``restart_process`` в потоке уже внутри stop-фазы (старое воплощение
    игнорирует stop), в этот момент взводится системный стоп и параллельно идёт ``stop_all``.
    Ломается, если отказ проверяется только на входе ``restart_process``: новое воплощение
    спавнится ПОСЛЕ системного стопа, живёт, а ``stop_all`` метит его переиспользованную очередь."""
    ctx = multiprocessing.get_context("spawn")
    sys_stop = ctx.Event()
    srm = _srm_with("Reader")
    q = _q(srm, "Reader")
    registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm, system_stop_event=sys_stop)
    cp = _class_path(_ReaderSleepsForever)
    old = registry.create_and_register("Reader", cp, {"queues": {"data": {}}})
    assert old is not None
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.shared_resources = None
    pm.config = {}
    pm._system_stop_event = sys_stop
    pm._process_configs = {"Reader": {"class": cp, "queues": {"data": {}}}}
    pm._process_registry = registry
    pm._wire_reissue_enabled = lambda: False
    pm._process_queue_ids = lambda name: {}
    pm.get_config = lambda k: {"stop_process_timeout": 0.5, "start_ready_timeout_s": 0}.get(k)
    for attr in (
        "_bump_incarnation",
        "_priority",
        "_mark_instance_started",
        "_wait_processes_ready",
        "_bump_routing_epoch",
        "_broadcast_routing_refresh",
        "_publish_process_identity",
        "_replay_telemetry_runtime_delta",
    ):
        setattr(pm, attr, MagicMock())
    pm._instance_restarts = {}
    pm._log_info = pm._log_error = pm._log_warning = lambda *a, **k: True

    box: dict = {}
    t = threading.Thread(target=lambda: box.setdefault("r", pm.restart_process("Reader")), daemon=True)
    new = None
    try:
        old.start()
        time.sleep(0.5)
        t.start()
        time.sleep(0.1)  # restart внутри stop_process: старое воплощение игнорирует stop
        sys_stop.set()
        _bounded(lambda: registry.stop_all(timeout=0.5), 15.0)
        t.join(15.0)
        assert not t.is_alive(), "restart_process не завершился"
        new = registry.get_process_by_name("Reader")
        assert box.get("r") is False, f"restart_process после системного стопа вернул {box.get('r')!r}"
        assert new is None or new is old, "после системного стопа зарегистрировано новое воплощение"
        assert not old.is_alive()
    finally:
        for proc in (old, new):
            if proc is not None and proc.pid is not None:
                _kill(proc)
        _close(q)


class _SwapOnTerminate(_FakeProcess):
    """Умирает на terminate и в тот же момент подменяет себя в реестре живым процессом с тем
    же именем — «новое воплощение зарегистрировано, пока стоп подтверждал смерть старого»."""

    def __init__(self, name: str, registry: ProcessRegistry) -> None:
        super().__init__(name, dies_on="terminate")
        self._registry = registry
        self.successor = _FakeProcess(name, dies_on=None)

    def terminate(self) -> None:
        super().terminate()
        self._registry.remove_process(self.name)
        self._registry.add_process(self.successor)


class _SwapOnTerminateToUnstarted(_SwapOnTerminate):
    """Как :class:`_SwapOnTerminate`, но преемник — настоящий ``Process``, ещё НЕ запущенный:
    ``create_and_register`` уже снял метку, ``process.start()`` ещё впереди (restart, фаза create
    switch'а). У такого ``is_alive()`` — False, хотя это будущий живой читатель."""

    def __init__(self, name: str, registry: ProcessRegistry) -> None:
        super().__init__(name, registry)
        self.successor = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(0,), name=name)


def test_mark_skips_registered_but_not_yet_started_successor() -> None:
    """Ломается, если «зарегистрированный не жив» считается мёртвым без проверки, что он вообще
    запускался: незапущенный преемник получает метку и стартует с ней (ревью ведущего, итерация 3)."""
    srm = _srm_with("Reader")
    q = _q(srm, "Reader")
    try:
        for stop in ("stop_one", "stop_many"):
            registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
            registry.add_process(_SwapOnTerminateToUnstarted("Reader", registry))
            if stop == "stop_one":
                assert registry.stop_one("Reader", timeout=0.01) is True
            else:
                assert registry.stop_many(["Reader"], timeout=0.01) == {"Reader": True}
            assert registry.get_process_by_name("Reader").pid is None
            assert q.is_reader_gone() is False, f"{stop}: метка на очереди ещё не запущенного преемника"
    finally:
        _close(q)


def test_mark_skips_name_now_held_by_a_live_incarnation() -> None:
    """Ломается, если метка ставится по ИМЕНИ, а не по наблюдённому мёртвым воплощению: живой
    преемник с тем же именем получает метку — его писатели отпускают feeder посреди кадра."""
    srm = _srm_with("Reader")
    q = _q(srm, "Reader")
    try:
        for stop in ("stop_one", "stop_many"):
            registry = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm)
            registry.add_process(_SwapOnTerminate("Reader", registry))
            if stop == "stop_one":
                assert registry.stop_one("Reader", timeout=0.01) is True
            else:
                assert registry.stop_many(["Reader"], timeout=0.01) == {"Reader": True}
            assert registry.get_process_by_name("Reader").is_alive()
            assert q.is_reader_gone() is False, f"{stop}: метка на очереди живого преемника"
    finally:
        _close(q)
