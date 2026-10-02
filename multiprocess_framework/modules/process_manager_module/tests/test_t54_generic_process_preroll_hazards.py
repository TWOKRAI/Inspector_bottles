# -*- coding: utf-8 -*-
"""Task 5.4 — hazard-тесты автора: звено runner -> GenericProcess -> SourceProducer.

Слепой набор тестера проверяет SourceProducer и проводку PM -> реестр -> runner по
отдельности; звено «runner кладёт событие -> GenericProcess отдаёт его продюсеру»
не держал ни один тест. Инъекции лида (K6: runner ставит ``_sources_ready_event``
ПОСЛЕ ``initialize()``; K7: GenericProcess отдаёт ``ready_event=None``) оставляли все
59 тестов зелёными. Здесь настоящий ``GenericProcess`` под настоящим
``run_process_function`` (в daemon-потоке, без spawn): событие готовности системы
держит ВСЕ источники процесса до ``set()``.

Что может сломаться в ЭТОМ механизме, исходя из того, как он построен:

* порядок: ``SourceProducer`` строится в ``initialize()`` — событие обязано лежать на
  экземпляре ДО него (проба ``initialize`` ниже);
* проводка: ``getattr(self, "_sources_ready_event", None)`` молча даёт ``None`` при
  любой опечатке/переименовании — «ожидания нет» неотличимо от «ожидание работает»,
  поэтому каждая проверка отсутствия кадров парная с контролем достижимости
  (без события кадры ИДУТ);
* ``log_warning`` проводится отдельно от события — свой тест;
* повторный ``run_loop`` того же продюсера (рестарт воркера): после истёкшего срока
  и после взведённого события ждать заново нельзя, после стопа посреди ожидания —
  ждём заново со свежим сроком (поведение закреплено тестом, не следствие случая);
* системный стоп посреди preroll не должен ждать срока 10 с.

Каждый блокирующий вызов — в daemon-потоке с join-дедлайном (pytest-timeout в окружении
нет). Счёт кадров — вызовы ``produce()`` в списках на уровне модуля.
"""

from __future__ import annotations

import multiprocessing
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic import source_producer as sp_mod
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

from ..runner.process_runner import run_process_function

#: Шаг таймера Windows: границы со спеки (50 мс) допускают +1 такт.
GRID_S = 0.0156

_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_t54_generic_process_preroll_hazards"
_GP = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"
_PROBE_GP = f"{_THIS}.ProbeGenericProcess"

#: Метки времени produce() по источникам; сбрасывается фикстурой ``clean_state``.
CALLS: dict[str, list[float]] = {"a": [], "b": []}
#: Что runner положил на экземпляр к моменту initialize() (проба K6).
AT_INITIALIZE: list = []


class _CountingSource(ProcessModulePlugin):
    """Источник: каждый produce() фиксирует метку времени, кадров не отдаёт."""

    category = "source"
    key = ""

    def configure(self, ctx) -> None:  # noqa: D401 — контракт плагина
        pass

    def start(self, ctx) -> None:
        pass

    def produce(self) -> list:
        CALLS[self.key].append(time.perf_counter())
        return []


class CountSrcA(_CountingSource):
    name = "t54_gp_src_a"
    key = "a"


class CountSrcB(_CountingSource):
    name = "t54_gp_src_b"
    key = "b"


class ProbeGenericProcess(GenericProcess):
    """GenericProcess, запоминающий событие на экземпляре в момент входа в initialize()."""

    def initialize(self) -> bool:
        AT_INITIALIZE.append(getattr(self, "_sources_ready_event", "MISSING"))
        return super().initialize()


def _plugin_defs(*keys: str) -> list[dict]:
    classes = {"a": CountSrcA, "b": CountSrcB}
    return [{"plugin_class": f"{_THIS}.{classes[k].__name__}", "plugin_name": classes[k].name} for k in keys]


