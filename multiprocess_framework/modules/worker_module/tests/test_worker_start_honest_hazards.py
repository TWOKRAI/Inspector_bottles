# -*- coding: utf-8 -*-
"""C-91, hazard-тесты автора: корневая проверка остановки в авто-рестарте (ADR-WRK-007).

R7 (слепой набор) проверяет «после stop_worker -> True потоков нет». Этого не хватает:
если в ``_restart_worker_internal`` отключить сверку ``stop_event``, лишний поток T2
всё равно стартует, а страховочный цикл ``stop_worker`` его остановит, и R7 останется
зелёным. R11 закрепляет именно корень: T2 не стартует вообще, цель вызвана ровно один раз.

R12 — страховочный цикл ``stop_worker``: законный старт внутри ``join`` тоже остановлен.
R13 — итоговая запись STOPPED и перечитывание реестра в одном захвате замка.
R14 — ``Thread.start()`` бросил после настоящего старта: живой поток не теряется из реестра.
R15 — ``stop_worker(timeout=None)`` ждёт без срока, как ``join(None)``.

Любой вызов, способный зависнуть, идёт в daemon-потоке с дедлайном join.
"""

import itertools
import sys
import threading

import pytest

from multiprocess_framework.modules.worker_module import ThreadConfig, WorkerManager, WorkerStatus

_DEADLINE = 5.0
_COUNTER = itertools.count()


def _wait_until(predicate, timeout: float) -> bool:
    tick = threading.Event()
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        tick.wait(0.005)
        waited += 0.005
    return bool(predicate())


def _in_thread_join(ident: int) -> bool:
    frame = sys._current_frames().get(ident)
    while frame is not None:
        code = frame.f_code
        if code.co_name == "join" and code.co_filename.endswith("threading.py"):
            return True
        frame = frame.f_back
    return False


@pytest.mark.timeout(30)
def test_r11_stop_in_auto_restart_window_never_starts_second_thread():
    name = f"c91h{next(_COUNTER)}"
    mgr = WorkerManager(name)
    assert mgr.initialize() is True
    for level in ("debug", "info", "warning", "error"):
        setattr(mgr, f"_log_{level}", lambda *a, **kw: True)

    calls: list[int] = []
    release_all = threading.Event()  # уборка: отпускает цель, если она всё же стартовала второй раз

    def target(stop_event, pause_event):
        calls.append(threading.get_ident())
        if len(calls) == 1:
            raise RuntimeError("c91: преднамеренная ошибка цели")
        while not (stop_event.is_set() or release_all.is_set()):
            stop_event.wait(0.01)

    assert mgr.create_worker("w", target, ThreadConfig(restart_on_failure=True, max_restarts=3)) is True

    lc = mgr._lifecycle
    original = lc._restart_worker_internal
    in_window = threading.Event()
    release_window = threading.Event()

    def wrapper(worker_name, *a, **kw):
        in_window.set()
        release_window.wait(_DEADLINE)
        return original(worker_name, *a, **kw)

    lc._restart_worker_internal = wrapper
    box: dict = {}
    stopper = threading.Thread(
        target=lambda: box.setdefault("result", mgr.stop_worker("w", timeout=2.0)),
        name="c91h-stopper",
        daemon=True,
    )
    try:
        assert mgr.start_worker("w") is True
        assert in_window.wait(_DEADLINE), "предусловие: поток воркера вошёл в окно авто-рестарта"

        stopper.start()
        assert _wait_until(lambda: stopper.ident is not None and _in_thread_join(stopper.ident), 2.0), (
            "предусловие: stop_worker стоит в Thread.join, пока поток в окне авто-рестарта"
        )

        release_window.set()
        stopper.join(_DEADLINE)
        assert not stopper.is_alive(), "stop_worker завис после выхода из окна"

        assert box["result"] is True
        assert len(calls) == 1, (
            f"авто-рестарт стартовал второй поток после запроса остановки (вызовов цели: {len(calls)})"
        )
        assert mgr._worker_registry.get_status("w") == WorkerStatus.STOPPED
        live = [t for t in threading.enumerate() if t.name == f"{name}_w" and t.is_alive()]
        assert live == []
    finally:
        release_window.set()
        release_all.set()
        for t in list(threading.enumerate()):
            if t.name.startswith(name + "_"):
                t.join(2.0)


