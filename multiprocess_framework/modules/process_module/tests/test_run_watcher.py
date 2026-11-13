# -*- coding: utf-8 -*-
"""Task 1.2 (system-run-state) — слепые приёмочные тесты наблюдателя ``run_event`` на настоящем ``GenericProcess``.

Контракт — DESIGN пп.5-7 ``plans/2026-10-27_system-run-state/tasks/1.2.md``:
  * воркер ``run_watch`` (``WorkerType.SYSTEM``) сверяет цель с состоянием плагинов по УРОВНЮ: событие снято -> каждому
    ``RUNNING`` плагину ``pause()`` (состояние ``PAUSED``); взведено -> каждому ``PAUSED`` ``resume()`` (``RUNNING``);
  * исключение ``pause()`` одного плагина не мешает соседям, процесс жив;
  * первая пауза в ``boot()``: ребёнок, рождённый при снятом событии, объявляет готовность УЖЕ с плагинами в ``PAUSED``
    (устройство не успевает отдать кадр до START); фильтр источников ``generic_process.py:185`` пропускает ``PAUSED`` —
    воркер ``source_producer_<имя>`` СОЗДАН (иначе после START кадров не будет).

Наблюдаем эффект — ``plugin.state`` и вызовы хуков/``produce()``; имён методов сверки не трогаем (DESIGN их
не называет).
Стенд — настоящий ``GenericProcess`` под ``run_process_function`` в daemon-потоке (образец
``test_source_run_gate.py::test_real_generic_process_gate_and_run_gated_seam``): плагины — потоки того же
интерпретатора, поэтому их состояние читается напрямую. Событие — ``multiprocessing.Event``, ставится атрибутом
``_run_event`` подклассом до ``initialize()`` (как поставит раннер). Каждое ожидание — цикл с дедлайном или
daemon-поток с join-дедлайном.

Решения тестера:
  * в ``test_set_event_resumes_all_plugins`` плагины после ``clear()`` принудительно ставятся в ``PAUSED`` самим тестом
    (``_do_pause``) — чтобы красное было про «возобновление», а не про «паузу» (пауза покрыта соседним тестом);
  * плагины не-source категории в процессе есть (``RwProcessing``) вместе с источником: пауза «всем плагинам»
    проверяется на смеси.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin

_THIS = "multiprocess_framework.modules.process_module.tests.test_run_watcher"
_JOIN_S = 30.0
#: Срок реакции наблюдателя (сверка 0.05 с; запас на загруженную машину).
_REACT_S = 8.0

#: Живые экземпляры плагинов процесса по имени и счётчики хуков (процесс-ребёнок — поток этого же интерпретатора).
PLUGINS: dict[str, ProcessModulePlugin] = {}
HOOKS: dict[str, dict[str, int]] = {}
PRODUCE_CALLS: list[float] = []
SHARED: dict[str, Any] = {"event": None, "proc": None}
_LOCK = threading.Lock()


def _bump(name: str, hook: str) -> None:
    with _LOCK:
        HOOKS.setdefault(name, {"pause": 0, "resume": 0})[hook] += 1


class _RwBase(ProcessModulePlugin):
    def __init__(self) -> None:
        super().__init__()
        with _LOCK:
            PLUGINS[type(self).name] = self

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def pause(self, ctx: PluginContext) -> None:
        _bump(self.name, "pause")

    def resume(self, ctx: PluginContext) -> None:
        _bump(self.name, "resume")


class RwProcessing(_RwBase):
    category = "processing"
    name = "rw_proc_a"

    def process(self, items):
        return items


class RwProcessingB(RwProcessing):
    name = "rw_proc_b"


class RwProcessingBadPause(RwProcessing):
    """``pause()`` бросает: исключение не должно мешать соседям."""

    name = "rw_proc_bad"

    def pause(self, ctx: PluginContext) -> None:
        _bump(self.name, "pause")
        raise RuntimeError("pause не удался")


class RwSource(_RwBase):
    category = "source"
    name = "rw_source"

    def produce(self) -> list:
        PRODUCE_CALLS.append(time.perf_counter())
        return []


class WatchedGenericProcess(GenericProcess):
    """Настоящий GenericProcess; ``_run_event`` стоит на экземпляре до ``initialize()`` (как поставит раннер)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


def _start(plugin_classes: list[type], event: Any) -> tuple[threading.Thread, threading.Event, Any]:
    PLUGINS.clear()
    HOOKS.clear()
    PRODUCE_CALLS.clear()
    SHARED["event"] = event
    SHARED["proc"] = None
    plugins = [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in plugin_classes]
    cfg = {"config": {"plugins": plugins, "chain_targets": [], "source_target_fps": 100.0}}
    own_ready = multiprocessing.Event()
    bundle = {
        "queues": {"data": multiprocessing.Queue()},
        "config": cfg,
        "custom": {"process_config": cfg, "ready_event": own_ready},
    }
    stop = threading.Event()
    thread = threading.Thread(
        target=run_process_function,
        args=(f"{_THIS}.WatchedGenericProcess", "run_watch_gp", stop, bundle, None),
        daemon=True,
        name="run-watch-generic-process",
    )
    thread.start()
    return thread, stop, own_ready


