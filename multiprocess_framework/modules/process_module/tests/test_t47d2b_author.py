# -*- coding: utf-8 -*-
"""Task 4.7d-2b — авторские hazard-тесты исполнителя (проход маркера и ``stale_exec``).

Что может сломаться именно в ЭТОМ механизме:
  * смешанная коллекция (маркер + обычный item) ошибочно принята за маркерную и обходит плагин;
  * плагин мутирует dict входа на месте -> маркер ``stale_exec``, собранный ПОСЛЕ цепочки, потерял бы trace_id;
  * маркер-коллекция, пройдя мимо упавшего/критического плагина, всё же трогает breaker.
"""

from __future__ import annotations

import os
import queue
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import _MarkerBatch, _StampedBatch
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.port import Port, PortValidationError
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import (
    build_marker,
    is_marker,
    is_marker_collection,
)
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
    process, every: оба маркера stale_exec несут ИСХОДНЫЕ trace_id/capture_ts (собраны до цепочки).
    Task 5.3 (намеренно): маркеры уезжают одной записью о разрыве — исходные id в ``trace_ids``, ts в first/last."""
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
    assert [(d["count"], d["trace_ids"], d["first_capture_ts"], d["last_capture_ts"]) for d in data] == [
        (2, ["t1", "t2"], 1.0, 2.0)
    ]
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


# --------------------------------------------------------------------------------------------
# Ревью 2a/2b: маркер-коллекция не загрязняет метрики исполнителя (queue_wait_ms EMA, цикл)
# --------------------------------------------------------------------------------------------
def _drive_loop(ex: PipelineExecutor, batches: list, expect_sent: int, sent: list) -> None:
    """Прогнать ``run_loop`` реальной очередью: положить батчи, дождаться отправок, остановить и дождаться выхода
    (после ``join`` итерация, включая запись цикла, завершена целиком)."""
    chain: queue.Queue = queue.Queue()
    for b in batches:
        chain.put(b)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=ex.run_loop, args=(chain, stop, pause), daemon=True)
    worker.start()
    deadline = time.monotonic() + _T.DEADLINE_S
    while len(sent) < expect_sent and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    worker.join(_T.DEADLINE_S)
    assert len(sent) == expect_sent and not worker.is_alive(), f"sent={len(sent)}, ожидалось {expect_sent}"


def test_marker_only_batch_leaves_queue_wait_ema_and_cycle_metrics_untouched():
    """Маркер-коллекция, ждавшая в очереди 5 с, и ничего больше: ``queue_wait_ms == 0.0`` (в EMA не вошла),
    ``cycles == 0``, ``cycle_duration_ms == 0.0`` — но отправлена (1) и ``not_inspected_handled == 1``."""
    sent: list = []
    ex = _executor([_Plugin("p")], sent=sent)
    batch = _MarkerBatch([_marker("m1")])
    batch.enq_ts = time.perf_counter() - 5.0

    _drive_loop(ex, [batch], 1, sent)

    metrics = ex.get_cycle_metrics()
    assert metrics["queue_wait_ms"] == 0.0
    assert metrics["cycles"] == 0 and metrics["cycle_duration_ms"] == 0.0
    assert metrics["not_inspected_handled"] == 1


def test_frame_batch_after_marker_batch_is_the_only_one_in_ema_and_cycles_control():
    """CONTROL: маркер-коллекция (ждала 5 с), затем кадровая (ждала 0.5 с). EMA = ровно ожидание кадра
    (400..700 мс; если бы маркер вошёл, первая проба дала бы 5000 и EMA ушла бы за 4000), ``cycles == 1``."""
    sent: list = []
    ex = _executor([_Plugin("p")], sent=sent)
    markers = _MarkerBatch([_marker("m1")])
    markers.enq_ts = time.perf_counter() - 5.0
    frames = _StampedBatch([{"trace_id": "f1", "x": 1}])
    frames.enq_ts = time.perf_counter() - 0.5

    _drive_loop(ex, [markers, frames], 2, sent)

    metrics = ex.get_cycle_metrics()
    assert 400.0 <= metrics["queue_wait_ms"] <= 700.0, metrics["queue_wait_ms"]
    assert metrics["cycles"] == 1
    assert metrics["not_inspected_handled"] == 1


# --------------------------------------------------------------------------------------------
# Ревью 2b (minor): порты проверяются по ITEM, маркерный вход не оправдывает невалидный НЕмаркерный выход
# --------------------------------------------------------------------------------------------
class _PortPlugin:
    enabled = True
    name = "ported"
    inputs = [Port(name="frame")]
    outputs = [Port(name="mask")]

    def __init__(self, fn) -> None:
        self._fn = fn

    def process(self, items: list[dict]) -> list[dict]:
        return self._fn(items)


def _call(plugin, items):
    return PluginRunner(validate_ports=True).call_process(plugin, items)


def test_ports_marker_input_does_not_excuse_invalid_non_marker_output():
    """Вход — маркер (портов не проверяем), выход — маркер + item без порта ``mask``: PortValidationError на item."""
    plugin = _PortPlugin(lambda its: [_marker("m1"), {"trace_id": "bad"}])
    with pytest.raises(PortValidationError, match="mask"):
        _call(plugin, [_marker("m0")])


def test_ports_mixed_input_validates_the_non_marker_item():
    """Вход [маркер, item без ``frame``]: коллекция не маркерная и маркер внутри не оправдывает item."""
    plugin = _PortPlugin(lambda its: [{"mask": 1}])
    with pytest.raises(PortValidationError, match="frame"):
        _call(plugin, [_marker("m0"), {"trace_id": "bad"}])


def test_ports_mixed_input_with_valid_item_passes_marker_is_not_validated():
    """Вход [маркер, валидный item ``frame``]: маркер без порта ``frame`` ошибки не даёт (порты — по ITEM, а не по
    коллекции: смешанная коллекция раньше проверялась целиком и маркер внутри её валил)."""
    out = _call(_PortPlugin(lambda its: [{"mask": 1}]), [_marker("m0"), {"frame": 1}])
    assert out[0]["mask"] == 1


def test_ports_pure_marker_in_and_out_pass_and_valid_items_pass_control():
    """Маркер на входе и выходе при обязательных портах — не ошибка; CONTROL: валидный item проходит."""
    out = _call(_PortPlugin(lambda its: its), [_marker("m0")])
    assert len(out) == 1 and out[0]["inspection_status"] == "not_inspected" and out[0]["trace_id"] == "m0"
    out = _call(_PortPlugin(lambda its: [{"mask": 1}]), [{"frame": 1}])
    assert out[0]["mask"] == 1


# --------------------------------------------------------------------------------------------
# Ревью 2a (nit 4 + DRY): одно определение is_marker_collection
# --------------------------------------------------------------------------------------------
def test_single_marker_collection_predicate_lives_in_marker_module():
    """Потребители берут ОДИН объект функции из ``not_inspected_marker``; старых имён нет."""
    from multiprocess_framework.modules.process_module.generic import (
        data_receiver,
        pipeline_executor,
        plugin_operation_step,
        plugin_runner,
    )

    assert pipeline_executor.is_marker_collection is is_marker_collection
    assert plugin_operation_step.is_marker_collection is is_marker_collection
    assert not hasattr(plugin_runner, "is_marker_collection")
    assert not hasattr(data_receiver.DataReceiver, "_is_marker_collection")
