# -*- coding: utf-8 -*-
"""Task 5.3 — слепые приёмочные тесты ``PipelineExecutor`` и двери: запись о разрыве вместо N маркеров.

Независимый tester, от acceptance Task 5.3 (plans/transport-single-policy/phase-5.md, «### Task 5.3»),
без чтения реализации 5.3 (её в дереве нет). Ожидаемые значения — литералы.

Что пинится:
  * ``_forward_markers`` схлопывает коллекцию маркеров в записи ДО цепочки: ``_MarkerBatch`` из 1078 маркеров
    и 2 ``chain_targets`` -> ``send_fn`` ровно 2 раза, в обоих ``data["count"] == 1078``, ``trace_ids`` в порядке
    входа; ``not_inspected_handled`` растёт на Σ ``count`` ВХОДА (не на число записей);
  * чанк: 1600 маркеров -> 2 записи (1500 + 100), по записи на цель;
  * вход-запись суммируется, плагин ``accepts_markers`` видит схлопнутую запись ровно 1 раз, плагин без
    ``accepts_markers`` не вызывается;
  * дверь отправителя под ``every``, fan-out на 2 цели: одна запись ``count=1`` на обе цели,
    ``not_inspected_door == 1``, ``door_drops == 1``.

Зелёные контроли (держат стенд честным, зелёные и до реализации): счётчики двери при fan-out; ``handled`` на
1078 маркерах (сегодня ``len(items)`` даёт то же число).
Остальное — красное до реализации: ``AssertionError`` (сегодня уходит по сообщению на маркер, ``handled`` считает
items, в двери нет ``count``).

Всё, что может заблокироваться (``run``, дверь), гоняется в daemon-потоке с дедлайном на ``join``.
"""

from __future__ import annotations

import gc
import os
import queue
import threading
from typing import Callable

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import _MarkerBatch
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

DEADLINE_S = 15.0
SERVICE_KEYS = {"_t_sent_ns", "_t_send", "_from"}  # штамп transport_ms и frame-trace: не часть записи
BASE_TS = 1000.0


# --------------------------------------------------------------------------------------------
# стенд исполнителя
# --------------------------------------------------------------------------------------------
class _Plugin:
    """Плагин-шпион: считает вызовы process(), запоминает копию входного списка."""

    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self, name: str, *, accepts: bool | None = None) -> None:
        self.name = name
        if accepts is not None:
            self.accepts_markers = accepts
        self.calls = 0
        self.seen: list[list[dict]] = []

    def process(self, items: list[dict]) -> list[dict]:
        self.calls += 1
        self.seen.append(list(items))
        return items


def _executor(plugins, *, overflow="latest", targets=("t1", "t2"), sent=None) -> PipelineExecutor:
    sent = sent if sent is not None else []
    return PipelineExecutor(
        plugins=list(plugins),
        chain_targets=list(targets),
        shm_middleware=None,
        send_fn=lambda target, msg: sent.append((target, msg)),
        node_name="exec_node",
        overflow=overflow,
    )


def _drive(ex: PipelineExecutor, batches: list[list[dict]]) -> None:
    """Прогнать батчи через настоящий ``ex.run`` (daemon-поток, дедлайн) и остановить воркер по пустой очереди."""
    q: queue.Queue = queue.Queue()
    for b in batches:
        q.put(b)
    ex.bind_queue(q)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
    worker.start()
    waiter = threading.Event()
    for _ in range(int(DEADLINE_S / 0.01)):
        if q.empty():
            break
        waiter.wait(0.01)
    else:
        stop.set()
        pytest.fail("исполнитель не выбрал очередь за дедлайн")
    stop.set()
    worker.join(DEADLINE_S)
    if worker.is_alive():
        pytest.fail("PipelineExecutor не завершил такт за дедлайн")


def _bare(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in SERVICE_KEYS}


def _handled(ex: PipelineExecutor) -> int:
    return ex.get_cycle_metrics()["not_inspected_handled"]


def _m(i: int, *, reason: str = "lag") -> dict:
    return build_marker(
        {"trace_id": f"t{i}", "capture_ts": BASE_TS + i, "camera_id": "cam0"}, reason=reason, source="upstream"
    )


def _batch(n: int, *, reason: str = "lag") -> _MarkerBatch:
    batch = _MarkerBatch(_m(i, reason=reason) for i in range(n))
    batch.enq_ts = 0.0
    return batch