class _Runner:
    """Один настоящий GenericProcess под run_process_function в daemon-потоке."""

    def __init__(self, ready_event, *, class_path: str = _GP, keys: tuple[str, ...] = ("a",), sys_stop=None) -> None:
        cfg = {"config": {"plugins": _plugin_defs(*keys), "chain_targets": [], "source_target_fps": 100.0}}
        # Собственная готовность процесса (runner передаёт её через attach_ready_event, процесс
        # взводит в конце run()) — якорь тестов «кадров нет»: отсчёт идёт от неё, а не от фиксированной паузы.
        self.own = multiprocessing.Event()
        bundle = {
            "queues": {"data": multiprocessing.Queue()},
            "config": cfg,
            "custom": {"process_config": cfg, "ready_event": self.own},
        }
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=run_process_function,
            args=(class_path, "t54_gp", self.stop, bundle, sys_stop),
            kwargs={"system_ready_event": ready_event},
            daemon=True,
            name="t54-generic-process",
        )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=15.0)


@pytest.fixture(autouse=True)
def clean_state():
    for v in CALLS.values():
        v.clear()
    AT_INITIALIZE.clear()
    yield


@pytest.fixture
def runners():
    made: list[_Runner] = []

    def _make(ready_event, **kw) -> _Runner:
        r = _Runner(ready_event, **kw)
        made.append(r)
        return r

    yield _make
    for r in made:
        r.close()
    leaked = [r.thread.name for r in made if r.thread.is_alive()]
    assert not leaked, f"run_process_function не вышел после stop: {leaked}"


def _wait_first(key: str, deadline_s: float) -> bool:
    end = time.perf_counter() + deadline_s
    while time.perf_counter() < end:
        if CALLS[key]:
            return True
        time.sleep(0.002)
    return bool(CALLS[key])


# ---------------------------------------------------------------------------
# Настоящий GenericProcess: событие держит источник, контроль — без события кадры идут
# ---------------------------------------------------------------------------


def test_real_generic_process_holds_source_until_system_ready_event(runners) -> None:
    ev = multiprocessing.Event()
    r = runners(ev)
    r.start()
    assert r.own.wait(10.0), "процесс не объявил собственную готовность за 10 с"
    time.sleep(0.3)  # при K7 (ready_event=None) за 0.3 с идут десятки кадров
    assert CALLS["a"] == [], f"produce() вызван {len(CALLS['a'])} раз до set() системного события"
    t_set = time.perf_counter()
    ev.set()
    assert _wait_first("a", 3.0), "после set() кадров нет за 3 с"
    latency = CALLS["a"][0] - t_set
    assert latency <= 0.050 + GRID_S, f"первый кадр через {latency * 1000:.1f} мс после set()"


def test_control_generic_process_without_event_produces_frames(runners) -> None:
    """КОНТРОЛЬ достижимости: тот же стенд при ``system_ready_event=None`` — кадры идут.

    Без него «0 кадров» предыдущего теста сошёлся бы и с рассыпавшимся стендом
    (плагин не загрузился, процесс не поднялся)."""
    r = runners(None)
    r.start()
    assert _wait_first("a", 10.0), "без события источник GenericProcess не дал ни одного кадра за 10 с"
    assert len(CALLS["a"]) > 0


def test_runner_sets_sources_ready_event_before_initialize(runners) -> None:
    """K6: GenericProcess строит SourceProducer в initialize(), событие должно лежать раньше."""
    ev = multiprocessing.Event()
    r = runners(ev, class_path=_PROBE_GP)
    r.start()
    end = time.perf_counter() + 5.0
    while time.perf_counter() < end and not AT_INITIALIZE:
        time.sleep(0.01)
    assert AT_INITIALIZE == [ev], AT_INITIALIZE


# ---------------------------------------------------------------------------
# Два источника в одном процессе
# ---------------------------------------------------------------------------


