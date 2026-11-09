# -*- coding: utf-8 -*-
"""Task 1.1 (system-run-state) — слепые тесты гейта работы в ``SourceProducer`` и в настоящем ``GenericProcess``.

Контракт — DESIGN пп.4 и 6 ``plans/2026-10-27_system-run-state/tasks/1.1.md``:
  * ``SourceProducer(..., run_event: Any | None = None, run_gated: bool = True)``;
  * в ``run_loop`` ветка паузы срабатывает и при ``run_event is not None and run_gated and not run_event.is_set()``
    (сон 0.05 с, ``continue``, без срока); ``run_gated=False`` -> событие не смотрится;
  * ``run_gated`` — ключ конфига source-плагина (плоский ``ctx.config``, умолчание ``True``), берётся
    ``GenericProcess`` через ``PluginOrchestrator.config_of(plugin)``.

Наблюдаем эффект — число вызовов ``produce()``, а не имя метода. Блокирующие вызовы — в daemon-потоках с join-дедлайном.
Образец настоящего процесса — ``process_manager_module/tests/test_t54_generic_process_preroll_hazards.py``.

Решения тестера: событие в настоящем ``GenericProcess`` кладётся атрибутом ``_run_event`` через подкласс (DESIGN п.3:
«атрибут ``_run_event`` ребёнка до ``initialize()``»), чтобы тест не зависел от проводки раннера (её держит
``test_run_event_wiring``).
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

_THIS = "multiprocess_framework.modules.process_module.tests.test_source_run_gate"
_JOIN_S = 15.0
#: Сколько ждём, чтобы убедиться, что кадров НЕТ (>> шага сна закрытой ветки 0.05 с и интервала кадра 10 мс).
_QUIET_S = 0.4

_DEFAULT = object()  # run_gated не передаётся вовсе


class _Counting:
    """Source-плагин: каждый produce() — +1 к счётчику, кадров не отдаёт."""

    is_source = True

    def __init__(self) -> None:
        self.name = "run_gate_src"
        self.calls = 0

    def produce(self) -> list:
        self.calls += 1
        return []


def _wait_calls(plugin: _Counting, at_least: int, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if plugin.calls >= at_least:
            return True
        time.sleep(0.005)
    return plugin.calls >= at_least


# --------------------------------------------------------------------------- #
# SourceProducer: гейт на уровне цикла
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("event_set", [False, True], ids=["event-clear", "event-set"])
@pytest.mark.parametrize("run_gated", [_DEFAULT, True, False], ids=["gated-default", "gated-true", "gated-false"])
def test_source_gate(run_gated: Any, event_set: bool) -> None:
    """produce() не вызывается только при run_gated истинном (по умолчанию True) и снятом событии; после set() идёт."""
    plugin = _Counting()
    event = threading.Event()
    if event_set:
        event.set()
    kwargs: dict[str, Any] = {} if run_gated is _DEFAULT else {"run_gated": run_gated}
    producer = SourceProducer(
        plugin=plugin,
        shm_middleware=None,
        send_fn=lambda target, msg: None,
        chain_targets=[],
        target_fps=100.0,
        node_name="run_gate_src",
        run_event=event,
        **kwargs,
    )
    stop = threading.Event()
    thread = threading.Thread(target=producer.run_loop, args=(stop, threading.Event()), daemon=True, name="gate-loop")
    thread.start()
    try:
        gated_closed = (run_gated is not False) and not event_set
        if gated_closed:
            time.sleep(_QUIET_S)
            assert plugin.calls == 0, f"produce() вызван {plugin.calls} раз при закрытом гейте"
            event.set()
            assert _wait_calls(plugin, 3, 5.0), "после set() производство не возобновилось"
        else:
            assert _wait_calls(plugin, 3, 5.0), (
                f"гейт не закрыт (run_gated={run_gated!r}, set={event_set}), а кадров нет"
            )
    finally:
        stop.set()
        thread.join(_JOIN_S)
    assert not thread.is_alive(), "run_loop не вышел после stop"


# --------------------------------------------------------------------------- #
# Настоящий GenericProcess + два source-плагина: событие и шов config_of (ключ run_gated у КАЖДОГО плагина свой)
# --------------------------------------------------------------------------- #

#: Метки produce() настоящих плагинов по ключу ``a``/``b`` и текущее событие процесса (подменяются тестом).
GP_CALLS: dict[str, list[float]] = {"a": [], "b": []}
GP_EVENT: dict[str, Any] = {"ev": None}


class _GateCountSource(ProcessModulePlugin):
    """Настоящий source-плагин: каждый produce() фиксирует метку времени, кадров не отдаёт."""

    category = "source"
    key = ""

    def configure(self, ctx) -> None:  # noqa: D401 — контракт плагина
        pass

    def start(self, ctx) -> None:
        pass

    def produce(self) -> list:
        GP_CALLS[self.key].append(time.perf_counter())
        return []


class GateSrcA(_GateCountSource):
    name = "run_gate_src_a"
    key = "a"


class GateSrcB(_GateCountSource):
    name = "run_gate_src_b"
    key = "b"


class GatedGenericProcess(GenericProcess):
    """Настоящий GenericProcess; ``_run_event`` стоит на экземпляре до ``initialize()`` (как поставит раннер)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = GP_EVENT["ev"]


