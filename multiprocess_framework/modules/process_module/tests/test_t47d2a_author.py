# -*- coding: utf-8 -*-
"""Task 4.7d-2a — авторские hazard-тесты приёмника (механизм ``_bound_lag`` под ``overflow="every"``).

Что может сломаться именно в ЭТОМ механизме (замена на месте + склейка под ``chain.mutex``):
  * гонка с потребителем: ``get()`` идёт параллельно с заменой/склейкой -> кадр потерян или задвоен;
  * склейка освобождает место, но без ``not_full.notify`` блокированный в ``put`` производитель спит
    при свободной очереди (``put`` сам никого не будит — будит только ``get`` и этот notify);
  * ветка ``latest`` обязана остаться прежней (удаление без маркеров, прежний набор ключей).

Всё, что может заблокироваться, гоняется в daemon-потоке с дедлайном на ``join``.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import Counter

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver, _MarkerBatch
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker, is_marker

DEADLINE_S = 10.0


class _NoCollector:
    def on_item(self, item: dict) -> None:  # pragma: no cover - в этих тестах не вызывается
        raise AssertionError("коллектор не должен вызываться")

    def check_timeouts(self) -> None:
        return None


def _receiver(chain: queue.Queue, *, lag: int, overflow: str) -> DataReceiver:
    return DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=None,
        item_collector=_NoCollector(),
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        node_name="author_node",
        max_lag_items=lag,
        overflow=overflow,
    )


def _frame(trace_id: str) -> list[dict]:
    return [{"frame": np.zeros((1, 1), dtype=np.uint8), "trace_id": trace_id}]


def test_every_bound_concurrent_consumer_loses_and_duplicates_nothing():
    """200 кадров t0..t199 при параллельном ``get()``: каждый trace_id встречается РОВНО один раз —
    кадром либо маркером (замена и склейка идут под mutex, потребитель видит коллекцию целиком)."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=4, overflow="every")
    seen: list[str] = []
    producer_done = threading.Event()

    def consume() -> None:
        while True:
            try:
                coll = chain.get(timeout=0.05)
            except queue.Empty:
                if producer_done.is_set():
                    return
                continue
            seen.extend(it["trace_id"] for it in coll)
            time.sleep(0.0005)  # медленный потребитель: очередь копится, bound срабатывает

    def produce() -> None:
        for i in range(200):
            receiver.on_items_ready(_frame(f"t{i}"))
        producer_done.set()

    consumer = threading.Thread(target=consume, daemon=True)
    producer = threading.Thread(target=produce, daemon=True)
    consumer.start()
    producer.start()
    producer.join(DEADLINE_S)
    consumer.join(DEADLINE_S)
    assert not producer.is_alive() and not consumer.is_alive(), "завис производитель или потребитель"

    assert Counter(seen) == Counter(f"t{i}" for i in range(200))
    # учёт счётчиков согласован с тем, что реально ушло маркерами
    assert receiver.get_cycle_metrics()["not_inspected_lag"] == receiver.get_cycle_metrics()["lag_dropped_items"]


def test_producer_blocked_in_put_is_released_when_coalescing_frees_slots():
    """Очередь на 5 забита [Ma, Mb, Mc, c1, c2]; сторонний производитель блокирован в ``put``. Приходит c3
    (lag 2): c1 -> маркер, склейка Ma+Mb+Mc+M1 освобождает 3 слота и ОБЯЗАНА разбудить его (put сам не будит)."""
    chain: queue.Queue = queue.Queue(maxsize=5)
    for tid in ("a", "b", "c"):
        chain.put(_MarkerBatch([build_marker({"trace_id": tid}, reason="lag", source="up")]))  # как в проде: тип
    chain.put(_frame("c1"))
    chain.put(_frame("c2"))
    assert chain.full()
    receiver = _receiver(chain, lag=2, overflow="every")

    blocker_done = threading.Event()

    def blocked_put() -> None:
        chain.put([{"tag": "blocker"}])
        blocker_done.set()

    blocker = threading.Thread(target=blocked_put, daemon=True)
    blocker.start()
    assert not blocker_done.wait(0.3), "производитель не заблокировался — сценарий не воспроизведён"

    worker = threading.Thread(target=receiver.on_items_ready, args=(_frame("c3"),), daemon=True)
    worker.start()
    worker.join(DEADLINE_S)
    assert not worker.is_alive()

    assert blocker_done.wait(DEADLINE_S), "склейка освободила место, но блокированный put не разбужен"
    with chain.mutex:
        shape = [[it.get("trace_id") or it.get("tag") for it in c] for c in chain.queue]
    assert shape[0] == ["a", "b", "c", "c1"]  # одна склеенная коллекция маркеров
    assert sorted(t for c in shape[1:] for t in c) == ["blocker", "c2", "c3"]