def _states(names: list[str]) -> dict[str, str]:
    return {n: (PLUGINS[n].state.value if n in PLUGINS else "absent") for n in names}


def _wait_states(names: list[str], want: str, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if all(_states(names)[n] == want for n in names):
            return True
        time.sleep(0.02)
    return all(_states(names)[n] == want for n in names)


def _shutdown(thread: threading.Thread, stop: threading.Event) -> None:
    stop.set()
    thread.join(_JOIN_S)
    assert not thread.is_alive(), "run_process_function не вышел после stop"


@pytest.mark.timeout(120)
def test_clear_event_pauses_all_plugins() -> None:
    """Событие взведено: плагины ``RUNNING``; ``clear()``: каждый (source и processing) в ``PAUSED``, хук позван."""
    names = ["rw_proc_a", "rw_proc_b", "rw_source"]
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start([RwProcessing, RwProcessingB, RwSource], event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность за 30 с"
        assert _states(names) == {n: "running" for n in names}, _states(names)

        event.clear()

        assert _wait_states(names, "paused", _REACT_S), f"после clear() не все плагины в PAUSED: {_states(names)}"
        for name in names:
            assert HOOKS[name]["pause"] >= 1, f"pause() у {name} не позван: {HOOKS}"
    finally:
        _shutdown(thread, stop)


@pytest.mark.timeout(120)
def test_set_event_resumes_all_plugins() -> None:
    """Плагины в ``PAUSED`` при снятом событии; ``set()`` -> каждый возвращается в ``RUNNING``, ``resume()`` позван."""
    names = ["rw_proc_a", "rw_proc_b", "rw_source"]
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start([RwProcessing, RwProcessingB, RwSource], event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность за 30 с"
        event.clear()
        # Предусловие стенда (не предмет теста): плагины на паузе. Наблюдатель мог поставить их сам — тогда no-op.
        for name in names:
            PLUGINS[name]._do_pause(None)  # type: ignore[arg-type]
        assert _states(names) == {n: "paused" for n in names}, _states(names)
        resumes_before = {n: HOOKS.get(n, {}).get("resume", 0) for n in names}

        event.set()

        assert _wait_states(names, "running", _REACT_S), f"после set() не все плагины в RUNNING: {_states(names)}"
        for name in names:
            assert HOOKS[name]["resume"] > resumes_before[name], f"resume() у {name} не позван: {HOOKS}"
    finally:
        _shutdown(thread, stop)


@pytest.mark.timeout(120)
def test_child_started_with_clear_event_is_paused_before_ready() -> None:
    """Ребёнок рождён при снятом событии: к готовности источник в ``PAUSED``, воркер ``source_producer_<имя>`` создан.

    Затем ``set()`` -> источник ``RUNNING`` и ``produce()`` пошёл (если воркера нет — после START кадров не будет).
    """
    event = multiprocessing.Event()  # снято с рождения
    thread, stop, own_ready = _start([RwSource], event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность за 30 с"
        # сразу после объявления готовности: пауза уже стоит (устройство не отдаёт кадр до START)
        assert _states(["rw_source"]) == {"rw_source": "paused"}, _states(["rw_source"])
        assert PRODUCE_CALLS == [], f"produce() вызван {len(PRODUCE_CALLS)} раз до START"

        # воркер источника СОЗДАН, несмотря на PAUSED (регресс-ловушка на фильтр generic_process.py:185)
        proc = SHARED["proc"]
        assert proc is not None, "экземпляр процесса не создан"
        workers = proc.worker_manager.get_all_workers_status()
        assert "source_producer_rw_source" in workers, sorted(workers)

        event.set()

        assert _wait_states(["rw_source"], "running", _REACT_S), (
            f"после set() источник не RUNNING: {_states(['rw_source'])}"
        )
        end = time.monotonic() + _REACT_S
        while len(PRODUCE_CALLS) < 3 and time.monotonic() < end:
            time.sleep(0.02)
        assert len(PRODUCE_CALLS) >= 3, f"после set() кадры не пошли: produce() вызван {len(PRODUCE_CALLS)} раз"
    finally:
        _shutdown(thread, stop)


@pytest.mark.timeout(120)
def test_one_plugin_pause_raises_others_still_paused() -> None:
    """``pause()`` одного плагина бросает: остальные в ``PAUSED``, упавший остаётся ``RUNNING``, процесс жив."""
    healthy = ["rw_proc_a", "rw_proc_b", "rw_source"]
    event = multiprocessing.Event()
    event.set()
    # упавший — ПЕРВЫМ в списке: проверяем, что исключение не обрывает обход соседей
    thread, stop, own_ready = _start([RwProcessingBadPause, RwProcessing, RwProcessingB, RwSource], event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность за 30 с"

        event.clear()

        assert _wait_states(healthy, "paused", _REACT_S), f"исключение соседа сорвало паузу: {_states(healthy)}"
        assert HOOKS["rw_proc_bad"]["pause"] >= 1, f"pause() упавшего плагина не позван: {HOOKS}"
        assert _states(["rw_proc_bad"]) == {"rw_proc_bad": "running"}, (
            "упавший pause() не должен менять состояние плагина"
        )
        assert thread.is_alive(), "процесс не пережил исключение pause()"
    finally:
        _shutdown(thread, stop)
