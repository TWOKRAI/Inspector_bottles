# -*- coding: utf-8 -*-
"""Task 1.2 (system-run-state) — hazard-тесты автора: сверка ``run_event`` с плагинами (гонки, замки, порядок).

Не слепой набор (``test_run_watcher.py``) — проверки свойств, которые автор гарантирует: сверка по УРОВНЮ, а не по
фронту; зависший хук не морозит соседей и снимок; shutdown не воскрешает закрытый плагин; ``_should_pause`` одна на
сверку и boot; упавший хук — причина ``failure`` и повтор не чаще раза в секунду.

Стенд — настоящий ``PluginOrchestrator`` + ``MockProcessServices`` (носитель ``_run_event`` — ``threading.Event``,
у него те же ``is_set/set/clear``, что у ``mp.Event``); проход сверки зовётся синхронно, блокирующие хуки — в
daemon-потоке с дедлайном ``join``. Настоящий ``GenericProcess`` — только в T4 (``worker.pause_all``).
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager

_THIS = "multiprocess_framework.modules.process_module.tests.test_run_watcher_hazards"
_PROC = "rwh_proc"
_JOIN_S = 20.0

HOOKS: dict[str, dict[str, int]] = {}
PRODUCE_CALLS: list[str] = []
GATE = threading.Event()  # отпускает заблокированный хук
ENTERED = threading.Event()  # хук вошёл (и заблокирован)


@pytest.fixture(autouse=True)
def _reset() -> Any:
    HOOKS.clear()
    PRODUCE_CALLS.clear()
    GATE.clear()
    ENTERED.clear()
    yield
    GATE.set()  # не оставляем заблокированных потоков


def _bump(name: str, hook: str) -> None:
    HOOKS.setdefault(name, {"pause": 0, "resume": 0})[hook] += 1


def _hooks(name: str) -> dict[str, int]:
    return HOOKS.get(name, {"pause": 0, "resume": 0})


class HzPlain(ProcessModulePlugin):
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items

    def pause(self, ctx: PluginContext) -> None:
        _bump(self.name, "pause")

    def resume(self, ctx: PluginContext) -> None:
        _bump(self.name, "resume")


class HzA(HzPlain):
    name = "hz_a"


class HzBlockPause(HzPlain):
    name = "hz_block_pause"

    def pause(self, ctx: PluginContext) -> None:
        _bump(self.name, "pause")
        ENTERED.set()
        GATE.wait(_JOIN_S)


class HzBlockResume(HzPlain):
    name = "hz_block_resume"

    def resume(self, ctx: PluginContext) -> None:
        _bump(self.name, "resume")
        ENTERED.set()
        GATE.wait(_JOIN_S)


class HzBadPause(HzPlain):
    name = "hz_bad_pause"

    def pause(self, ctx: PluginContext) -> None:
        _bump(self.name, "pause")
        raise RuntimeError("секрет-путь /pause/key")


class HzBadResume(HzPlain):
    name = "hz_bad_resume"

    def resume(self, ctx: PluginContext) -> None:
        _bump(self.name, "resume")
        raise RuntimeError("resume не удался")


class HzConfigureBroken(HzPlain):
    name = "hz_cfg_broken"

    def configure(self, ctx: PluginContext) -> None:
        raise RuntimeError("configure упал")


class HzSource(HzPlain):
    category = "source"
    name = "hz_src"

    def produce(self) -> list:
        PRODUCE_CALLS.append(self.name)
        return []


def _boot(
    classes: list[type],
    *,
    event: threading.Event | None,
    watch: bool = True,
    extra: dict[str, dict] | None = None,
) -> tuple[PluginOrchestrator, MockProcessServices, dict[str, ProcessModulePlugin]]:
    services = MockProcessServices(name=_PROC)
    services._current_process_status = "running"  # type: ignore[attr-defined]
    if event is not None:
        services._run_event = event  # type: ignore[attr-defined]
    if watch:
        services._run_watch_enabled = lambda: True  # type: ignore[attr-defined]
    orch = PluginOrchestrator(services=services)
    defs = [
        {"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name, **(extra or {}).get(c.name, {})}
        for c in classes
    ]
    orch.load_and_configure_managers(defs)
    orch.boot()
    return orch, services, {p.name: p for p in orch.plugins}


def _in_thread(target: Any) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True, name="rwh-worker")
    thread.start()
    return thread


def _join(thread: threading.Thread, what: str, deadline_s: float = _JOIN_S) -> None:
    thread.join(deadline_s)
    assert not thread.is_alive(), f"{what}: поток завис дольше {deadline_s} с"


def _event(is_set: bool) -> threading.Event:
    ev = threading.Event()
    if is_set:
        ev.set()
    return ev


# --------------------------------------------------------------------------- #
# T1, T2: сверка по уровню
# --------------------------------------------------------------------------- #


def test_event_pulse_during_pause_hook_converges() -> None:
    """Событие взведено, пока ``pause()`` блокирован: после хука ``PAUSED``, следующий опрос даёт ``RUNNING``."""
    event = _event(True)
    orch, _, plugins = _boot([HzBlockPause, HzA], event=event)
    event.clear()
    worker = _in_thread(orch.reconcile_run_event)
    assert ENTERED.wait(_JOIN_S), "pause() не вызван"

    event.set()  # цель сменилась, пока хук блокирован
    GATE.set()
    _join(worker, "проход сверки")

    assert plugins["hz_block_pause"].state is PluginState.PAUSED
    # соседу уже нечего паузить: цель перечитывается перед каждым плагином
    assert _hooks("hz_a") == {"pause": 0, "resume": 0}
    assert plugins["hz_a"].state is PluginState.RUNNING

    orch.reconcile_run_event()  # следующий опрос сходится

    assert plugins["hz_block_pause"].state is PluginState.RUNNING
    assert _hooks("hz_block_pause") == {"pause": 1, "resume": 1}


def test_event_pulse_during_resume_hook_converges() -> None:
    """Зеркало: событие снято, пока ``resume()`` блокирован: после хука ``RUNNING``, следующий опрос даёт ``PAUSED``."""
    event = _event(True)
    orch, _, plugins = _boot([HzBlockResume], event=event)
    plugin = plugins["hz_block_resume"]
    event.clear()
    orch.reconcile_run_event()  # пауза применена обычным путём
    assert plugin.state is PluginState.PAUSED
    event.set()
    worker = _in_thread(orch.reconcile_run_event)
    assert ENTERED.wait(_JOIN_S), "resume() не вызван"

    event.clear()
    GATE.set()
    _join(worker, "проход сверки")

    assert plugin.state is PluginState.RUNNING
    orch.reconcile_run_event()
    assert plugin.state is PluginState.PAUSED
    assert _hooks("hz_block_resume") == {"pause": 2, "resume": 1}


def test_pulse_between_polls_is_net_zero() -> None:
    """``clear()→set()`` быстрее опроса: ни одного хука, состояния не менялись (осознанно: чистый эффект ноль)."""
    event = _event(True)
    orch, _, plugins = _boot([HzA], event=event)

    event.clear()
    event.set()
    orch.reconcile_run_event()

    assert _hooks("hz_a") == {"pause": 0, "resume": 0}
    assert plugins["hz_a"].state is PluginState.RUNNING


# --------------------------------------------------------------------------- #
# T4: наблюдатель переживает worker.pause_all (настоящий процесс)
# --------------------------------------------------------------------------- #

SHARED: dict[str, Any] = {"event": None, "proc": None}


class WatchedGenericProcess(GenericProcess):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


def _worker_paused(wm: Any, name: str) -> bool:
    info = wm._worker_registry.get(name)
    assert info is not None, f"воркер {name!r} не зарегистрирован"
    return bool(info["pause_event"].is_set())


@pytest.mark.timeout(120)
def test_observer_survives_worker_pause_all() -> None:
    """``worker.pause_all`` не глушит ``run_watch`` и ``readiness_snapshot``: ``clear()`` после неё паузит плагины."""
    event = multiprocessing.Event()
    event.set()
    SHARED["event"] = event
    SHARED["proc"] = None
    cfg = {
        "config": {
            "plugins": [{"plugin_class": f"{_THIS}.HzA", "plugin_name": HzA.name}],
            "chain_targets": [],
        }
    }
    own_ready = multiprocessing.Event()
    bundle = {
        "queues": {"data": multiprocessing.Queue()},
        "config": cfg,
        "custom": {"process_config": cfg, "ready_event": own_ready},
    }
    stop = threading.Event()
    thread = _in_thread(lambda: run_process_function(f"{_THIS}.WatchedGenericProcess", "rwh_gp", stop, bundle, None))
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность"
        proc = SHARED["proc"]
        wm = proc.worker_manager

        wm.pause_all_workers(exclude_system=True)

        assert not _worker_paused(wm, "run_watch"), "pause_all заглушил наблюдателя событий"
        assert not _worker_paused(wm, "readiness_snapshot"), "pause_all заглушил снимок готовности"
        event.clear()
        end = time.monotonic() + 8.0
        plugin = proc._orchestrator.plugins[0]
        while plugin.state is not PluginState.PAUSED and time.monotonic() < end:
            time.sleep(0.02)
        assert plugin.state is PluginState.PAUSED, "после pause_all наблюдатель перестал паузить плагины"
    finally:
        stop.set()
        thread.join(_JOIN_S)
    assert not thread.is_alive()


# --------------------------------------------------------------------------- #
# T5, T22: остановка и shutdown
# --------------------------------------------------------------------------- #


def test_shutdown_during_slow_pause_hook_keeps_stopped() -> None:
    """Медленный ``pause()`` пережил ``shutdown()`` (замок сверки истёк за 2 с): ``PAUSED`` не затирает ``STOPPED``."""
    event = _event(True)
    orch, services, plugins = _boot([HzBlockPause], event=event)
    plugin = plugins["hz_block_pause"]
    event.clear()
    worker = _in_thread(orch.reconcile_run_event)
    assert ENTERED.wait(_JOIN_S), "pause() не вызван"

    started = time.monotonic()
    orch.request_stop()  # контракт C-60: не ждёт замок сверки
    assert time.monotonic() - started < 1.0, "request_stop() ждал замок сверки"
    closer = _in_thread(orch.shutdown)
    _join(closer, "shutdown()", 10.0)
    assert plugin.state is PluginState.STOPPED
    errors = [rec["msg"] for rec in services.logs if rec["level"] == "ERROR"]
    assert any("замок сверки" in msg for msg in errors), errors

    GATE.set()  # хук возвращается ПОСЛЕ shutdown
    _join(worker, "проход сверки")

    assert plugin.state is PluginState.STOPPED, "медленный pause() воскресил закрытый плагин"


def test_do_pause_does_not_overwrite_changed_state() -> None:
    """Защита в ``base.py``: если хук застал смену состояния, ``_do_pause/_do_resume`` её не затирают."""

    class _Closing(HzPlain):
        name = "hz_closing"

        def pause(self, ctx: PluginContext) -> None:
            self.state = PluginState.STOPPED

        def resume(self, ctx: PluginContext) -> None:
            self.state = PluginState.STOPPED

    plugin = _Closing()
    plugin.state = PluginState.RUNNING
    plugin._do_pause(None)  # type: ignore[arg-type]
    assert plugin.state is PluginState.STOPPED

    plugin.state = PluginState.PAUSED
    plugin._do_resume(None)  # type: ignore[arg-type]
    assert plugin.state is PluginState.STOPPED


def test_no_hooks_after_request_stop() -> None:
    """После ``request_stop()`` сверка не зовёт ни ``pause()``, ни ``resume()``."""
    event = _event(True)
    orch, _, plugins = _boot([HzA], event=event)

    orch.request_stop()
    event.clear()
    orch.reconcile_run_event()

    assert _hooks("hz_a") == {"pause": 0, "resume": 0}
    assert plugins["hz_a"].state is PluginState.RUNNING


# --------------------------------------------------------------------------- #
# T6 (часть паузы): зависший readiness() и медленный хук не морозят друг друга
# --------------------------------------------------------------------------- #


class HzBlockReadiness(HzPlain):
    name = "hz_block_readiness"

    def readiness(self, ctx: PluginContext) -> list[dict]:
        ENTERED.set()
        GATE.wait(_JOIN_S)
        return []


def test_blocking_readiness_does_not_stall_pause_hooks() -> None:
    """``readiness()`` одного плагина завис: пауза остальных проходит (поток снимка и поток сверки — разные)."""
    event = _event(True)
    orch, _, plugins = _boot([HzBlockReadiness, HzA], event=event)
    snapshot_worker = _in_thread(orch.readiness_snapshot)
    assert ENTERED.wait(_JOIN_S), "readiness() не вызван"

    event.clear()
    reconcile = _in_thread(orch.reconcile_run_event)
    _join(reconcile, "проход сверки при зависшем readiness()", 5.0)

    assert plugins["hz_a"].state is PluginState.PAUSED
    assert plugins["hz_block_readiness"].state is PluginState.PAUSED
    GATE.set()
    _join(snapshot_worker, "снимок")


def test_slow_resume_hook_does_not_freeze_snapshot_at() -> None:
    """``resume()`` блокирован в проходе сверки: снимок считается (``at`` растёт), замок сверки он не берёт."""
    event = _event(True)
    orch, _, plugins = _boot([HzBlockResume], event=event)
    event.clear()
    orch.reconcile_run_event()
    event.set()
    reconcile = _in_thread(orch.reconcile_run_event)
    assert ENTERED.wait(_JOIN_S), "resume() не вызван"

    first = orch.readiness_snapshot()
    time.sleep(0.05)
    result: dict[str, Any] = {}
    snap_thread = _in_thread(lambda: result.update(orch.readiness_snapshot()))
    _join(snap_thread, "снимок при медленном resume()", 5.0)

    assert result["at"] > first["at"], (first, result)
    GATE.set()
    _join(reconcile, "проход сверки")


# --------------------------------------------------------------------------- #
# T8: _should_pause одна на сверку и boot (run_gated: false)
# --------------------------------------------------------------------------- #


def test_run_gated_false_source_not_paused_and_excluded_from_paused() -> None:
    """Источник с ``run_gated: false`` остаётся ``RUNNING`` при снятом событии и не держит ``paused: false``."""
    event = _event(True)
    orch, _, plugins = _boot([HzSource, HzA], event=event, extra={"hz_src": {"run_gated": False}})

    event.clear()
    orch.reconcile_run_event()

    assert plugins["hz_src"].state is PluginState.RUNNING
    assert plugins["hz_a"].state is PluginState.PAUSED
    assert _hooks("hz_src") == {"pause": 0, "resume": 0}
    assert orch.readiness_snapshot()["paused"] is True


def test_run_gated_false_source_not_paused_in_boot() -> None:
    """Первая пауза в boot() тоже пропускает ``run_gated: false`` — превью в ``ready`` (В2)."""
    event = _event(False)
    _, _, plugins = _boot([HzSource, HzA], event=event, extra={"hz_src": {"run_gated": False}})

    assert plugins["hz_src"].state is PluginState.RUNNING
    assert plugins["hz_a"].state is PluginState.PAUSED


def test_gated_source_paused_in_boot_and_produce_not_blocked_by_label() -> None:
    """Источник паузится в boot(); ``PAUSED`` — ярлык: ``call_produce`` его не режет (Н11)."""
    event = _event(False)
    _, _, plugins = _boot([HzSource], event=event)
    source = plugins["hz_src"]
    assert source.state is PluginState.PAUSED

    PluginRunner(log_error=lambda msg: None).call_produce(source)

    assert PRODUCE_CALLS == ["hz_src"], "produce() источника в PAUSED не вызван (ярлык не должен быть гейтом до 1.9)"


def test_produce_may_run_before_resume_documented() -> None:
    """Контракт хука ``pause/resume`` честно говорит, что ``produce()`` может идти раньше ``resume()``."""
    doc = (ProcessModulePlugin.pause.__doc__ or "") + (ProcessModulePlugin.resume.__doc__ or "")
    assert "produce()" in doc and "РАНЬШЕ" in doc


# --------------------------------------------------------------------------- #
# T9: упавший хук — причина failure, троттлинг, один лог на серию
# --------------------------------------------------------------------------- #


def _reasons(orch: PluginOrchestrator, node: str) -> list[str]:
    return [r["reason"] for r in orch.readiness_snapshot()["reasons"] if r["node"] == f"{_PROC}.{node}"]


def test_hook_failure_surfaces_failure_reason_and_retries() -> None:
    """``pause()`` упал: плагин ``RUNNING``, причина ``failure`` без текста исключения, повтор не чаще 1 с."""
    event = _event(True)
    orch, services, plugins = _boot([HzBadPause], event=event)
    event.clear()

    orch.reconcile_run_event()
    orch.reconcile_run_event()  # внутри интервала — хук не повторяется

    assert plugins["hz_bad_pause"].state is PluginState.RUNNING
    assert _hooks("hz_bad_pause")["pause"] == 1
    snap = orch.readiness_snapshot()
    assert snap["ready"] is False and snap["paused"] is False, snap
    assert _reasons(orch, "hz_bad_pause") == ["pause() упал: RuntimeError"]
    assert "секрет-путь" not in repr(snap)

    time.sleep(1.1)
    orch.reconcile_run_event()

    assert _hooks("hz_bad_pause")["pause"] == 2, "повтор после интервала не состоялся"
    pause_logs = [r["msg"] for r in services.logs if r["level"] == "ERROR" and "pause()" in r["msg"]]
    assert len(pause_logs) == 1, pause_logs  # один лог на серию


def test_failed_pause_reason_clears_when_target_flips() -> None:
    """``pause()`` упал, событие взведено снова: плагин ``RUNNING`` = цель, причина снимается (Д4)."""
    event = _event(True)
    orch, _, _ = _boot([HzBadPause], event=event)
    event.clear()
    orch.reconcile_run_event()
    assert _reasons(orch, "hz_bad_pause") == ["pause() упал: RuntimeError"]

    event.set()
    orch.reconcile_run_event()

    assert _reasons(orch, "hz_bad_pause") == []
    assert orch.readiness_snapshot()["ready"] is True


def test_failed_resume_reason_and_clear() -> None:
    """Зеркало: ``resume()`` упал — плагин ``PAUSED``, причина «resume() упал»; цель сменилась — причина снята."""
    event = _event(True)
    orch, _, plugins = _boot([HzBadResume], event=event)
    event.clear()
    orch.reconcile_run_event()
    assert plugins["hz_bad_resume"].state is PluginState.PAUSED
    event.set()

    orch.reconcile_run_event()

    assert plugins["hz_bad_resume"].state is PluginState.PAUSED
    assert _reasons(orch, "hz_bad_resume") == ["resume() упал: RuntimeError"]
    event.clear()
    orch.reconcile_run_event()
    assert _reasons(orch, "hz_bad_resume") == []


def test_idle_plugin_after_failed_configure_does_not_hold_paused_false() -> None:
    """Плагин в ``IDLE`` после упавшего ``configure`` не держит ``paused: false`` (но даёт причину ``failure``)."""
    event = _event(True)
    orch, _, _ = _boot([HzConfigureBroken, HzA], event=event)

    event.clear()
    orch.reconcile_run_event()

    snap = orch.readiness_snapshot()
    assert snap["paused"] is True, snap
    assert snap["ready"] is False, snap
    assert [r["reason"] for r in snap["reasons"]] == ["плагин не поднят (idle)"], snap


# --------------------------------------------------------------------------- #
# T14: нет наблюдателя — нет первой паузы
# --------------------------------------------------------------------------- #


def test_no_observer_means_no_boot_pause() -> None:
    """Событие снято, но наблюдателя нет (``_run_watch_enabled`` ложно/нет): плагины остаются ``RUNNING``."""
    _, _, plugins = _boot([HzA], event=_event(False), watch=False)
    assert plugins["hz_a"].state is PluginState.RUNNING

    # контрольное плечо: со стендом, умеющим ловить паузу
    _, _, plugins_watched = _boot([HzA], event=_event(False), watch=True)
    assert plugins_watched["hz_a"].state is PluginState.PAUSED


# --------------------------------------------------------------------------- #
# Раунд 2 (после раннего ревью Opus): уровень, замок shutdown, release_paused, два воркера
# --------------------------------------------------------------------------- #


def test_level_not_edge_forced_running_is_paused_again() -> None:
    """Сверка по УРОВНЮ: плагин принудительно в ``RUNNING`` при снятом событии без фронта -> снова ``PAUSED``."""
    event = _event(True)
    orch, _, plugins = _boot([HzA], event=event)
    plugin = plugins["hz_a"]
    event.clear()
    orch.reconcile_run_event()
    assert plugin.state is PluginState.PAUSED

    plugin.state = PluginState.RUNNING  # кто-то вернул ярлык; фронта события не было
    orch.reconcile_run_event()

    assert plugin.state is PluginState.PAUSED
    assert _hooks("hz_a") == {"pause": 2, "resume": 0}


def test_level_not_edge_forced_paused_is_resumed_again() -> None:
    """Зеркало: плагин принудительно в ``PAUSED`` при взведённом событии без фронта -> проход возвращает ``RUNNING``."""
    event = _event(True)
    orch, _, plugins = _boot([HzA], event=event)
    plugin = plugins["hz_a"]

    plugin.state = PluginState.PAUSED
    orch.reconcile_run_event()

    assert plugin.state is PluginState.RUNNING
    assert _hooks("hz_a") == {"pause": 0, "resume": 1}


ORDER: list[str] = []


class HzSlowPause(HzPlain):
    """``pause()`` короче таймаута замка shutdown (0,6 с < 2 с); пишет порядок событий."""

    name = "hz_slow_pause"

    def pause(self, ctx: PluginContext) -> None:
        ORDER.append("pause_start")
        time.sleep(0.6)
        ORDER.append("pause_end")

    def shutdown(self, ctx: PluginContext) -> None:
        ORDER.append("shutdown")


def test_shutdown_waits_short_pause_hook_and_does_not_resurrect() -> None:
    """Замок держит порядок БЕЗ защиты ``base.py``: ``shutdown()`` ждёт короткий ``pause()`` и лишь потом закрывает."""
    ORDER.clear()
    event = _event(True)
    orch, _, plugins = _boot([HzSlowPause], event=event)
    plugin = plugins["hz_slow_pause"]
    event.clear()
    worker = _in_thread(orch.reconcile_run_event)
    end = time.monotonic() + 10.0
    while ORDER != ["pause_start"] and time.monotonic() < end:
        time.sleep(0.005)
    assert ORDER == ["pause_start"], ORDER

    closer = _in_thread(orch.shutdown)
    time.sleep(0.2)
    assert closer.is_alive(), "shutdown() не дождался замка сверки: плагин закрывается под идущим хуком"
    assert ORDER == ["pause_start"], ORDER  # plugin.shutdown() ещё не позван
    _join(closer, "shutdown()", 10.0)
    _join(worker, "проход сверки")

    assert ORDER == ["pause_start", "pause_end", "shutdown"], ORDER
    assert plugin.state is PluginState.STOPPED


def test_release_paused_resumes_all_paused_plugins() -> None:
    """``release_paused()`` возвращает из паузы каждый ``PAUSED`` плагин (отказ создания ``run_watch``, m6)."""
    event = _event(False)
    orch, _, plugins = _boot([HzA, HzBadResume], event=event)
    assert {p.state for p in plugins.values()} == {PluginState.PAUSED}

    orch.release_paused()

    assert plugins["hz_a"].state is PluginState.RUNNING
    # упавший resume() не обрывает обход и не бросает наружу; плагин остаётся PAUSED (цель событием не менялась)
    assert plugins["hz_bad_resume"].state is PluginState.PAUSED
    assert _hooks("hz_bad_resume")["resume"] == 1


def _start_real(plugin_classes: list[type], event: Any) -> tuple[threading.Thread, threading.Event, Any]:
    SHARED["event"] = event
    SHARED["proc"] = None
    plugins = [{"plugin_class": f"{_THIS}.{c.__name__}", "plugin_name": c.name} for c in plugin_classes]
    cfg = {"config": {"plugins": plugins, "chain_targets": []}}
    own_ready = multiprocessing.Event()
    bundle = {
        "queues": {"data": multiprocessing.Queue()},
        "config": cfg,
        "custom": {"process_config": cfg, "ready_event": own_ready},
    }
    stop = threading.Event()
    thread = _in_thread(lambda: run_process_function(f"{_THIS}.WatchedGenericProcess", "rwh_gp2", stop, bundle, None))
    return thread, stop, own_ready


def _stop_real(thread: threading.Thread, stop: threading.Event) -> None:
    GATE.set()
    stop.set()
    thread.join(_JOIN_S)
    assert not thread.is_alive(), "run_process_function не вышел после stop"


@pytest.mark.timeout(120)
def test_run_watch_creation_failure_releases_boot_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """``create_worker("run_watch")`` бросил: плагины, спаузенные в boot(), возвращены из паузы (m6); процесс жив."""
    original = WorkerManager.create_worker

    def create_worker(self: Any, worker_name: str, *args: Any, **kwargs: Any) -> Any:
        if worker_name == "run_watch":
            raise RuntimeError("create_worker сломан")
        return original(self, worker_name, *args, **kwargs)

    monkeypatch.setattr(WorkerManager, "create_worker", create_worker)
    event = multiprocessing.Event()  # снято с рождения: boot() паузит плагины
    thread, stop, own_ready = _start_real([HzA], event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил готовность"
        proc = SHARED["proc"]
        plugin = proc._orchestrator.plugins[0]
        assert plugin.state is PluginState.RUNNING, "плагин остался в PAUSED без наблюдателя"
        assert _hooks("hz_a") == {"pause": 1, "resume": 1}
        workers = proc.worker_manager.get_all_workers_status()
        assert "run_watch" not in workers and "readiness_snapshot" in workers, sorted(workers)
    finally:
        _stop_real(thread, stop)


@pytest.mark.timeout(120)
def test_process_with_orchestrator_has_two_separate_state_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """В процессе с оркестратором два ОТДЕЛЬНЫХ воркера с разными целевыми функциями (Д1: не один общий цикл)."""
    original = WorkerManager.create_worker
    targets: dict[str, Any] = {}

    def create_worker(self: Any, worker_name: str, target: Any = None, *args: Any, **kwargs: Any) -> Any:
        targets[worker_name] = target
        return original(self, worker_name, target, *args, **kwargs)

    monkeypatch.setattr(WorkerManager, "create_worker", create_worker)
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start_real([HzA], event)
    try:
        assert own_ready.wait(_JOIN_S)
        workers = SHARED["proc"].worker_manager.get_all_workers_status()
        assert "run_watch" in workers and "readiness_snapshot" in workers, sorted(workers)
        assert targets["run_watch"].__name__ == "_run_watch_loop", targets
        assert targets["readiness_snapshot"].__name__ == "_readiness_snapshot_loop", targets
    finally:
        _stop_real(thread, stop)


@pytest.mark.timeout(120)
def test_real_process_blocked_readiness_does_not_stall_pause() -> None:
    """Настоящий процесс: ``readiness()`` завис в потоке снимка — пауза остальных идёт (потоки раздельны)."""
    event = multiprocessing.Event()
    event.set()
    thread, stop, own_ready = _start_real([HzBlockReadiness, HzA], event)
    try:
        assert own_ready.wait(_JOIN_S)
        assert ENTERED.wait(10.0), "readiness() не вызван потоком снимка"
        plugins = {p.name: p for p in SHARED["proc"]._orchestrator.plugins}

        event.clear()

        end = time.monotonic() + 8.0
        while plugins["hz_a"].state is not PluginState.PAUSED and time.monotonic() < end:
            time.sleep(0.02)
        assert plugins["hz_a"].state is PluginState.PAUSED, "зависший readiness() остановил сверку"
    finally:
        _stop_real(thread, stop)
