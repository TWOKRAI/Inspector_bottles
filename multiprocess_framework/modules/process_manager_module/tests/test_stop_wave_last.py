# -*- coding: utf-8 -*-
"""Task 1.3 (gui-graceful-close) — слепая приёмка: волна ``last`` системного стопа PM.

Написано ДО реализации по критериям приёмки брифа (REDS 1-10); DESIGN/FILES задачи и реализация не читались.

Контракт: процессы с ``stop_wave: last`` PM гасит только после основной волны ``main``; у волны ``last`` своё
окно ``last_wave_s`` (``LAST_WAVE_S = 2.0``), GUI не получает ``terminate``, пока PM ждёт зависшего соседа.

Обвязка:
  * ОС-процесс заменён двойником ``_FakeOsProcess`` (патч имени ``Process`` в модуле реестра): всё остальное —
    настоящие ``ProcessRegistry.create_and_register`` (волна читается из ``proc_dict`` самим реестром),
    ``children_stop`` -> ``ChildProcessStop`` (REDS 1, 2) и настоящий PM-оркестратор ``Rig`` из
    ``test_pm_responsive_during_children_stop`` с областью ``children`` корня (REDS 7, 8, 9);
  * двойник сам наблюдает свой НАСТОЯЩИЙ ``multiprocessing.Event`` (опрос 2 мс) и пишет моменты: сигнал
    ``stop_event`` (monotonic и wall), ``terminate``, ``kill``, смерть. Время выхода задаёт тест (``exit_after_s``
    после сигнала); «зависший» ребёнок живёт ``exit_after_s`` и умирает на ``terminate()`` (или только на ``kill()``);
  * время — ``time.monotonic()`` от старта группы / команды; ожидаемые значения — литералы из приёмки.

Всё, что может блокироваться, идёт в daemon-потоке с дедлайном join.

Что НЕ покрыто (см. отчёт): ``wave`` / ``set_wave_listener`` группы отдельным тестом; ``stop_wave`` в ответе
``supervision.status``; путь спавнера и внешний join с ``last_wave_s``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint

from ..core import process_registry as process_registry_module
from ..core.process_registry import ProcessRegistry
from ..core.stop_budget import stop_budget
from .test_pm_responsive_during_children_stop import Rig

REPO_ROOT = Path(__file__).resolve().parents[4]
PRESENTATION_PATH = REPO_ROOT / "multiprocess_prototype" / "frontend" / "presentation.yaml"

GROUP_DEADLINE_S = 7.0  # D = старт + 7,0: окно main (5,0) + окно last (2,0)
JOIN_GUARD_S = 25.0  # потолок ожидания потока группы: дальше «завис» = упавший ассерт
STATUS_POLL_S = 0.1


# --------------------------------------------------------------------------- #
# Двойник ОС-процесса
# --------------------------------------------------------------------------- #


class _FakeOsProcess:
    """ОС-процесс, чей выход управляется тестом.

    Живёт с момента создания. После сигнала ``stop_event`` умирает сам через ``exit_after_s``; ``terminate()``
    убивает его сразу, если ``dies_on_terminate``; ``kill()`` убивает всегда. Все моменты — в атрибутах.
    """

    def __init__(self, name: str, stop_event: Any, exit_after_s: float, dies_on_terminate: bool) -> None:
        self.name = name
        self.pid = 50000 + abs(hash(name)) % 1000
        self.exitcode: int | None = None
        self.stop_event = stop_event
        self._exit_after_s = exit_after_s
        self._dies_on_terminate = dies_on_terminate
        self._dead = threading.Event()
        self._lock = threading.Lock()
        self.t_signal: float | None = None
        self.t_signal_wall: float | None = None
        self.t_terminate: float | None = None
        self.t_kill: float | None = None
        self.t_dead: float | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._thread = threading.Thread(target=self._watch, daemon=True, name=f"fake-{name}")
        self._thread.start()

    def _watch(self) -> None:
        while not self._dead.is_set():
            if self.stop_event.is_set():
                break
            time.sleep(0.002)
        else:
            return
        self.t_signal = time.monotonic()
        self.t_signal_wall = time.time()
        if not self._dead.wait(self._exit_after_s):
            self._die(0)

    def _die(self, code: int) -> None:
        with self._lock:
            if self._dead.is_set():
                return
            self.exitcode = code
            self.t_dead = time.monotonic()
            self._dead.set()

    # ---- интерфейс mp.Process, нужный реестру ---------------------------------

    def start(self) -> None:
        return None

    def is_alive(self) -> bool:
        return not self._dead.is_set()

    def join(self, timeout: float | None = None) -> None:
        self._dead.wait(timeout)

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.t_terminate is None:
            self.t_terminate = time.monotonic()
        if self._dies_on_terminate:
            self._die(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        if self.t_kill is None:
            self.t_kill = time.monotonic()
        self._die(-9)


class _Farm:
    """Фабрика двойников: план по имени -> объект, который реестр получает вместо ``multiprocessing.Process``."""

    def __init__(self) -> None:
        self._plans: dict[str, tuple[float, bool]] = {}
        self.children: dict[str, _FakeOsProcess] = {}

    def plan(self, name: str, *, exit_after_s: float, dies_on_terminate: bool = True) -> None:
        self._plans[name] = (exit_after_s, dies_on_terminate)

    def factory(self, *, target: Any = None, args: tuple = (), kwargs: Any = None, name: str | None = None) -> Any:
        exit_after_s, dies_on_terminate = self._plans[str(name)]
        stop_event = args[2]  # run_process_function(class_path, name, stop_event, bundle, system_stop_event)
        child = _FakeOsProcess(str(name), stop_event, exit_after_s, dies_on_terminate)
        self.children[str(name)] = child
        return child

    def shutdown(self) -> None:
        for child in self.children.values():
            child._die(-9)


@pytest.fixture
def farm(monkeypatch):
    f = _Farm()
    monkeypatch.setattr(process_registry_module, "Process", f.factory)
    try:
        yield f
    finally:
        f.shutdown()


def _spawn(
    registry: ProcessRegistry,
    farm: _Farm,
    name: str,
    *,
    wave: str | None,
    exit_after_s: float,
    dies_on_terminate: bool = True,
) -> _FakeOsProcess:
    """Процесс через НАСТОЯЩИЙ ``create_and_register``: ``stop_wave`` едет в ``proc_dict`` верхнего уровня."""
    farm.plan(name, exit_after_s=exit_after_s, dies_on_terminate=dies_on_terminate)
    config: dict[str, Any] = {} if wave is None else {"stop_wave": wave}
    assert registry.create_and_register(name, "fake.Child", config) is not None, f"процесс {name} не создан"
    return farm.children[name]


def _run_registry_group(registry: ProcessRegistry) -> tuple[float, bool]:
    """``children_stop`` -> ``request_stop`` -> ``join_until(старт + 7,0)`` в daemon-потоке; ``(старт, итог)``."""
    t0 = time.monotonic()
    group = registry.children_stop(mark_reader_gone=False)
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            group.request_stop()
            box["ok"] = group.join_until(t0 + GROUP_DEADLINE_S)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = repr(exc)

    thread = threading.Thread(target=body, daemon=True, name="group-stop")
    thread.start()
    thread.join(JOIN_GUARD_S)
    assert not thread.is_alive(), "children_stop().join_until завис за дедлайн"
    assert "error" not in box, box["error"]
    return t0, bool(box["ok"])


# --------------------------------------------------------------------------- #
# REDS 1: last не получает сигнал, пока main не вышел
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_last_wave_child_not_signalled_until_main_done(farm) -> None:
    """``main`` выходит через 1,0 с после своего ``stop_event``: ``stop_event`` ``last`` не раньше выхода ``main``
    и не позже выхода ``main`` + 0,1 с."""
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    main = _spawn(registry, farm, "worker", wave=None, exit_after_s=1.0)
    last = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3)

    t0, ok = _run_registry_group(registry)

    assert main.t_dead is not None, "main-ребёнок не вышел"
    assert last.t_signal is not None, "last-ребёнок так и не получил stop_event"
    assert last.t_signal >= main.t_dead, (
        f"stop_event last взведён за {main.t_dead - last.t_signal:.3f} с до выхода main "
        f"(last: {last.t_signal - t0:.3f} с, main вышел: {main.t_dead - t0:.3f} с от старта)"
    )
    assert last.t_signal <= main.t_dead + 0.1, (
        f"stop_event last опоздал: {last.t_signal - main.t_dead:.3f} с после выхода main (допуск 0,1 с)"
    )
    assert ok is True, "join_until(старт + 7,0) не дождался обоих детей"


# --------------------------------------------------------------------------- #
# REDS 2: зависший main не отдаёт last под terminate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("main_ignores_terminate", "terminate_lo", "kill_expected"),
    [
        pytest.param(False, 5.0, False, id="main-dies-on-terminate"),
        pytest.param(True, 5.0, True, id="main-ignores-terminate-killed-at-6"),
    ],
)
@pytest.mark.timeout(60)
def test_hung_main_child_does_not_terminate_last_child(
    farm, main_ignores_terminate: bool, terminate_lo: float, kill_expected: bool
) -> None:
    """``main`` игнорирует ``stop_event`` (живёт 8 с): ``terminate`` ``main`` в [5,0; 5,1], ``stop_event`` ``last`` в
    [5,0; 5,1] (вариант (А): по времени ``D − last_wave_s``) — после смерти ``main``, если тот умер на ``terminate``,
    и до его смерти, если ``main`` игнорирует и ``terminate`` (``kill`` ``main`` в [6,0; 6,1]). ``last`` не получает
    ни ``terminate``, ни ``kill`` и заканчивает ``exited``."""
    registry = ProcessRegistry(logger=None, child_stop_budget=stop_budget(5.0))
    main = _spawn(registry, farm, "hung", wave=None, exit_after_s=8.0, dies_on_terminate=not main_ignores_terminate)
    last = _spawn(registry, farm, "gui", wave="last", exit_after_s=0.3)

    t0, ok = _run_registry_group(registry)

    assert main.t_terminate is not None, "main так и не получил terminate"
    assert terminate_lo <= main.t_terminate - t0 <= 5.1, (
        f"terminate main в {main.t_terminate - t0:.3f} с от старта, ожидалось [5,0; 5,1]"
    )
    if kill_expected:
        assert main.t_kill is not None, "main игнорирует terminate, а kill не пришёл"
        assert 6.0 <= main.t_kill - t0 <= 6.1, f"kill main в {main.t_kill - t0:.3f} с от старта, ожидалось [6,0; 6,1]"
        assert registry.stop_outcome("hung") == "killed"
    else:
        assert main.t_kill is None, "main умер на terminate, kill не нужен"
        assert registry.stop_outcome("hung") == "terminated"

    assert main.t_dead is not None and last.t_signal is not None
    # Вариант (А) (решение лида 2026-11-08): last сигналят по времени, в D − last_wave_s = 5,0, не дожидаясь конца
    # эскалации main. Без kill main умирает на terminate в 5,0 — сигнал last сразу после; с kill main живёт до 6,0,
    # а last уже сигналлен в 5,0.
    assert 5.0 <= last.t_signal - t0 <= 5.1, (
        f"stop_event last в {last.t_signal - t0:.3f} с от старта, ожидалось [5,0; 5,1]"
    )
    if kill_expected:
        assert last.t_signal < main.t_dead, "вариант (А): stop_event last должен уйти до смерти main (kill в 6,0)"
    else:
        assert last.t_signal >= main.t_dead, "stop_event last взведён до смерти main"
        assert last.t_signal <= main.t_dead + 0.1, f"stop_event last опоздал на {last.t_signal - main.t_dead:.3f} с"
    assert last.terminate_calls == 0, "last получил terminate от зависшего соседа"
    assert last.kill_calls == 0, "last получил kill от зависшего соседа"
    assert registry.stop_outcome("gui") == "exited"
    assert ok is True


# --------------------------------------------------------------------------- #
# REDS 3, 6: формула бюджета
# --------------------------------------------------------------------------- #


def test_budget_adds_2s_only_with_last() -> None:
    """Без ``last`` пять ключей и ``pm_total_s`` 7,0 / ``outer_s`` 8,5; с ``has_last=True`` — шесть, оба больше на 2,0,
    ``last_wave_s`` 2,0 последним ключом."""
    from ..core.stop_budget import LAST_WAVE_S

    assert LAST_WAVE_S == 2.0

    plain = stop_budget(5.0)
    assert len(plain) == 5, list(plain)
    assert plain["pm_total_s"] == 7.0
    assert plain["outer_s"] == 8.5

    with_last = stop_budget(5.0, has_last=True)
    assert len(with_last) == 6, list(with_last)
    assert with_last["pm_total_s"] == 9.0
    assert with_last["outer_s"] == 10.5
    assert with_last["last_wave_s"] == 2.0
    assert list(with_last)[-1] == "last_wave_s"


def test_no_last_children_keeps_old_budget_literals() -> None:
    """``has_last=False``: ровно пять прежних ключей в прежнем порядке, литералы 3,0 / 1,0 / 5,0 / 7,0 / 8,5."""
    budget = stop_budget(5.0, has_last=False)

    assert list(budget.items()) == [
        ("work_s", 3.0),
        ("infra_s", 1.0),
        ("pm_graceful_s", 5.0),
        ("pm_total_s", 7.0),
        ("outer_s", 8.5),
    ]


# --------------------------------------------------------------------------- #
# REDS 4, 5, 10: конфигурация волны
# --------------------------------------------------------------------------- #


def _proc_dict_of(process: dict[str, Any]) -> dict[str, Any]:
    """``dict`` процесса топологии -> ``proc_dict`` (``SystemBlueprint`` -> ``as_generic_config`` -> ``build``)."""
    blueprint = SystemBlueprint.model_validate({"name": "w", "processes": [process], "wires": []})
    (cfg,) = blueprint.build_configs()
    _name, proc_dict = cfg.build()
    return proc_dict


def test_blueprint_stop_wave_roundtrip_to_proc_dict() -> None:
    """``stop_wave: last`` доходит до верхнего уровня ``proc_dict``; ``main`` и отсутствие поля — ключа нет."""
    assert _proc_dict_of({"process_name": "gui", "stop_wave": "last"}).get("stop_wave") == "last"
    assert "stop_wave" not in _proc_dict_of({"process_name": "worker", "stop_wave": "main"})
    assert "stop_wave" not in _proc_dict_of({"process_name": "worker"})


def test_presentation_overlay_marks_gui_last() -> None:
    """После ``apply_presentation_overlay`` процесс ``gui`` несёт ``stop_wave: last``."""
    from multiprocess_prototype.backend.launch import apply_presentation_overlay

    with open(PRESENTATION_PATH, encoding="utf-8") as fh:
        overlay = yaml.safe_load(fh)
    topology = {
        "name": "t",
        "processes": [
            {"process_name": "cam", "plugins": []},
            {
                "process_name": "gui",
                "process_class": "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess",
                "plugins": [],
            },
        ],
        "wires": [],
    }

    patched = apply_presentation_overlay(topology, overlay)

    gui = next(p for p in patched["processes"] if p["process_name"] == "gui")
    assert gui.get("stop_wave") == "last", gui
    cam = next(p for p in patched["processes"] if p["process_name"] == "cam")
    assert "stop_wave" not in cam, "overlay пометил чужой процесс"


class _RegistryLog:
    """Логгер реестра (``_log_<level>``): копит WARNING."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def _log_warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.warnings.append(str(message))

    def _log_info(self, message: str, *args: Any, **kwargs: Any) -> None:
        return None

    _log_debug = _log_info
    _log_error = _log_info


