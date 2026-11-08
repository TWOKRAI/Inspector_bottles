# -*- coding: utf-8 -*-
"""Task 1.3 — авторские стражи teamlead волны ``last`` (не RED; красные только под инъекцией).

С1: корень PM и спавнер берут ``has_last`` из ``processes_config``: корень (9,0, 1,0), внешний join 10,5;
    без ``last`` — 7,0 и 8,5 (инъекция (2) «``has_last`` всегда ``False``»).
С2: срок ``force`` 0,5 с на топологии с ``last`` — ``stop_event`` обеим волнам на первом проходе, ``terminate``
    детям ``main`` не раньше 0,5 с (срок, переданный группе, = срок области, зажатый PM).
С3: ``ChildProcessStop.poll`` — один проход без ожидания: ``(True, 0.0)`` / ``(False, 0.0)`` /
    ``(None, pause ≤ poll_s)``.
С4: вариант (А) при ``main``, игнорирующем и ``terminate``: сигнал ``last`` в [5,0; 5,1] — раньше ``kill`` ``main``.
С1 (усилен): ``budget_s`` ОТКРЫТОЙ области ``work/children`` настоящего PM после ``initialize()`` — 7,0 / 5,0
    (инъекция (7) «область без ``+ last_wave_s``»).
С5: групповой ``kill()`` фазы 3 до сигнала ``last``: ``kill`` зависшему ``main`` — через окно подтверждения после
    ``kill()`` группы, не сразу (инъекция (11)); ``last`` без сигнала не получает ни ``terminate``, ни ``kill``.
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
from .test_process_root_pm_hazards import _call_bounded
from .test_stop_wave_last import (  # noqa: F401 — фикстуры farm, make_wave_rig
    _RegistryLog,
    _run_registry_group,
    _spawn,
    farm,
    make_wave_rig,
)

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
    # Открыть настоящий корень: детей из processes_config не создавать, каталоги логов не трогать.
    pm._create_processes_from_config = lambda _cfg: None
    pm._sweep_orphaned_log_dirs = lambda _names: None
    assert pm.initialize() is True
    try:
        assert pm.lifetime_segments["work"]._names["children"].res.budget_s == children_s
    finally:
        done, _result, error = _call_bounded(pm.shutdown)
        assert done and error is None, repr(error)


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


# --------------------------------------------------------------------------- #
# С5: групповой kill() фазы 3 до сигнала last
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("until_s", "kill_lo"),
    [
        pytest.param(2.0, 1.0, id="until-2.0-kill-at-grace"),
        pytest.param(1.5, 0.5, id="until-1.5-kill-at-deadline-minus-confirm"),
    ],
)
@pytest.mark.timeout(60)
def test_group_kill_before_last_signal_waits_kill_confirm_window(farm, until_s: float, kill_lo: float) -> None:  # noqa: F811
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    main = _spawn(registry, farm, "hung", wave=None, exit_after_s=8.0, dies_on_terminate=False)
    last = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3)
    group = registry.children_stop(mark_reader_gone=False)
    box: dict[str, Any] = {}

    def body() -> None:
        group.request_stop()  # фаза 1: только main
        box["t_kill"] = time.monotonic()
        group.kill()  # фаза 3 сразу (фаза 2 пропущена): last ещё не сигналлен
        box["ok"] = group.join_until(box["t_kill"] + until_s)  # until фазы 3

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(15.0)
    assert not thread.is_alive()
    t_kill = box["t_kill"]

    assert box["ok"] is True
    assert main.t_terminate is not None and main.t_terminate - t_kill <= 0.1
    # kill_at = min(kill() + terminate_grace 1,0; until − kill_confirm 1,0)
    assert main.t_kill is not None and kill_lo <= main.t_kill - t_kill <= kill_lo + 0.1, (
        f"kill main через {main.t_kill - t_kill:.3f} с после kill() группы, ожидалось [{kill_lo}; {kill_lo + 0.1}]"
    )
    assert last.t_signal is not None and last.t_signal >= t_kill
    assert last.terminate_calls == 0 and last.kill_calls == 0
    assert registry.stop_outcome("hung") == "killed"
    assert registry.stop_outcome("gui") == "exited"


# --------------------------------------------------------------------------- #
# М1 (ревью r1): смерть last в основной волне метится в момент факта
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_last_child_death_during_main_wave_marked_at_once(farm) -> None:  # noqa: F811
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    _spawn(registry, farm, "worker", wave=None, exit_after_s=3.0)
    gui = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3)
    marks: dict[str, float] = {}
    registry._mark_confirmed_dead = lambda name, _proc: marks.setdefault(name, time.monotonic())
    group = registry.children_stop(mark_reader_gone=True)
    box: dict[str, Any] = {}
    group.set_wave_listener(lambda _wave, _d: box.setdefault("t_last", time.monotonic()))

    t0 = time.monotonic()
    killer = threading.Timer(0.5, gui._die, args=(0,))  # gui гибнет сам, без сигнала
    killer.start()

    def body() -> None:
        group.request_stop()
        box["ok"] = group.join_until(t0 + 7.0)

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    thread.join(15.0)
    killer.cancel()
    assert not thread.is_alive()

    assert box["ok"] is True
    assert 0.5 <= marks["gui"] - t0 <= 0.7, f"метка gui на {marks['gui'] - t0:.3f} с, ожидалось [0,5; 0,7]"
    assert registry.stop_outcome("gui") == "exited"
    assert gui.terminate_calls == 0 and gui.kill_calls == 0
    assert gui.t_signal is None, "мёртвому gui stop_event не взводится"
    assert box["t_last"] - t0 >= 3.0, "волна last сигналлена до выхода main"


# --------------------------------------------------------------------------- #
# М2 (ревью r1)
# --------------------------------------------------------------------------- #


def test_shift_deadline_skipped_on_force_and_after_done() -> None:
    """(а) Сдвиг ``deadline_at`` слушателем волны: есть при graceful, нет при ``force`` и после ``done``."""
    far = time.monotonic() + 60.0
    cases = [("graceful", None, None, True), ("force", 1.0, None, False), ("graceful", None, "done", False)]
    for mode, deadline_s, phase, shifted in cases:
        pm = ProcessManagerProcess(config={"shutdown_timeout": 5.0})
        assert pm._begin_system_stop(mode, "test", deadline_s) is True
        if phase is not None:
            pm._set_system_stop_phase(phase)
        before = pm._system_stop_snapshot()["deadline_at"]
        assert pm._shift_system_stop_deadline(far) is shifted, (mode, phase)
        after = pm._system_stop_snapshot()["deadline_at"]
        if shifted:
            assert after - before >= 50.0, (mode, phase, after - before)
        else:
            assert after == before, (mode, phase)


@pytest.mark.timeout(60)
def test_failing_wave_listener_does_not_break_stop(farm) -> None:  # noqa: F811
    """(б) Слушатель группы бросает — ERROR в лог реестра, стоп идёт; сбой сдвига срока PM — фаза ``last_wave``."""
    log = _RegistryLog()
    errors: list[str] = []
    log._log_error = lambda message, *a, **k: errors.append(str(message))
    registry = ProcessRegistry(logger=log, child_stop_budget=stop_budget(5.0))
    _spawn(registry, farm, "worker", wave=None, exit_after_s=0.3)
    gui = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3)

    def boom(_wave: str, _deadline: float) -> None:
        raise RuntimeError("listener boom")

    group = registry.children_stop(mark_reader_gone=False)
    group.set_wave_listener(boom)
    t0 = time.monotonic()
    group.request_stop()
    assert group.join_until(t0 + 7.0) is True
    assert gui.t_signal is not None
    assert registry.stop_outcome("gui") == "exited"
    assert any("слушатель волны last" in m for m in errors), errors

    from ..process.process_manager_process import _ChildrenStop

    pm = ProcessManagerProcess(config={"shutdown_timeout": 5.0})
    assert pm._begin_system_stop("graceful", "test", None) is True

    def shift_boom(_deadline: float) -> bool:
        raise RuntimeError("shift boom")

    pm._shift_system_stop_deadline = shift_boom
    _ChildrenStop(pm)._on_last_wave("last", time.monotonic() + 2.0)
    assert pm._system_stop_snapshot()["phase"] == "last_wave"


@pytest.mark.timeout(60)
def test_last_surviving_kill_gets_survived(farm) -> None:  # noqa: F811
    """(в) ``last`` переживает ``terminate`` и ``kill`` — итог ``survived`` (снимок выживших обеих сборок)."""
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    _spawn(registry, farm, "worker", wave=None, exit_after_s=0.2)
    gui = _spawn(registry, farm, "gui", wave="last", exit_after_s=60.0, dies_on_terminate=False)
    gui.kill = lambda: setattr(gui, "kill_calls", gui.kill_calls + 1)  # бессмертный: kill не убивает
    group = registry.children_stop(mark_reader_gone=False)
    t0 = time.monotonic()
    group.request_stop()
    assert group.join_until(t0 + 1.0) is False  # фаза 2
    group.kill()
    assert group.join_until(time.monotonic() + 2.0) is False  # фаза 3
    assert registry.stop_outcome("worker") == "exited"
    assert registry.stop_outcome("gui") == "survived"
    assert gui.terminate_calls >= 1 and gui.kill_calls >= 1
    gui._die(-9)


@pytest.mark.parametrize("kill_at_s", [pytest.param(None, id="before-last-signal"), pytest.param(1.0, id="after")])
@pytest.mark.timeout(60)
def test_group_kill_reaches_last_only_after_its_signal(farm, kill_at_s: float | None) -> None:  # noqa: F811
    """(г) ``kill()`` группы шлёт ``terminate`` ``last`` только после его сигнала: до сигнала — ничего,
    после (``kill()`` посреди фазы 2) — сразу, а не в срок области."""
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    wave_main = 8.0 if kill_at_s is None else 0.2
    main = _spawn(registry, farm, "worker", wave=None, exit_after_s=wave_main)
    # до сигнала: last выходит штатно (0,3 с после своего сигнала); после: живёт, пока не придёт terminate
    gui = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3 if kill_at_s is None else 60.0)
    group = registry.children_stop(mark_reader_gone=False)
    t0 = time.monotonic()
    group.request_stop()
    if kill_at_s is None:
        group.kill()  # до сигнала last
        time.sleep(0.2)
        assert gui.terminate_calls == 0 and gui.kill_calls == 0, "last получил эскалацию до своего сигнала"
        assert main.terminate_calls == 1
        assert group.join_until(time.monotonic() + 2.0) is True
        assert gui.terminate_calls == 0 and registry.stop_outcome("gui") == "exited"
        return
    box: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: box.setdefault("ok", group.join_until(t0 + 7.0)), daemon=True)
    thread.start()
    time.sleep(kill_at_s)
    assert gui.t_signal is not None, "предусловие: last сигналлен (main вышел на 0,2 с)"
    group.kill()  # посреди фазы 2, после сигнала last
    thread.join(15.0)
    assert not thread.is_alive()
    assert gui.t_terminate is not None and kill_at_s <= gui.t_terminate - t0 <= kill_at_s + 0.2, (
        f"terminate last на {gui.t_terminate and gui.t_terminate - t0}"
    )


@pytest.mark.timeout(120)
def test_hung_last_child_escalated_in_own_window_through_pm_area(farm, make_wave_rig) -> None:  # noqa: F811
    """(д) ``main`` вышел, ``last`` игнорирует ``stop_event`` и ``terminate``: ``terminate`` через окно 5,0 после его
    сигнала, ``kill`` через 1,0 после ``terminate``, итог ``killed``, корень закрыт раньше ``pm_total_s`` 9,0."""
    rig = make_wave_rig(5.0)
    rig.add_wave_child(farm, "worker", wave=None, exit_after_s=0.5)
    gui = rig.add_wave_child(farm, "gui", wave="last", exit_after_s=60.0, dies_on_terminate=False)
    t0 = time.monotonic()
    rig.pm.stop_event.set()
    assert rig.wait_root_closed(60.0)
    t_closed = time.monotonic() - t0

    assert gui.t_signal is not None and gui.t_signal - t0 <= 0.8
    # Допуск 0,05 снизу: двойник видит stop_event опросом 2 мс (t_signal позже request_stop), а t_terminate
    # пишется внутри terminate() после момента now, от которого считается kill_at.
    assert gui.t_terminate is not None and 4.95 <= gui.t_terminate - gui.t_signal <= 5.1
    assert gui.t_kill is not None and 0.95 <= gui.t_kill - gui.t_terminate <= 1.1
    assert rig.pm._process_registry.stop_outcome("gui") == "killed"
    assert t_closed < 9.0, f"корень закрыт за {t_closed:.2f} с"