def test_two_sources_in_one_process_both_wait_for_the_event(runners) -> None:
    ev = multiprocessing.Event()
    r = runners(ev, keys=("a", "b"))
    r.start()
    assert r.own.wait(10.0), "процесс не объявил собственную готовность за 10 с"
    time.sleep(0.3)
    assert CALLS["a"] == [] and CALLS["b"] == [], (len(CALLS["a"]), len(CALLS["b"]))
    ev.set()
    assert _wait_first("a", 3.0), "источник a не стартовал после set()"
    assert _wait_first("b", 3.0), "источник b не стартовал после set()"


# ---------------------------------------------------------------------------
# log_warning: проводка из GenericProcess в SourceProducer
# ---------------------------------------------------------------------------


def test_preroll_warning_goes_through_the_process_logger_exactly_once(runners, monkeypatch) -> None:
    """Срок вышел, событие не пришло -> ровно один WARNING «preroll» через логгер процесса.

    ``_log_warning`` процесса пишет в собственный менеджер логов; наблюдаем его вызов
    подменой метода экземпляра через подкласс — это граница, которую GenericProcess
    передаёт продюсеру (``log_warning=self._log_warning``)."""
    monkeypatch.setattr(sp_mod, "DEFAULT_PREROLL_TIMEOUT_S", 0.3, raising=False)
    warnings: list[str] = []
    original = GenericProcess._log_warning

    def spy(self, message, *a, **kw):
        warnings.append(str(message))
        return original(self, message, *a, **kw)

    monkeypatch.setattr(GenericProcess, "_log_warning", spy)
    r = runners(multiprocessing.Event())  # никто не взведёт
    t0 = time.perf_counter()
    r.start()
    assert _wait_first("a", 6.0), "срок 0.3 с истёк, а источник так и не стартовал"
    time.sleep(0.4)  # кадры идут дальше — второго предупреждения быть не должно
    preroll = [w for w in warnings if "preroll" in w.lower()]
    assert len(preroll) == 1, warnings
    assert len(CALLS["a"]) >= 3, "после срока источник должен продолжать крутиться"
    assert CALLS["a"][0] - t0 >= 0.3 - GRID_S


# ---------------------------------------------------------------------------
# Повторный run_loop того же продюсера (рестарт воркера)
# ---------------------------------------------------------------------------


class _Plain:
    is_source = True

    def __init__(self) -> None:
        self.name = "t54_restart"
        self.stamps: list[float] = []

    def produce(self) -> list:
        self.stamps.append(time.perf_counter())
        return []


class _RerunRig:
    def __init__(self, ready_event) -> None:
        self.plugin = _Plain()
        self.warnings: list[str] = []
        self.producer = SourceProducer(
            plugin=self.plugin,
            shm_middleware=None,
            send_fn=lambda target, msg: None,
            chain_targets=[],
            target_fps=200.0,
            node_name="t54_restart",
            ready_event=ready_event,
            log_warning=self.warnings.append,
        )
        self.threads: list[tuple[threading.Thread, threading.Event]] = []

    def run(self) -> tuple[threading.Thread, threading.Event]:
        stop = threading.Event()
        t = threading.Thread(
            target=self.producer.run_loop, args=(stop, threading.Event()), daemon=True, name="t54-rerun"
        )
        self.threads.append((t, stop))
        t.start()
        return t, stop

    def close(self) -> None:
        for t, stop in self.threads:
            stop.set()
            t.join(timeout=3.0)