def test_invalid_stop_wave_ignored_with_warning_without_value(farm) -> None:
    """``stop_wave: late``: ``as_generic_config`` не бросает; WARNING реестра называет ``stop_wave`` процесса и не
    содержит значения ``late``; процесс остаётся в волне ``main``."""
    proc_dict = _proc_dict_of({"process_name": "worker1", "stop_wave": "late"})  # не бросает
    farm.plan("worker1", exit_after_s=0.1)
    log = _RegistryLog()
    registry = ProcessRegistry(logger=log, child_stop_budget=stop_budget(5.0))

    assert registry.create_and_register("worker1", "fake.Child", proc_dict) is not None

    about_wave = [m for m in log.warnings if "stop_wave" in m]
    assert about_wave, f"в логе реестра нет WARNING про stop_wave: {log.warnings}"
    assert any("worker1" in m for m in about_wave), f"WARNING не называет процесс: {about_wave}"
    assert not any("late" in m for m in log.warnings), f"значение негодного stop_wave попало в лог: {log.warnings}"
    assert registry.stop_wave("worker1") == "main"


# --------------------------------------------------------------------------- #
# Живой PM: область children настоящего PM
# --------------------------------------------------------------------------- #


class WaveRig(Rig):
    """``Rig`` 1.1a с бюджетом ``has_last=True`` и детьми через НАСТОЯЩИЙ ``create_and_register`` реестра PM.

    ``_instrument`` Rig не зовётся целиком: он подменяет ``registry.children_stop`` шпионом с фиксированной сигнатурой,
    а здесь нужна настоящая группа без обёрток. Оставлена только заглушка оркестратора плагинов.
    """

    def __init__(self, graceful_s: float) -> None:
        super().__init__(graceful_s)
        self.pm.attach_stop_budget(stop_budget(graceful_s, has_last=True))

    def _instrument(self) -> None:
        class _NoPlugins:
            def request_stop(self) -> None:
                return None

            def shutdown(self) -> None:
                return None

        self.pm._orchestrator = _NoPlugins()

    def add_wave_child(
        self, farm: _Farm, name: str, *, wave: str | None, exit_after_s: float, dies_on_terminate: bool = True
    ) -> _FakeOsProcess:
        child = _spawn(
            self.pm._process_registry,
            farm,
            name,
            wave=wave,
            exit_after_s=exit_after_s,
            dies_on_terminate=dies_on_terminate,
        )
        self.pm._process_configs[name] = {"class": "fake.Child"}
        self.pm._ensure_routing_state()
        with self.pm._routing_lock:
            self.pm._incarnations[name] = 1  # имя попадает в processes ответа supervision.status
        self.children[name] = child  # type: ignore[assignment]  # Rig.close() добивает через _die
        return child