def _record(ids: list[str], *, reason: str = "lag", first: float, last: float) -> dict:
    """Запись о разрыве, собранная ЛИТЕРАЛОМ (не через ``build_gap``): вход «пришла от соседа»."""
    return {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "count": len(ids),
        "trace_ids": list(ids),
        "first_capture_ts": first,
        "last_capture_ts": last,
        "reasons": {reason: len(ids)},
        "sources": {"upstream": len(ids)},
        "source": "upstream",
        "camera_id": "cam0",
    }


# --------------------------------------------------------------------------------------------
# _forward_markers: схлопывание ДО цепочки
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_marker_batch_1078_two_targets_sends_exactly_two_records(overflow):
    sent: list = []
    ex = _executor([], overflow=overflow, sent=sent)

    _drive(ex, [_batch(1078)])

    assert [t for t, _m_ in sent] == ["t1", "t2"]


@pytest.mark.parametrize("overflow", ["latest", "every"])
def test_marker_batch_1078_record_literal_in_both_targets(overflow):
    sent: list = []
    ex = _executor([], overflow=overflow, sent=sent)

    _drive(ex, [_batch(1078)])

    expected = {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "count": 1078,
        "trace_ids": [f"t{i}" for i in range(1078)],
        "first_capture_ts": BASE_TS,
        "last_capture_ts": BASE_TS + 1077,
        "reasons": {"lag": 1078},
        "sources": {"upstream": 1078},
        "source": "upstream",
        "camera_id": "cam0",
    }
    assert len(sent) == 2
    for _target, msg in sent:
        assert _bare(msg["data"]) == expected


def test_marker_batch_1078_handled_grows_by_sum_of_input_counts_control():
    """КОНТРОЛЬ (зелёный и до реализации: сегодня ``len(items)`` == 1078): держит ``handled`` на Σ count входа,
    когда ``send_fn`` получает одну запись. Красным станет у реализации, что считает записи, а не входы."""
    ex = _executor([])
    before = _handled(ex)

    _drive(ex, [_batch(1078)])

    assert _handled(ex) - before == 1078


def test_marker_batch_chunks_1600_markers_into_1500_and_100_per_target():
    sent: list = []
    ex = _executor([], sent=sent)
    before = _handled(ex)

    _drive(ex, [_batch(1600)])

    assert [t for t, _m_ in sent] == ["t1", "t2", "t1", "t2"]
    assert [msg["data"]["count"] for _t, msg in sent] == [1500, 1500, 100, 100]
    assert [len(msg["data"]["trace_ids"]) for _t, msg in sent] == [1500, 1500, 100, 100]
    assert sent[2][1]["data"]["trace_ids"][0] == "t1500"
    assert _handled(ex) - before == 1600, "handled должен считать входные маркеры, а не записи"


# --------------------------------------------------------------------------------------------
# вход — запись
# --------------------------------------------------------------------------------------------
def test_record_input_is_forwarded_as_one_record_and_handled_counts_its_count():
    sent: list = []
    ex = _executor([], sent=sent, targets=("t1",))
    before = _handled(ex)
    record = _record([f"r{i}" for i in range(7)], first=3.0, last=9.0)
    batch = _MarkerBatch([dict(record)])
    batch.enq_ts = 0.0

    _drive(ex, [batch])

    assert len(sent) == 1
    assert _bare(sent[0][1]["data"]) == record
    assert _handled(ex) - before == 7


def test_records_and_markers_in_one_batch_collapse_into_one_record_in_input_order():
    sent: list = []
    ex = _executor([], sent=sent, targets=("t1",))
    before = _handled(ex)
    rec_a = _record(["a1", "a2", "a3"], first=5.0, last=7.0)
    rec_b = _record(["b1", "b2"], reason="stale_exec", first=1.0, last=2.0)
    marker = _m(9, reason="door")
    batch = _MarkerBatch([dict(rec_a), marker, dict(rec_b)])
    batch.enq_ts = 0.0

    _drive(ex, [batch])

    assert len(sent) == 1
    data = sent[0][1]["data"]
    assert data["count"] == 6
    assert data["trace_ids"] == ["a1", "a2", "a3", "t9", "b1", "b2"]
    assert data["reasons"] == {"lag": 3, "door": 1, "stale_exec": 2}
    assert (data["first_capture_ts"], data["last_capture_ts"]) == (1.0, BASE_TS + 9)
    assert _handled(ex) - before == 6


# --------------------------------------------------------------------------------------------
# плагины: схлопывание ДО цепочки
# --------------------------------------------------------------------------------------------
def test_plugin_with_accepts_markers_sees_one_collapsed_record_in_one_call():
    spy = _Plugin("keeper", accepts=True)
    ex = _executor([spy], targets=("t1",))

    _drive(ex, [_batch(5)])

    assert spy.calls == 1
    assert len(spy.seen[0]) == 1, "цепочка должна получить одну запись, а не 5 маркеров"
    assert spy.seen[0][0]["count"] == 5
    assert spy.seen[0][0]["trace_ids"] == ["t0", "t1", "t2", "t3", "t4"]