def test_latest_path_unchanged_on_t1_to_t6():
    """latest, lag 2: те же шесть кадров -> [t5, t6] исходными объектами, ни одного маркера, из метрик нет
    маркерных ключей; ``lag_dropped_total`` по-прежнему в коллекциях."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, lag=2, overflow="latest")
    colls = [_frame(f"t{i}") for i in range(1, 7)]
    for coll in colls:
        receiver.on_items_ready(coll)

    with chain.mutex:
        queued = list(chain.queue)
    assert [c[0] for c in queued] == [colls[4][0], colls[5][0]]  # те же item-объекты, без пересборки
    assert not any(is_marker(it) for c in queued for it in c)
    metrics = receiver.get_cycle_metrics()
    assert metrics["lag_dropped_items"] == 4
    assert receiver.lag_dropped_total == 4
    assert not {"not_inspected_lag", "not_inspected_stale_restore"} & set(metrics)


# --------------------------------------------------------------------------------------------
# Ревью 2a (minor): маркер-коллекция опознаётся ТИПОМ, а не обходом items под chain.mutex
# --------------------------------------------------------------------------------------------
class _CountingMarkerBatch(_MarkerBatch):
    """``_MarkerBatch``, считающий обходы своих items. Обход головы из маркеров под mutex — ровно то, что
    замена ``all(is_marker ...)`` на ``isinstance`` обязана убрать (20k маркеров -> 4.5 мс на кадр)."""

    __slots__ = ("iter_calls",)

    def __iter__(self):
        self.iter_calls = getattr(self, "iter_calls", 0) + 1
        return list.__iter__(self)


def test_bound_lag_every_does_not_walk_items_of_a_long_marker_head():
    """Голова очереди — 1000 маркеров (``_MarkerBatch``), за ней c1, c2; приходит c3 (lag 2). Потолок срабатывает
    (c1 -> маркер, склейка с головой), но ни ``_is_frame_collection``, ни проверка склейки голову НЕ обходят:
    ``__iter__`` головы вызван 0 раз; сама голова остаётся первой и вобрала маркер c1 (1001 item)."""
    chain: queue.Queue = queue.Queue(maxsize=8)
    head = _CountingMarkerBatch(build_marker({"trace_id": f"h{i}"}, reason="lag", source="up") for i in range(1000))
    head.iter_calls = 0
    head.enq_ts = 0.0
    chain.put(head)
    chain.put(_frame("c1"))
    chain.put(_frame("c2"))
    receiver = _receiver(chain, lag=2, overflow="every")

    worker = threading.Thread(target=receiver.on_items_ready, args=(_frame("c3"),), daemon=True)
    worker.start()
    worker.join(DEADLINE_S)
    assert not worker.is_alive()

    assert head.iter_calls == 0, f"голова из маркеров обойдена {head.iter_calls} раз под mutex"
    with chain.mutex:
        queued = list(chain.queue)
    assert queued[0] is head and len(head) == 1001
    assert [c[0]["trace_id"] for c in queued[1:]] == ["c2", "c3"]
    assert receiver.get_cycle_metrics()["not_inspected_lag"] == 1


def test_marker_batch_type_survives_replacement_and_coalescing():
    """[c1, c2] lag 2 + c3 -> c1 заменён маркером; + c4 -> c2 заменён и СКЛЕЕН в первую: в очереди первая коллекция
    ровно типа ``_MarkerBatch`` (не list/_StampedBatch) с trace_id [c1, c2] — иначе следующая склейка её
    не узнает и маркер-коллекции начнут копиться до ``queue_size``."""
    chain: queue.Queue = queue.Queue(maxsize=8)
    chain.put(_frame("c1"))
    chain.put(_frame("c2"))
    receiver = _receiver(chain, lag=2, overflow="every")

    receiver.on_items_ready(_frame("c3"))
    with chain.mutex:
        first = chain.queue[0]
    assert type(first) is _MarkerBatch and [m["trace_id"] for m in first] == ["c1"]

    receiver.on_items_ready(_frame("c4"))
    with chain.mutex:
        shape = list(chain.queue)
    assert type(shape[0]) is _MarkerBatch
    assert [m["trace_id"] for m in shape[0]] == ["c1", "c2"]
    assert [c[0]["trace_id"] for c in shape[1:]] == ["c3", "c4"]


class _DroppingShm:
    """restore_frame, который ВСЕГДА отказывает (метка ``_shm_dropped`` на data, как у настоящего)."""

    def restore_frame(self, msg: dict) -> dict:
        msg["data"]["_shm_dropped"] = True
        return msg


@pytest.mark.parametrize("kind", ["ipc_marker", "stale_restore"])
def test_marker_enqueued_by_run_loop_is_a_marker_batch(kind):
    """IPC-маркер (любой режим) и маркер stale_restore (every) кладутся в chain_queue как ``_MarkerBatch``
    — иначе потолок не склеит их с соседними маркерами и обойдёт под mutex."""
    if kind == "ipc_marker":
        marker = build_marker({"trace_id": "t7", "capture_ts": 1.0}, reason="lag", source="up")
        msg, shm = {"data": dict(marker), "sender": "up"}, None
    else:
        msg, shm = {"data": {"trace_id": "t9", "capture_ts": 3.5}}, _DroppingShm()
    chain: queue.Queue = queue.Queue(maxsize=8)
    pending, drained = [msg], threading.Event()

    def receive_fn(**_kw):
        if pending:
            return pending.pop(0)
        drained.set()
        return None

    receiver = DataReceiver(
        receive_fn=receive_fn,
        shm_middleware=shm,
        item_collector=_NoCollector(),
        chain_queue=chain,
        node_name="author_node",
        overflow="every",
    )
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=receiver.run_loop, args=(stop, pause), daemon=True)
    worker.start()
    ok = drained.wait(DEADLINE_S)
    stop.set()
    worker.join(DEADLINE_S)
    assert ok and not worker.is_alive(), "приёмник не дочитал сообщение или не остановился"

    assert chain.qsize() == 1
    coll = chain.get_nowait()
    assert type(coll) is _MarkerBatch
    assert len(coll) == 1 and is_marker(coll[0])