@pytest.fixture
def make_wave_rig(farm):
    rigs: list[WaveRig] = []

    def factory(graceful_s: float = 5.0) -> WaveRig:
        rig = WaveRig(graceful_s)
        rigs.append(rig)
        rig.start()
        return rig

    try:
        yield factory
    finally:
        for rig in rigs:
            rig.close()


def _bounded(fn: Any, timeout_s: float = 10.0) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="bounded")
    thread.start()
    thread.join(timeout_s)
    assert not thread.is_alive(), f"вызов завис дольше {timeout_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _status(rig: WaveRig) -> dict:
    res = _bounded(rig.pm._cmd_supervision_status)
    assert isinstance(res, dict) and res.get("success") is True, res
    return res


@pytest.mark.timeout(120)
def test_main_child_4s_then_last_child_2s_both_exited_through_pm_area(farm, make_wave_rig) -> None:
    """При ``has_last``: ``main`` выходит через 4,0 с после сигнала, ``last`` — через 2,0 с после своего. ``stop_event``
    ``last`` не раньше выхода ``main`` (старт + 4,0); итог обоих ``exited``, ни один не получил ``terminate``."""
    rig = make_wave_rig(5.0)
    main = rig.add_wave_child(farm, "worker", wave=None, exit_after_s=4.0)
    last = rig.add_wave_child(farm, "gui", wave="last", exit_after_s=2.0)

    t0 = time.monotonic()
    rig.pm.stop_event.set()
    assert rig.wait_root_closed(60.0), "корень PM не закрылся за дедлайн"

    assert last.t_signal is not None and main.t_dead is not None
    assert last.t_signal - t0 >= 4.0, (
        f"stop_event last в {last.t_signal - t0:.3f} с от старта, раньше выхода main (4,0)"
    )
    assert last.t_signal >= main.t_dead, "stop_event last взведён до выхода main"
    registry = rig.pm._process_registry
    assert registry.stop_outcome("worker") == "exited"
    assert registry.stop_outcome("gui") == "exited"
    assert main.terminate_calls == 0 and main.kill_calls == 0, "main получил эскалацию внутри своего окна"
    assert last.terminate_calls == 0 and last.kill_calls == 0, "last получил эскалацию: окно main зажало last"
    assert rig.report is not None and rig.report.survivors == (), rig.report


