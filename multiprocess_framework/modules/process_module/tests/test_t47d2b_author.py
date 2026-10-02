# -*- coding: utf-8 -*-
"""Task 4.7d-2b — авторские hazard-тесты исполнителя (проход маркера и ``stale_exec``).

Что может сломаться именно в ЭТОМ механизме:
  * смешанная коллекция (маркер + обычный item) ошибочно принята за маркерную и обходит плагин;
  * плагин мутирует dict входа на месте -> маркер ``stale_exec``, собранный ПОСЛЕ цепочки, потерял бы trace_id;
  * маркер-коллекция, пройдя мимо упавшего/критического плагина, всё же трогает breaker.
"""

from __future__ import annotations

import os
import time

import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker, is_marker
from multiprocess_framework.modules.router_module.tests import test_frame_ref_gen as _T


@pytest.fixture
def rig(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)
    r = _T._Rig()
    yield r
    r.close()


class _Plugin:
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self, name: str, fn=None, on_process=None, fail: bool = False) -> None:
        self.name = name
        self._fn, self._on_process, self._fail = fn, on_process, fail
        self.calls = 0
        self.seen: list[list[dict]] = []

    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        self.seen.append(list(items))
        if self._fail:
            raise ValueError("intentional failure")
        if self._on_process is not None:
            self._on_process()
        return self._fn(items) if self._fn is not None else items


def _executor(plugins, *, shm=None, overflow="latest", sent=None, **kw) -> PipelineExecutor:
    sent = sent if sent is not None else []
    return PipelineExecutor(
        plugins=list(plugins),
        chain_targets=["out"],
        shm_middleware=shm,
        send_fn=lambda target, msg: sent.append((target, msg)),
        node_name="exec_node",
        overflow=overflow,
        **kw,
    )


def _marker(trace_id: str) -> dict:
    return build_marker({"trace_id": trace_id, "capture_ts": 1.0}, reason="lag", source="up")


def test_mixed_collection_takes_normal_path_and_plugin_sees_the_marker_inside():
    """[маркер, обычный item]: коллекция НЕ маркерная -> плагин без accepts_markers вызван 1 раз на ВСЕЙ
    коллекции (маркер внутри не вырезан и не тронут), not_inspected_handled не растёт."""
    plugin = _Plugin("plain")
    sent: list = []
    ex = _executor([plugin], sent=sent)
    marker, normal = _marker("m1"), {"trace_id": "n1", "x": 1}

    _T._bounded(lambda: ex._run_batch([marker, normal], time.perf_counter()))

    assert plugin.calls == 1
    assert plugin.seen[0][0] is marker and plugin.seen[0][1] is normal
    assert is_marker(marker) and marker["trace_id"] == "m1"
    assert ex.get_cycle_metrics()["not_inspected_handled"] == 0
    assert len(sent) == 2  # обычный путь: оба item'а ушли по одному target


def test_post_chain_stale_markers_carry_original_trace_ids_when_plugin_mutates_input_in_place(rig):
    """Плагин на месте портит dict входа (trace_id/capture_ts) и возвращает его же; слот перезаписан во время
    process, every: оба маркера stale_exec несут ИСХОДНЫЕ trace_id/capture_ts (собраны до цепочки)."""
    writer, reader = rig.make("A"), rig.make("B")
    items = []
    for i in (1, 2):
        wire = _T._wire(_T._send(writer, {"frame": _T._arr("frame", i), "trace_id": f"t{i}", "capture_ts": float(i)}))
        items.append(_T._receive_as_pipeline(reader, wire))

    def corrupt(its: list[dict]) -> list[dict]:
        for it in its:
            it["trace_id"] = "mutated"
            it.pop("capture_ts", None)
        return its

    plugin = _Plugin("p", fn=corrupt, on_process=lambda: _T._overwrite(writer, "frame"))
    sent: list = []
    ex = _executor([plugin], shm=reader, overflow="every", sent=sent)

    _T._bounded(lambda: ex._run_batch(items, time.perf_counter()))

    data = [m["data"] for _t, m in sent]
    assert all(is_marker(d) for d in data), data
    assert [(d["trace_id"], d["capture_ts"]) for d in data] == [("t1", 1.0), ("t2", 2.0)]
    assert plugin.calls == 1


def test_breaker_untouched_by_100_marker_batches_through_live_failing_and_bypassed_critical_plugins():
    """В цепочке критический bypassed плагин (SuspectTagStep на его позиции) и живой падающий плагин; 100
    маркер-коллекций: process 0 раз, consecutive_fails/bypass без изменений (живой не получил ни сбоя, ни
    успеха), тег не перетёрт suspect, not_inspected_handled == 100."""
    crit = _Plugin("crit", fail=True)
    live = _Plugin("live", fail=True)
    sent: list = []
    ex = _executor([crit, live], sent=sent, max_consecutive_fails=5, critical_plugins=["crit"])
    ex._bypassed["crit"] = True  # критический плагин в bypass: на его позиции стоит SuspectTagStep
    ex._steps_dirty = True
    state = (dict(ex._consecutive_fails), dict(ex._bypassed))

    def run() -> None:
        for i in range(100):
            ex._run_batch([_marker(f"m{i}")], time.perf_counter())

    _T._bounded(run)

    assert (dict(ex._consecutive_fails), dict(ex._bypassed)) == state
    assert (crit.calls, live.calls) == (0, 0)
    assert len(sent) == 100
    assert all(m["data"]["inspection_status"] == "not_inspected" for _t, m in sent)
    assert ex.get_cycle_metrics()["not_inspected_handled"] == 100
