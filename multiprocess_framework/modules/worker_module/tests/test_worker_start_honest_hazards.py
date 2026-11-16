# -*- coding: utf-8 -*-
"""C-91, hazard-тесты автора: корневая проверка остановки в авто-рестарте (ADR-WRK-007).

R7 (слепой набор) проверяет «после stop_worker -> True потоков нет». Этого не хватает:
если в ``_restart_worker_internal`` отключить сверку ``stop_event``, лишний поток T2
всё равно стартует, а страховочный цикл ``stop_worker`` его остановит, и R7 останется
зелёным. R11 закрепляет именно корень: T2 не стартует вообще, цель вызвана ровно один раз.

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