def _start_process(a_extra: dict, b_extra: dict, run_event) -> tuple[threading.Thread, threading.Event, Any]:
    for calls in GP_CALLS.values():
        calls.clear()
    GP_EVENT["ev"] = run_event
    plugins = [
        {"plugin_class": f"{_THIS}.GateSrcA", "plugin_name": GateSrcA.name, **a_extra},
        {"plugin_class": f"{_THIS}.GateSrcB", "plugin_name": GateSrcB.name, **b_extra},
    ]
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
        args=(f"{_THIS}.GatedGenericProcess", "run_gate_gp", stop, bundle, None),
        daemon=True,
        name="run-gate-generic-process",
    )
    thread.start()
    return thread, stop, own_ready


def _wait_gp_calls(key: str, at_least: int, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if len(GP_CALLS[key]) >= at_least:
            return True
        time.sleep(0.005)
    return len(GP_CALLS[key]) >= at_least


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("a_extra", "b_extra", "gated_keys", "free_keys"),
    [
        ({}, {"run_gated": True}, ["a", "b"], []),  # ключа нет / True -> оба держит событие
        ({}, {"run_gated": False}, ["a"], ["b"]),  # плоский ключ в определении плагина
        ({}, {"config": {"run_gated": False}}, ["a"], ["b"]),  # вложенный config (GUI-форма) -> плоский ctx.config
        ({"run_gated": False}, {}, ["b"], ["a"]),  # шов по плагину, а не по порядку в списке
    ],
    ids=["absent-and-true", "b-false-flat", "b-false-nested", "a-false-flat"],
)
def test_real_generic_process_gate_and_run_gated_seam(a_extra, b_extra, gated_keys, free_keys) -> None:
    """Событие снято: у плагина без ключа или с True produce 0; ``run_gated: False`` в его конфиге -> produce идёт."""
    event = multiprocessing.Event()  # снято
    thread, stop, own_ready = _start_process(a_extra, b_extra, event)
    try:
        assert own_ready.wait(_JOIN_S), "процесс не объявил собственную готовность за 15 с"
        for key in free_keys:
            assert _wait_gp_calls(key, 3, 5.0), f"плагин {key}: run_gated false, а кадров при снятом событии нет"
        time.sleep(_QUIET_S)
        for key in gated_keys:
            assert GP_CALLS[key] == [], f"плагин {key}: produce() вызван {len(GP_CALLS[key])} раз при снятом событии"
        event.set()
        for key in gated_keys:
            assert _wait_gp_calls(key, 3, 5.0), f"плагин {key}: после set() производство не возобновилось"
        event.clear()
        time.sleep(0.2)  # дать циклу заметить закрытие (сон закрытой ветки 0.05 с)
        before = {k: len(GP_CALLS[k]) for k in gated_keys}
        time.sleep(_QUIET_S)
        for key in gated_keys:
            assert len(GP_CALLS[key]) <= before[key] + 1, f"плагин {key}: после clear() производство не остановилось"
    finally:
        stop.set()
        thread.join(_JOIN_S)
    assert not thread.is_alive(), "run_process_function не вышел после stop"
