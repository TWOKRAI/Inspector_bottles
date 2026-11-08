# -*- coding: utf-8 -*-
"""Task 1.3 — авторские стражи teamlead волны ``last`` (не RED; красные только под инъекцией).

С1: корень PM и спавнер берут ``has_last`` из ``processes_config``: корень (9,0, 1,0), внешний join 10,5;
    без ``last`` — 7,0 и 8,5 (инъекция (2) «``has_last`` всегда ``False``»).
С2: срок ``force`` 0,5 с на топологии с ``last`` — ``stop_event`` обеим волнам на первом проходе, ``terminate``
    детям ``main`` не раньше 0,5 с (срок, переданный группе, = срок области, зажатый PM).
С3: ``ChildProcessStop.poll`` — один проход без ожидания: ``(True, 0.0)`` / ``(False, 0.0)`` /
    ``(None, pause ≤ poll_s)``.
С4: вариант (А) при ``main``, игнорирующем и ``terminate``: сигнал ``last`` в [5,0; 5,1] — раньше ``kill`` ``main``.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from ..core.child_process_stop import ChildProcessStop
from ..core.process_registry import ProcessRegistry
from ..core.stop_budget import stop_budget
from ..launcher.spawner import ProcessSpawner
from ..process.process_manager_process import ProcessManagerProcess
from .test_stop_wave_last import _run_registry_group, _spawn, farm  # noqa: F401 — фикстура farm

_WITH_LAST = {"gui": {"class": "x.Gui", "stop_wave": "last"}, "cam": {"class": "x.Cam"}}
_WITHOUT_LAST = {"gui": {"class": "x.Gui", "stop_wave": "late"}, "cam": {"class": "x.Cam"}}


# --------------------------------------------------------------------------- #
# С1: корень PM и спавнер
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("processes_config", "root", "children_s"),
    [
        pytest.param(_WITH_LAST, (9.0, 1.0), 7.0, id="with-last"),
        pytest.param(_WITHOUT_LAST, (7.0, 1.0), 5.0, id="invalid-wave-no-last"),
    ],
)
def test_pm_root_budget_from_processes_config(processes_config: dict, root: tuple, children_s: float) -> None:
    pm = ProcessManagerProcess(config={"shutdown_timeout": 5.0, "processes_config": processes_config})
    runner_budget = stop_budget(5.0)  # раннер шлёт пять ключей: last_wave_s PM считает сам
    pm.attach_stop_budget(runner_budget)
    assert pm._root_budget(runner_budget) == root
    budget = pm._budget()
    assert budget["pm_graceful_s"] + budget.get("last_wave_s", 0.0) == children_s


@pytest.mark.parametrize(
    ("processes_config", "outer_s"),
    [pytest.param(_WITH_LAST, 10.5, id="with-last"), pytest.param(_WITHOUT_LAST, 8.5, id="no-last")],
)
def test_spawner_outer_join_from_processes_config(processes_config: dict, outer_s: float) -> None:
    spawner = ProcessSpawner(processes_config=processes_config, stop_timeout=5.0)
    process = MagicMock()
    process.is_alive.side_effect = [True] + [False] * 10  # жив до join, вышел к его концу
    spawner._process = process
    spawner.stop()
    assert process.join.call_args_list[0].kwargs["timeout"] == outer_s


# --------------------------------------------------------------------------- #
# С2: срок force 0,5 с
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_force_short_deadline_signals_both_waves_first_pass(farm) -> None:  # noqa: F811
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    main = _spawn(registry, farm, "hung", wave=None, exit_after_s=8.0)
    last = _spawn(registry, farm, "gui", wave="last", exit_after_s=8.0)

    t0 = time.monotonic()
    group = registry.children_stop(mark_reader_gone=False)
    box: dict[str, Any] = {}

    def body() -> None:
        group.request_stop()
        box["ok"] = group.join_until(t0 + 0.5)

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(10.0)
    assert not thread.is_alive()
    time.sleep(0.05)  # двойник замечает событие опросом 2 мс

    assert box["ok"] is False
    assert group.wave == "last"
    assert main.t_signal is not None and main.t_signal - t0 <= 0.1
    assert last.t_signal is not None and last.t_signal - t0 <= 0.1, "last не сигналлен на первом проходе"
    assert main.t_terminate is not None and main.t_terminate - t0 >= 0.5, "terminate main раньше срока force"


# --------------------------------------------------------------------------- #
# С3: ChildProcessStop.poll
# --------------------------------------------------------------------------- #


class _Proc:
    def __init__(self, alive: bool) -> None:
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False


def test_poll_one_pass_without_wait() -> None:
    idle_calls: list[float] = []
    alive = _Proc(True)
    stop = ChildProcessStop({"a": alive}, {"a": threading.Event()}, poll_s=0.05, idle=idle_calls.append)
    stop.request_stop()

    t = time.monotonic()
    result, pause = stop.poll(t + 10.0)
    assert result is None and 0.0 <= pause <= 0.05
    assert time.monotonic() - t < 0.05, "poll ждал"
    assert idle_calls == [], "poll не зовёт idle: ожидание — дело wait()"

    assert stop.poll(time.monotonic() - 1.0) == (False, 0.0)  # срок вышел
    alive.alive = False
    assert stop.poll(time.monotonic() + 10.0) == (True, 0.0)

    stop.wait(0.01)
    assert idle_calls == [0.01]


# --------------------------------------------------------------------------- #
# С4: вариант (А), main игнорирует и terminate
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_last_signalled_by_time_before_main_kill(farm) -> None:  # noqa: F811
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    main = _spawn(registry, farm, "hung", wave=None, exit_after_s=8.0, dies_on_terminate=False)
    last = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3)

    t0, ok = _run_registry_group(registry)

    assert ok is True
    assert last.t_signal is not None and 5.0 <= last.t_signal - t0 <= 5.1
    assert main.t_kill is not None and last.t_signal < main.t_kill
    assert last.terminate_calls == 0 and last.kill_calls == 0
    assert registry.stop_outcome("gui") == "exited"
    assert registry.stop_outcome("hung") == "killed"
