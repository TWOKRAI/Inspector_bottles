# -*- coding: utf-8 -*-
"""Task 5.3 — слепые приёмочные тесты приёмника: слияние маркер-коллекций в хвост и формула ADR-174 в items.

Независимый tester, от acceptance Task 5.3 (plans/transport-single-policy/phase-5.md, «### Task 5.3»),
без чтения реализации 5.3 (её в дереве нет). Ожидаемые значения — литералы.

Что пинится:
  * 1000 IPC-записей в узел, чей исполнитель стоит (из ``chain_queue`` никто не читает), в обоих режимах
    (``latest`` / ``every``) и при ``max_lag_items`` 0 и 4: ``chain_queue.qsize() <= 2``, ``overload_events == 0``,
    все 1000 приняты за <= 2 с, ничего не потеряно и порядок цел;
  * слияние только в ХВОСТ: запись после кадровой коллекции открывает новую маркер-коллекцию (порядок очереди
    не меняется);
  * гонка слияния с живым исполнителем: ни одна запись не теряется (Σ count = 2000, ``trace_ids`` в порядке входа,
    ``handled`` = 2000);
  * юнит-риг ADR-174 п. 5 в items: источник -> processor (``every``, потолок 2, исполнитель стоит, пока приёмник
    не принял все 300 кадров) -> inspector: ``Σ born(processor) > 0`` (сторож от пустого рига),
    ``handled(inspector) - own(inspector) == Σ born(processor)``; разрыв уезжает ОДНОЙ записью.

Зелёные контроли (зелёные и до реализации: сегодня ``handled`` считает маркеры по одному, а ``born`` — items):
формула ADR-174 и литерал рига (298 из 300). Формула нужна, чтобы реализация, считающая ``handled`` по записям,
упала здесь. Всё остальное — красное до реализации (``AssertionError``: приёмник блокируется на ``put`` и не
принимает 1000 записей за 2 с; ``send_fn`` получает 298 сообщений-маркеров вместо одной записи).

Всё, что может заблокироваться (``run_loop``, ``run``, ``on_items_ready``), гоняется в daemon-потоке с дедлайном;
после теста потоки гасятся через ``stop_event``.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver, _MarkerBatch
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import is_marker

DEADLINE_S = 15.0
ACCEPT_S = 2.0  # acceptance: «все 1000 приняты за <= 2 с»
N_RECORDS = 1000
SERVICE_KEYS = {"_t_sent_ns", "_t_send", "_from"}


# --------------------------------------------------------------------------------------------
# общие кирпичи
# --------------------------------------------------------------------------------------------
class _SpyCollector:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def on_item(self, item: dict) -> None:
        self.items.append(item)

    def check_timeouts(self) -> None:
        return None

    def pending_count(self) -> int:
        return 0


class _Passthrough:
    """Коллектор «один item = одна коллекция»: сразу отдаёт item приёмнику (боевой одиночный join)."""

    def __init__(self) -> None:
        self.receiver: DataReceiver | None = None

    def on_item(self, item: dict) -> None:
        assert self.receiver is not None
        self.receiver.on_items_ready([item])

    def check_timeouts(self) -> None:
        return None

    def pending_count(self) -> int:
        return 0


class _Plugin:
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self, name: str) -> None:
        self.name = name

    def process(self, items: list[dict]) -> list[dict]:
        return items


def _record(i: int) -> dict:
    """Запись о разрыве count=2 (литерал): ``trace_ids`` r{i}a, r{i}b."""
    return {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "count": 2,
        "trace_ids": [f"r{i}a", f"r{i}b"],
        "first_capture_ts": float(2 * i),
        "last_capture_ts": float(2 * i + 1),
        "reasons": {"lag": 2},
        "sources": {"upstream": 2},
        "source": "upstream",
        "camera_id": "cam0",
    }


def _ipc(data: dict) -> dict:
    return {"data": dict(data), "sender": "upstream", "type": "data", "channel": "data"}


def _all_ids() -> list[str]:
    return [t for i in range(N_RECORDS) for t in (f"r{i}a", f"r{i}b")]


class _Feed:
    """receive_fn над списком сообщений; ``drained`` взводится, когда приёмник пришёл за следующим."""

    def __init__(self, messages: list[dict]) -> None:
        self.pending = list(messages)
        self.drained = threading.Event()

    def __call__(self, **_kwargs: Any) -> dict | None:
        if self.pending:
            return self.pending.pop(0)
        self.drained.set()
        return None


def _start(target, *args) -> threading.Thread:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def _receiver(chain: queue.Queue, feed, *, overflow: str, lag: int, node: str = "recv", collector=None):
    return DataReceiver(
        receive_fn=feed,
        shm_middleware=None,
        item_collector=collector if collector is not None else _SpyCollector(),
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        node_name=node,
        max_lag_items=lag,
        overflow=overflow,
    )


def _flatten(chain: queue.Queue) -> list[dict]:
    with chain.mutex:
        return [it for coll in chain.queue for it in coll]


# --------------------------------------------------------------------------------------------
# 1000 IPC-записей, исполнитель стоит
# --------------------------------------------------------------------------------------------
def _flood(overflow: str, lag: int):
    """1000 IPC-записей через ``run_loop``; из ``chain_queue`` (maxsize=64) никто не читает.
    Возвращает (приёмник, очередь, принято_за_2с). Поток гасится в любом случае."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    feed = _Feed([_ipc(_record(i)) for i in range(N_RECORDS)])
    receiver = _receiver(chain, feed, overflow=overflow, lag=lag)
    stop, pause = threading.Event(), threading.Event()
    worker = _start(receiver.run_loop, stop, pause)
    accepted = feed.drained.wait(ACCEPT_S)
    stop.set()
    worker.join(DEADLINE_S)
    if worker.is_alive():
        pytest.fail("run_loop не завершился после stop_event")
    return receiver, chain, accepted