def test_rerun_after_timeout_does_not_wait_again_and_warns_once(monkeypatch) -> None:
    monkeypatch.setattr(sp_mod, "DEFAULT_PREROLL_TIMEOUT_S", 0.2, raising=False)
    rig = _RerunRig(threading.Event())  # никто не взведёт
    try:
        t1, stop1 = rig.run()
        end = time.perf_counter() + 2.0
        while time.perf_counter() < end and not rig.plugin.stamps:
            time.sleep(0.002)
        assert rig.plugin.stamps, "срок 0.2 с истёк, источник не стартовал"
        stop1.set()
        t1.join(timeout=3.0)
        assert not t1.is_alive()
        n_before = len(rig.plugin.stamps)
        t_rerun = time.perf_counter()
        rig.run()
        end = time.perf_counter() + 1.0
        while time.perf_counter() < end and len(rig.plugin.stamps) == n_before:
            time.sleep(0.002)
        assert len(rig.plugin.stamps) > n_before, "повторный run_loop не дал кадра"
        assert rig.plugin.stamps[n_before] - t_rerun <= 0.050 + GRID_S, "повторный run_loop ждал срок заново"
        assert len(rig.warnings) == 1, rig.warnings
    finally:
        rig.close()


def test_rerun_after_stop_during_preroll_waits_again_with_a_fresh_deadline(monkeypatch) -> None:
    """Закреплённое поведение: стоп посреди ожидания preroll НЕ засчитывает.

    Повторный запуск того же продюсера ждёт событие заново и со свежим сроком —
    срок первого запуска не «доедается»."""
    monkeypatch.setattr(sp_mod, "DEFAULT_PREROLL_TIMEOUT_S", 0.5, raising=False)
    ev = threading.Event()
    rig = _RerunRig(ev)
    try:
        t1, stop1 = rig.run()
        time.sleep(0.3)  # внутри срока 0.5 с
        stop1.set()
        t1.join(timeout=3.0)
        assert not t1.is_alive()
        assert rig.plugin.stamps == [] and rig.warnings == []
        time.sleep(0.4)  # от старта первого запуска прошло > 0.5 с; от стопа — нет
        t_rerun = time.perf_counter()
        rig.run()
        time.sleep(0.3)  # < свежий срок 0.5 с: кадров быть не должно, event так и не взведён
        assert rig.plugin.stamps == [], "повторный запуск доел срок первого вместо свежего"
        assert rig.warnings == []
        end = time.perf_counter() + 2.0
        while time.perf_counter() < end and not rig.plugin.stamps:
            time.sleep(0.002)
        assert rig.plugin.stamps, "свежий срок истёк, а источник не стартовал"
        assert rig.plugin.stamps[0] - t_rerun >= 0.5 - GRID_S
        assert len(rig.warnings) == 1, rig.warnings
    finally:
        rig.close()


# ---------------------------------------------------------------------------
# Системный стоп посреди preroll — сквозной
# ---------------------------------------------------------------------------


def test_system_stop_during_preroll_exits_runner_without_produce_or_warning(runners, monkeypatch) -> None:
    warnings: list[str] = []
    original = GenericProcess._log_warning

    def spy(self, message, *a, **kw):
        warnings.append(str(message))
        return original(self, message, *a, **kw)

    monkeypatch.setattr(GenericProcess, "_log_warning", spy)
    sys_stop = multiprocessing.Event()
    r = runners(multiprocessing.Event(), sys_stop=sys_stop)  # срок по умолчанию 10 с
    r.start()
    # Процесс объявил готовность (его run() отработал) при 0 кадров: источник внутри preroll.
    assert r.own.wait(10.0), "процесс не объявил собственную готовность за 10 с"
    time.sleep(0.3)
    assert CALLS["a"] == [], "кадры пошли до системного стопа и до set() события"
    assert r.thread.is_alive()
    t_stop = time.perf_counter()
    sys_stop.set()
    r.thread.join(timeout=5.0)
    exit_after = time.perf_counter() - t_stop
    assert not r.thread.is_alive(), "run_process_function не вышел за 5 с после system_stop_event"
    assert exit_after <= 1.0, f"выход через {exit_after:.2f} с после системного стопа"
    assert CALLS["a"] == [], "produce() вызван во время/после стопа в preroll"
    assert not [w for w in warnings if "preroll" in w.lower()], warnings