@pytest.mark.timeout(120)
def test_phase_last_wave_visible_between_last_signal_and_done(farm, make_wave_rig) -> None:
    """``main`` выходит через 1,5 с, ``last`` — через 1,5 с после своего сигнала; опрос ``supervision.status`` каждые
    0,1 с: до старт + 1,4 фаза ``children``; в [1,7; 2,9] — ``last_wave`` и ``deadline_at - started_at`` = 7,0 +- 0,3;
    затем ``done``."""
    rig = make_wave_rig(5.0)
    rig.add_wave_child(farm, "worker", wave=None, exit_after_s=1.5)
    rig.add_wave_child(farm, "gui", wave="last", exit_after_s=1.5)

    samples: list[tuple[float, dict | None]] = []
    quit_poll = threading.Event()

    def poll() -> None:
        while not quit_poll.is_set():
            t_a = time.monotonic()
            try:
                res = rig.pm._cmd_supervision_status()
            except BaseException as exc:  # noqa: BLE001
                samples.append((t_a - t0, {"phase": f"error: {exc!r}"}))
                return
            t_b = time.monotonic()
            samples.append(((t_a + t_b) / 2 - t0, res.get("system_stop")))
            quit_poll.wait(STATUS_POLL_S)

    t0 = time.monotonic()
    rig.pm.stop_event.set()
    poller = threading.Thread(target=poll, daemon=True, name="status-poller")
    poller.start()
    closed = rig.wait_root_closed(60.0)
    quit_poll.set()
    poller.join(10.0)
    assert closed, "корень PM не закрылся за дедлайн"

    # Первые мгновения раннер PM ещё не подхватил событие и стоп не начат (system_stop None): пропуск только до 0,3 с.
    early = [(t, info) for t, info in samples if 0.3 <= t < 1.4]
    assert len(early) >= 5, f"опросов в окне [0,3; 1,4): {len(early)}"
    for t, info in early:
        assert info is not None and info["phase"] == "children", (
            f"t={t:.2f} с: ожидалась фаза children, получено {info}"
        )

    middle = [(t, info) for t, info in samples if 1.7 <= t <= 2.9]
    timeline = [(round(t, 2), (info or {}).get("phase")) for t, info in samples]
    assert len(middle) >= 6, f"опросов в окне [1,7; 2,9]: {len(middle)}; ход фаз: {timeline}"
    for t, info in middle:
        assert info is not None and info["phase"] == "last_wave", (
            f"t={t:.2f} с: ожидалась фаза last_wave, получено {info}"
        )
        span = info["deadline_at"] - info["started_at"]
        assert abs(span - 7.0) <= 0.3, f"t={t:.2f} с: deadline_at - started_at = {span:.3f}, ожидалось 7,0 +- 0,3"

    final = rig.pm._system_stop_snapshot()
    assert final is not None and final["phase"] == "done", final