# ---------------------------------------------------------------------------
# R12–R15: общая обвязка
# ---------------------------------------------------------------------------


class _Env:
    def __init__(self):
        self.name = f"c91h{next(_COUNTER)}"
        self.mgr = WorkerManager(self.name)
        assert self.mgr.initialize() is True
        for level in ("debug", "info", "warning", "error"):
            setattr(self.mgr, f"_log_{level}", lambda *a, **kw: True)
        self.release = threading.Event()  # уборка: отпускает все цели

    def coop_target(self):
        calls: list[int] = []
        release = self.release

        def target(stop_event, pause_event):
            calls.append(threading.get_ident())
            while not (stop_event.is_set() or release.is_set()):
                stop_event.wait(0.005)

        target.calls = calls
        return target

    def live(self) -> list[threading.Thread]:
        name = f"{self.name}_w"
        return [t for t in threading.enumerate() if t.name == name and t.is_alive()]

    def status(self):
        return self.mgr._worker_registry.get_status("w")

    def cleanup(self):
        self.release.set()
        for t in list(threading.enumerate()):
            if t.name.startswith(self.name + "_"):
                t.join(2.0)


@pytest.fixture
def henv():
    e = _Env()
    try:
        yield e
    finally:
        e.cleanup()


def _call(fn, name: str = "c91h-call", deadline: float = _DEADLINE):
    """Вызов в daemon-потоке с дедлайном; итог ("ok", значение) или ("raised", имя класса)."""
    box: dict = {}

    def run():
        try:
            box["value"] = ("ok", fn())
        except Exception as exc:  # noqa: BLE001 — исход вызова проверяет тест
            box["value"] = ("raised", type(exc).__name__)

    t = threading.Thread(target=run, name=name, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с"
    return box["value"]


# ---------------------------------------------------------------------------
# R12 — страховочный цикл stop_worker
# ---------------------------------------------------------------------------


class _JoinThenStartProxy:
    """Поток в реестре: после настоящего join зовёт start_worker — законный старт T2
    между выходом прежнего потока и перечитыванием реестра в stop_worker."""

    def __init__(self, real, start):
        self._real = real
        self._start = start
        self.start_result = None

    def join(self, timeout=None):
        self._real.join(timeout)
        if self.start_result is None:
            self.start_result = self._start()

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.mark.timeout(30)
def test_r12_stop_also_stops_thread_started_during_join(henv):
    target = henv.coop_target()
    assert henv.mgr.create_worker("w", target, ThreadConfig()) is True
    assert henv.mgr.start_worker("w") is True
    info = henv.mgr._worker_registry.get("w")
    proxy = _JoinThenStartProxy(info["thread"], lambda: henv.mgr._lifecycle.start_worker("w"))
    info["thread"] = proxy

    result = _call(lambda: henv.mgr.stop_worker("w", timeout=2.0))

    assert proxy.start_result is True, "предусловие: старт внутри join прошёл, поток T2 создан"
    assert result == ("ok", True)
    assert henv.live() == [], "stop_worker -> True, а поток T2, стартовавший во время join, жив"
    assert henv.status() == WorkerStatus.STOPPED


# ---------------------------------------------------------------------------
# R13 — старт в хвосте stop_worker: STOPPED не пишется поверх живого потока
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r13_start_racing_final_stopped_write_keeps_status_truthful(henv):
    target = henv.coop_target()
    assert henv.mgr.create_worker("w", target, ThreadConfig()) is True
    assert henv.mgr.start_worker("w") is True
    registry = henv.mgr._worker_registry
    original_update = registry.update_status
    armed = threading.Event()
    armed.set()
    starter_box: dict = {}

    def trap(worker_name, status):
        # Ловушка на итоговую запись STOPPED внутри stop_worker: законный start_worker
        # из другого потока. Успевает, только если запись не под замком старта.
        if status == WorkerStatus.STOPPED and armed.is_set() and threading.current_thread().name == "c91h-stopper":
            armed.clear()
            starter = threading.Thread(
                target=lambda: starter_box.setdefault("result", henv.mgr.start_worker("w")),
                name="c91h-starter",
                daemon=True,
            )
            starter_box["thread"] = starter
            starter.start()
            starter.join(0.5)
            _wait_until(lambda: len(target.calls) >= 2, 0.5)  # обёртка T2 уже записала RUNNING
        return original_update(worker_name, status)

    registry.update_status = trap
    try:
        stop_result = _call(lambda: henv.mgr.stop_worker("w", timeout=2.0), name="c91h-stopper")
        assert "thread" in starter_box, "предусловие: ловушка сработала на записи STOPPED в stop_worker"
        starter_box["thread"].join(_DEADLINE)
        assert not starter_box["thread"].is_alive(), "start_worker завис"
    finally:
        registry.update_status = original_update

    assert stop_result == ("ok", True)
    assert starter_box["result"] is True
    assert len(henv.live()) == 1
    assert henv.status() == WorkerStatus.RUNNING, (
        "STOPPED при живом потоке: старт вклинился между перечитыванием и записью"
    )
    assert _call(lambda: henv.mgr.start_worker("w")) == ("ok", True), "старт после такой гонки залип в False"
    assert len(henv.live()) == 1
    assert _call(lambda: henv.mgr.stop_worker("w", timeout=2.0)) == ("ok", True)
    assert henv.live() == []
    assert henv.status() == WorkerStatus.STOPPED
    assert _call(lambda: henv.mgr.start_worker("w")) == ("ok", True)
    assert len(henv.live()) == 1


# ---------------------------------------------------------------------------
# R14 — Thread.start() бросил после настоящего старта
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r14_thread_start_raising_after_real_start_keeps_live_thread_in_registry(henv, monkeypatch):
    target = henv.coop_target()
    assert henv.mgr.create_worker("w", target, ThreadConfig()) is True
    worker_thread_name = f"{henv.name}_w"
    real_start = threading.Thread.start

    def start_then_raise(self):
        real_start(self)
        if self.name == worker_thread_name:
            raise RuntimeError("c91: start() бросил после настоящего старта")

    monkeypatch.setattr(threading.Thread, "start", start_then_raise)
    try:
        outcome = _call(lambda: henv.mgr.start_worker("w"))
    finally:
        monkeypatch.undo()

    assert outcome == ("raised", "RuntimeError")
    live = henv.live()
    assert len(live) == 1, "предусловие: поток реально стартовал"
    assert henv.mgr._worker_registry.get("w")["thread"] is live[0], "живой поток потерян из реестра"
    assert _call(lambda: henv.mgr.start_worker("w")) == ("ok", True)
    assert len(henv.live()) == 1, "следующий start_worker создал второй поток"
    assert _call(lambda: henv.mgr.stop_worker("w", timeout=2.0)) == ("ok", True)
    assert henv.live() == []


# ---------------------------------------------------------------------------
# R15 — stop_worker(timeout=None)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_r15_stop_worker_with_timeout_none_waits_without_deadline(henv):
    target = henv.coop_target()
    assert henv.mgr.create_worker("w", target, ThreadConfig()) is True
    assert henv.mgr.start_worker("w") is True

    assert _call(lambda: henv.mgr.stop_worker("w", timeout=None)) == ("ok", True)
    assert henv.live() == []
    assert henv.status() == WorkerStatus.STOPPED
