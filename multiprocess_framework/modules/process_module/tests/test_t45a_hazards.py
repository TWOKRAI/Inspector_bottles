"""Task 4.5a — hazard-тесты автора: метка очереди и пути put в DataReceiver."""

from __future__ import annotations

import queue
import threading

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver


def _receiver(chain_queue: queue.Queue, **kw) -> DataReceiver:
    return DataReceiver(
        receive_fn=lambda: None,
        shm_middleware=None,
        item_collector=None,
        chain_queue=chain_queue,
        **kw,
    )


def test_backpressure_put_still_delivers_stamped_batch() -> None:
    """Путь блокирующего put после queue.Full тоже кладёт помеченную коллекцию."""
    q: queue.Queue = queue.Queue(maxsize=1)
    q.put(["old"])
    dr = _receiver(q, lag_alert_threshold_sec=0.05)
    dr._stop_event = threading.Event()
    t = threading.Thread(target=dr.on_items_ready, args=([{"frame_id": 1}],), daemon=True)
    t.start()
    t.join(timeout=0.3)  # ждёт места: первый put уже упал по таймауту
    assert q.get_nowait() == ["old"]
    t.join(timeout=2.0)
    assert not t.is_alive()
    got = q.get(timeout=1.0)
    assert got == [{"frame_id": 1}]
    assert isinstance(got.enq_ts, float) and got.enq_ts > 0


def test_bound_lag_drop_path_works_with_stamped_batch() -> None:
    """Потолок отставания: старые выбрасываются, свежая помеченная коллекция лежит в очереди."""
    q: queue.Queue = queue.Queue()
    dr = _receiver(q, max_lag_items=2)
    for i in range(5):
        dr.on_items_ready([{"frame_id": i}])
    assert q.qsize() == 2
    assert dr.lag_dropped_total == 3
    ids = [q.get_nowait()[0]["frame_id"] for _ in range(2)]
    assert ids == [3, 4]