def test_plain_plugin_is_not_called_and_one_record_goes_to_each_target():
    plain = _Plugin("plain")
    sent: list = []
    ex = _executor([plain], sent=sent)

    _drive(ex, [_batch(5)])

    assert plain.calls == 0
    assert [t for t, _m_ in sent] == ["t1", "t2"]
    assert [msg["data"]["count"] for _t, msg in sent] == [5, 5]


# --------------------------------------------------------------------------------------------
# дверь отправителя (every, fan-out 2)
# --------------------------------------------------------------------------------------------
SHAPES = {"frame": (48, 64, 3)}  # >= 8192 Б -> уходит в кольцо ссылкой
META = {"trace_id": "tr-1", "capture_ts": 12.5, "frame_id": 7, "camera_id": "cam0"}
DOOR_RECORD = {
    "inspection_status": "not_inspected",
    "overflow_marker": True,
    "reason": "door",
    "source": "B",
    "trace_id": "tr-1",
    "capture_ts": 12.5,
    "frame_id": 7,
    "camera_id": "cam0",
    "count": 1,
    "trace_ids": ["tr-1"],
    "first_capture_ts": 12.5,
    "last_capture_ts": 12.5,
    "reasons": {"door": 1},
    "sources": {"B": 1},
}


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def made():
    items: list[tuple[FrameShmMiddleware, MemoryManager]] = []
    yield items
    gc.collect()
    for mw, mm in reversed(items):
        for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001
                pass


def _mw(made, owner: str, **kw) -> FrameShmMiddleware:
    mm = MemoryManager()
    kw.setdefault("coll", 3)
    mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", **kw)
    made.append((mw, mm))
    return mw


def _arr(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=SHAPES["frame"]).astype(np.uint8)


def _bounded(fn: Callable[[], object], deadline: float = 30.0):
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _door_fanout(made):
    """Писатель A -> отправитель B (every) с view на слот A; слот A перезаписан; выход смотрит в чужой слот ->
    дверь дропает. Два сообщения на разные цели делят ОДИН data-dict (как ``_send_results``)."""
    writer, sender = _mw(made, "A"), _mw(made, "B", overflow="every")
    out = _bounded(
        lambda: writer.strip_data_frame_on_send(
            {"target": "t", "type": "data", "channel": "data", "data": {"frame": _arr(1), "n": 1, **META}}
        )
    )
    msg = sender.restore_frame(out)
    received = dict(msg["data"])
    received["frame"] = msg["frame"]
    assert received["_shm_views"] and not received["frame"].flags.owndata, "стенд неисправен: нет view-билетов"
    assert received["trace_id"] == "tr-1" and received["frame_id"] == 7, "стенд неисправен: мета не доехала"
    crop = received["frame"][:8, :8]
    item = {"n": received["n"], "_shm_views": received["_shm_views"], **{k: received[k] for k in META}, "crop": crop}
    for s in range(3):  # coll=3: кольцо A обернулось -> ячейка первой записи перезаписана
        _bounded(
            lambda s=s: writer.strip_data_frame_on_send(
                {"target": "t", "type": "data", "channel": "data", "data": {"frame": _arr(100 + s)}}
            )
        )
    msg1 = {"target": "t1", "type": "data", "channel": "data", "data": item}
    msg2 = {"target": "t2", "type": "data", "channel": "data", "data": item}
    out1 = _bounded(lambda: sender.strip_data_frame_on_send(msg1))
    out2 = _bounded(lambda: sender.strip_data_frame_on_send(msg2))
    return sender, out1, out2


def test_door_every_fanout_delivers_one_count1_record_to_both_targets(made):
    sender, out1, out2 = _door_fanout(made)

    assert out1 is not None and out2 is not None, "одна из целей fan-out осталась без записи"
    assert (out1["target"], out2["target"]) == ("t1", "t2")
    assert out1["data"] == DOOR_RECORD
    assert out2["data"] == DOOR_RECORD


def test_door_every_fanout_birth_counted_once_control(made):
    """КОНТРОЛЬ (зелёный и до реализации): одно рождение, две доставки — счётчики не удваиваются."""
    sender, _out1, _out2 = _door_fanout(made)

    assert sender.not_inspected_door == 1
    assert sender.door_drops == 1