@pytest.mark.timeout(120)
def test_last_child_stop_deadline_null_until_signalled_then_from_own_signal(farm, make_wave_rig) -> None:
    """До сигнала ``last`` ``stop_deadline_at`` ребёнка ``last`` = ``null``, у имени из ``main`` — число; после сигнала
    ``last`` срок = сигнал ``last`` + окно имени (не сигнал ``main`` + окно)."""
    rig = make_wave_rig(5.0)
    main = rig.add_wave_child(farm, "worker", wave=None, exit_after_s=1.5)
    last = rig.add_wave_child(farm, "gui", wave="last", exit_after_s=3.0)

    rig.pm.stop_event.set()
    assert rig.wait_until(lambda: main.t_signal is not None, 30.0), "main не получил сигнал стопа"
    time.sleep(0.5)  # main ещё жив (выходит через 1,5 с), last не сигналлен
    assert main.is_alive(), "предусловие: main уже вышел, окно main не воспроизведено"
    before = _status(rig)["processes"]
    assert before["gui"]["stop_deadline_at"] is None, before["gui"]
    worker_deadline = before["worker"]["stop_deadline_at"]
    assert isinstance(worker_deadline, float), before["worker"]
    assert last.t_signal is None, "last получил stop_event, пока main ещё жив"

    assert rig.wait_until(lambda: last.t_signal_wall is not None, 30.0), "last не получил сигнал стопа"
    time.sleep(0.3)  # last живёт 3,0 с после сигнала
    assert last.is_alive(), "предусловие: last уже вышел"
    after = _status(rig)["processes"]
    deadline = after["gui"]["stop_deadline_at"]
    assert isinstance(deadline, float), after["gui"]

    window = deadline - last.t_signal_wall
    # Окно имени ``last`` без своего ключа = g = 5,0 (решение лида 2026-11-08; ADR-PMM-042: сигнал + окно имени).
    # Ошибка «сигнал main + окно» дала бы 3,5 (main сигналлен на 1,5 с раньше): вне допуска ниже.
    assert abs(window - 5.0) <= 0.3, (
        f"stop_deadline_at(gui) - сигнал last = {window:.3f} с: ожидалось окно имени 5,0, а не отсчёт от сигнала main"
    )
