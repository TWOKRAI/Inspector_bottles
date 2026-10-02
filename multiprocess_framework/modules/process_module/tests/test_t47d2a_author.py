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

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
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
        chain.put([build_marker({"trace_id": tid}, reason="lag", source="up")])
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
