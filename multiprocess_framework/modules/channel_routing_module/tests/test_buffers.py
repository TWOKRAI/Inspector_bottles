# -*- coding: utf-8 -*-
"""
Тесты буферных стратегий: DirectBuffer, AsyncSenderBuffer.

(BatchBuffer снят в Ф7.4 вместе с батчингом записи — замер показал ноль
экономии на границе ОС и худший хвост p99 в потоке-эмитенте.)

Проверяет: enqueue, flush, stats, thread-safety, priority ordering.
"""

import time
import pytest

from ..buffers.direct_buffer import DirectBuffer
from ..buffers.async_sender_buffer import AsyncSenderBuffer


# ---------------------------------------------------------------------------
# DirectBuffer
# ---------------------------------------------------------------------------


class TestDirectBuffer:
    def test_enqueue_calls_send_fn(self):
        calls = []
        buf = DirectBuffer(send_fn=lambda ch, data: calls.append((ch, data)))
        buf.start()
        buf.enqueue("ch1", {"x": 1})
        buf.enqueue("ch2", {"x": 2})
        assert calls == [("ch1", {"x": 1}), ("ch2", {"x": 2})]

    def test_flush_is_noop(self):
        buf = DirectBuffer(send_fn=lambda ch, data: None)
        buf.flush()  # должно не падать
        buf.flush("ch1")

    def test_stats(self):
        calls = []
        buf = DirectBuffer(send_fn=lambda ch, data: calls.append(ch))
        buf.enqueue("ch", {"msg": "hello"})
        buf.enqueue("ch", {"msg": "world"})
        s = buf.stats
        assert s["enqueued"] == 2
        assert s["errors"] == 0
        assert s["type"] == "direct"

    def test_stats_error_on_exception(self):
        def _fail(ch, data):
            raise RuntimeError("fail")

        buf = DirectBuffer(send_fn=_fail)
        with pytest.raises(RuntimeError):
            buf.enqueue("ch", {})
        assert buf.stats["errors"] == 1

    def test_priority_ignored(self):
        order = []
        buf = DirectBuffer(send_fn=lambda ch, data: order.append(data["n"]))
        buf.enqueue("ch", {"n": 1}, priority="low")
        buf.enqueue("ch", {"n": 2}, priority="urgent")
        assert order == [1, 2]  # arrived-order preserved


# ---------------------------------------------------------------------------
# AsyncSenderBuffer
# ---------------------------------------------------------------------------


class TestAsyncSenderBuffer:
    def test_enqueue_and_receive(self):
        received = []

        def _send(ch, data):
            received.append((ch, data))

        buf = AsyncSenderBuffer(send_fn=_send)
        buf.start()
        buf.enqueue("ch1", {"v": 1})
        buf.enqueue("ch1", {"v": 2})
        time.sleep(0.3)
        buf.stop()

        assert len(received) == 2
        assert all(ch == "ch1" for ch, _ in received)

    def test_priority_ordering(self):
        received = []

        def _send(ch, data):
            received.append(data["p"])

        buf = AsyncSenderBuffer(send_fn=_send, queue_size=100)
        # Fill queue while worker is stopped to preserve ordering
        buf._stop_event.set()
        buf.enqueue("ch", {"p": "low"}, priority="low")
        buf.enqueue("ch", {"p": "normal"}, priority="normal")
        buf.enqueue("ch", {"p": "urgent"}, priority="urgent")
        buf.enqueue("ch", {"p": "high"}, priority="high")
        buf._stop_event.clear()
        buf.start()
        time.sleep(0.3)
        buf.stop()

        # urgent should come before normal/low
        assert received.index("urgent") < received.index("low")
        assert received.index("high") < received.index("low")

    def test_drop_on_full_queue(self):
        warnings = []
        buf = AsyncSenderBuffer(
            send_fn=lambda ch, data: time.sleep(0.5),  # very slow consumer
            queue_size=1,
            log_warning=warnings.append,
        )
        buf.start()
        buf.enqueue("ch", {"n": 1})  # worker picks this up immediately
        time.sleep(0.05)  # wait for worker to dequeue item 1 (now sleeping)
        buf.enqueue("ch", {"n": 2})  # fills queue (size=1)
        buf.enqueue("ch", {"n": 3})  # should drop — queue is full
        buf.stop()

        assert buf.stats["dropped"] >= 1
        assert warnings

    def test_stats(self):
        buf = AsyncSenderBuffer(send_fn=lambda ch, data: None)
        buf.start()
        buf.enqueue("ch", {"x": 1})
        time.sleep(0.2)
        buf.stop()
        s = buf.stats
        assert s["enqueued"] == 1
        assert s["type"] == "async_sender"

    def test_is_alive(self):
        buf = AsyncSenderBuffer(send_fn=lambda ch, data: None)
        assert not buf.is_alive
        buf.start()
        assert buf.is_alive
        buf.stop()
        assert not buf.is_alive

    def test_start_idempotent(self):
        buf = AsyncSenderBuffer(send_fn=lambda ch, data: None)
        buf.start()
        thread1 = buf._thread
        buf.start()  # second call should not create new thread
        assert buf._thread is thread1
        buf.stop()