@pytest.mark.parametrize("lag", [0, 4])
@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_flood_of_1000_ipc_records_is_accepted_within_2s_without_overload(overflow, lag):
    receiver, _chain, accepted = _flood(overflow, lag)

    assert accepted, "приёмник не принял 1000 IPC-записей за 2 с (блокируется на put в заполненную очередь)"
    assert receiver.overload_events == 0


@pytest.mark.parametrize("lag", [0, 4])
@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_flood_of_1000_ipc_records_occupies_at_most_two_queue_slots(overflow, lag):
    _receiver_, chain, _accepted = _flood(overflow, lag)

    assert chain.qsize() <= 2


@pytest.mark.parametrize("lag", [0, 4])
@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_flood_of_1000_ipc_records_loses_nothing_and_keeps_order(overflow, lag):
    _receiver_, chain, accepted = _flood(overflow, lag)

    assert accepted
    items = _flatten(chain)
    assert len(items) == N_RECORDS
    assert [t for it in items for t in it["trace_ids"]] == _all_ids()


# --------------------------------------------------------------------------------------------
# слияние только в хвост
# --------------------------------------------------------------------------------------------
def _marker_coll(i: int) -> _MarkerBatch:
    batch = _MarkerBatch([_record(i)])
    return batch


def _frame_coll(tag: str) -> list[dict]:
    return [{"frame": np.zeros((2, 2), dtype=np.uint8), "trace_id": tag}]


def test_gap_record_after_frame_collection_starts_a_new_marker_collection():
    """Очередь после подачи [rec0, rec1, frame, rec2, rec3] — три коллекции: [rec0 rec1] [frame] [rec2 rec3]
    (слияние через кадровую коллекцию нарушило бы порядок)."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, _Feed([]), overflow="latest", lag=0)

    def feed() -> None:
        for coll in (_marker_coll(0), _marker_coll(1), _frame_coll("F"), _marker_coll(2), _marker_coll(3)):
            receiver.on_items_ready(coll)

    t = _start(feed)
    t.join(DEADLINE_S)
    assert not t.is_alive(), "on_items_ready завис"

    with chain.mutex:
        shape = [[it.get("trace_ids") or it.get("trace_id") for it in coll] for coll in chain.queue]
    assert shape == [
        [["r0a", "r0b"], ["r1a", "r1b"]],
        ["F"],
        [["r2a", "r2b"], ["r3a", "r3b"]],
    ]


def test_merged_marker_collections_keep_marker_batch_type():
    """Слитая коллекция остаётся ``_MarkerBatch`` (иначе ``_bound_lag`` снова ходит по её содержимому)."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, _Feed([]), overflow="every", lag=0)

    t = _start(lambda: [receiver.on_items_ready(_marker_coll(i)) for i in range(5)])
    t.join(DEADLINE_S)
    assert not t.is_alive()

    with chain.mutex:
        colls = list(chain.queue)
    assert len(colls) == 1
    assert isinstance(colls[0], _MarkerBatch)
    assert len(colls[0]) == 5


# --------------------------------------------------------------------------------------------
# гонка слияния с живым исполнителем
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_live_executor_and_merging_receiver_lose_no_record(overflow):
    """Исполнитель читает ``chain_queue``, пока приёмник льёт 1000 записей: Σ count отправленного = 2000,
    ``trace_ids`` склеены в порядке входа, ``handled`` = 2000 (число записей на выходе от тайминга не зависит)."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    feed = _Feed([_ipc(_record(i)) for i in range(N_RECORDS)])
    receiver = _receiver(chain, feed, overflow=overflow, lag=0)
    sent: list = []
    ex = PipelineExecutor(
        plugins=[],
        chain_targets=["next"],
        shm_middleware=None,
        send_fn=lambda target, msg: sent.append((target, msg)),
        node_name="recv",
        overflow=overflow,
    )
    ex.bind_queue(chain)
    r_stop, r_pause = threading.Event(), threading.Event()
    e_stop, e_pause = threading.Event(), threading.Event()
    r_worker = _start(receiver.run_loop, r_stop, r_pause)
    e_worker = _start(ex.run, e_stop, e_pause)

    drained = feed.drained.wait(DEADLINE_S)
    r_stop.set()
    r_worker.join(DEADLINE_S)
    waiter = threading.Event()
    for _ in range(int(DEADLINE_S / 0.01)):
        if chain.empty():
            break
        waiter.wait(0.01)
    e_stop.set()
    e_worker.join(DEADLINE_S)

    assert drained, "приёмник не дочитал 1000 записей"
    assert not e_worker.is_alive(), "исполнитель не завершил такт за дедлайн"
    data = [msg["data"] for _t, msg in sent]
    assert sum(d["count"] for d in data) == 2 * N_RECORDS
    assert [t for d in data for t in d["trace_ids"]] == _all_ids()
    assert all(len(d["trace_ids"]) == d["count"] for d in data)
    assert ex.get_cycle_metrics()["not_inspected_handled"] == 2 * N_RECORDS


# --------------------------------------------------------------------------------------------
# юнит-риг ADR-174: источник -> processor (every, исполнитель стоит) -> inspector
# --------------------------------------------------------------------------------------------
N_FRAMES = 300


def _frame_msg(i: int) -> dict:
    data = {"frame": np.zeros((2, 2), dtype=np.uint8), "trace_id": f"f{i}", "capture_ts": float(i), "camera_id": "cam0"}
    return {"data": data, "sender": "source", "type": "data", "channel": "data"}


def _run_line():
    """300 кадров -> processor (``every``, потолок 2, исполнитель на паузе, пока приёмник не принял все 300) ->
    фейковый ``send_fn`` -> inspector (``every``, без потолка). Время паузы не моделируется: пауза = «исполнитель
    не стартовал до конца приёма», что детерминированно и не зависит от часов."""
    # --- processor
    chain_p: queue.Queue = queue.Queue(maxsize=64)
    feed_p = _Feed([_frame_msg(i) for i in range(N_FRAMES)])
    passthrough_p = _Passthrough()
    rcv_p = _receiver(chain_p, feed_p, overflow="every", lag=2, node="processor", collector=passthrough_p)
    passthrough_p.receiver = rcv_p
    sent_p: list = []
    ex_p = PipelineExecutor(
        plugins=[_Plugin("p")],
        chain_targets=["inspector"],
        shm_middleware=None,
        send_fn=lambda target, msg: sent_p.append((target, msg)),
        node_name="processor",
        overflow="every",
    )
    ex_p.bind_queue(chain_p)
    e_stop, e_pause = threading.Event(), threading.Event()
    e_pause.set()  # исполнитель стоит
    e_worker = _start(ex_p.run, e_stop, e_pause)
    r_stop, r_pause = threading.Event(), threading.Event()
    r_worker = _start(rcv_p.run_loop, r_stop, r_pause)
    assert feed_p.drained.wait(DEADLINE_S), "processor не принял 300 кадров"
    r_stop.set()
    r_worker.join(DEADLINE_S)
    e_pause.clear()  # исполнитель поехал: дренаж
    waiter = threading.Event()
    for _ in range(int(DEADLINE_S / 0.01)):
        if chain_p.empty():
            break
        waiter.wait(0.01)
    e_stop.set()
    e_worker.join(DEADLINE_S)
    assert not e_worker.is_alive(), "исполнитель processor завис"

    # --- inspector: ему приходит то, что processor отправил (порядок отправки)
    chain_i: queue.Queue = queue.Queue(maxsize=64)
    feed_i = _Feed([msg for _t, msg in sent_p])
    passthrough_i = _Passthrough()
    rcv_i = _receiver(chain_i, feed_i, overflow="every", lag=0, node="inspector", collector=passthrough_i)
    passthrough_i.receiver = rcv_i
    ex_i = PipelineExecutor(
        plugins=[],
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=lambda target, msg: None,
        node_name="inspector",
        overflow="every",
    )
    ex_i.bind_queue(chain_i)
    ie_stop, ie_pause = threading.Event(), threading.Event()
    ie_worker = _start(ex_i.run, ie_stop, ie_pause)
    ir_stop, ir_pause = threading.Event(), threading.Event()
    ir_worker = _start(rcv_i.run_loop, ir_stop, ir_pause)
    assert feed_i.drained.wait(DEADLINE_S), "inspector не принял отправленное processor"
    ir_stop.set()
    ir_worker.join(DEADLINE_S)
    for _ in range(int(DEADLINE_S / 0.01)):
        if chain_i.empty():
            break
        waiter.wait(0.01)
    ie_stop.set()
    ie_worker.join(DEADLINE_S)
    assert not ie_worker.is_alive(), "исполнитель inspector завис"
    return rcv_p, ex_p, sent_p, rcv_i, ex_i


def _born(rcv: DataReceiver, ex: PipelineExecutor) -> int:
    """Все рождения узла без двери (в риге нет SHM): lag + stale_restore + stale_exec."""
    r, e = rcv.get_cycle_metrics(), ex.get_cycle_metrics()
    return r["not_inspected_lag"] + r["not_inspected_stale_restore"] + e["not_inspected_stale_exec"]


def test_adr174_formula_in_items_handled_minus_own_equals_born_of_neighbour_control():
    """КОНТРОЛЬ (зелёный и до реализации). ``handled(next) - own(next) == Σ born(prev) * N``, N = 1 цель."""
    rcv_p, ex_p, _sent_p, rcv_i, ex_i = _run_line()

    born_processor = _born(rcv_p, ex_p)
    own_inspector = _born(rcv_i, ex_i)
    handled_inspector = ex_i.get_cycle_metrics()["not_inspected_handled"]

    assert born_processor > 0, "риг пуст: processor не родил ни одного маркера"
    assert handled_inspector - own_inspector == born_processor


def test_adr174_rig_literal_born_is_298_of_300_frames_control():
    """КОНТРОЛЬ (зелёный и до реализации): литерал рига. Потолок 2 из 300 кадров -> 298 маркеров ``lag``
    (кадры f0..f297), 2 кадра доехали. Без него остальные тесты рига могли бы пройти на пустом разрыве."""
    rcv_p, ex_p, sent_p, _rcv_i, _ex_i = _run_line()

    assert _born(rcv_p, ex_p) == 298
    frames = [m["data"]["trace_id"] for _t, m in sent_p if not is_marker(m["data"])]
    assert frames == ["f298", "f299"]


def test_adr174_rig_gap_leaves_processor_as_one_record_with_all_trace_ids():
    """Разрыв из 298 кадров уезжает ОДНОЙ записью (а не 298 сообщениями): ``count`` 298, ``trace_ids`` f0..f297."""
    _rcv_p, _ex_p, sent_p, _rcv_i, _ex_i = _run_line()

    gap_msgs = [m["data"] for _t, m in sent_p if is_marker(m["data"])]

    assert len(gap_msgs) == 1, f"разрыв уехал {len(gap_msgs)} сообщениями"
    assert gap_msgs[0]["count"] == 298
    assert gap_msgs[0]["trace_ids"] == [f"f{i}" for i in range(298)]
    assert gap_msgs[0]["reasons"] == {"lag": 298}
    assert gap_msgs[0]["sources"] == {"processor": 298}
