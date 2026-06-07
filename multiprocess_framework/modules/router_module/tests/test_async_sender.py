# -*- coding: utf-8 -*-
"""Тесты AsyncSender — poison-pill sentinel, структурный выход, приоритеты.

Покрытие:
(a) stop с пустой очередью → worker выходит быстро по sentinel
(b) stop с непустой очередью → sentinel заберётся, worker выходит
(c) enqueue после stop → no-op (сообщение не попадает в очередь)
(d) sentinel не ломает PriorityQueue при смешанных приоритетах
(e) обычная доставка и приоритеты сохраняются
(f) worker продолжает после ошибки send_fn
"""

from __future__ import annotations

import threading
import time

from ..core._sender import AsyncSender


class TestSentinelStopEmpty:
    """(a) stop с пустой очередью → worker выходит быстро по sentinel."""

    def test_stop_empty_queue_fast_exit(self) -> None:
        """Worker завершается менее чем за 0.5с при пустой очереди."""
        sender = AsyncSender("test", send_fn=lambda msg: None)
        sender.start()
        assert sender.is_alive

        t0 = time.perf_counter()
        sender.stop(timeout=2.0)
        elapsed = time.perf_counter() - t0

        assert not sender.is_alive
        assert elapsed < 0.5, f"Выход занял {elapsed:.3f}с — слишком долго для sentinel"


class TestSentinelStopNonEmpty:
    """(b) stop с непустой очередью → все сообщения обрабатываются, worker выходит."""

    def test_stop_nonempty_queue(self) -> None:
        """Сообщения, стоящие до sentinel, доставляются; worker выходит."""
        delivered: list[dict] = []
        lock = threading.Lock()

        def send_fn(msg: dict) -> None:
            with lock:
                delivered.append(msg)

        sender = AsyncSender("test", send_fn=send_fn)
        sender.start()

        # Положить несколько сообщений
        for i in range(5):
            sender.enqueue({"idx": i})

        # Дать worker'у начать обработку
        time.sleep(0.05)
        sender.stop(timeout=2.0)

        assert not sender.is_alive
        # Все 5 сообщений должны быть доставлены
        with lock:
            assert len(delivered) == 5


class TestEnqueueAfterStop:
    """(c) enqueue после stop → no-op."""

    def test_enqueue_after_stop_noop(self) -> None:
        """Сообщение, положенное после stop, не попадает в очередь."""
        delivered: list[dict] = []
        sender = AsyncSender("test", send_fn=lambda msg: delivered.append(msg))
        sender.start()
        sender.stop(timeout=2.0)

        # enqueue после stop — no-op
        sender.enqueue({"should_not_arrive": True})
        assert sender.queued == 0, "enqueue после stop не должен инкрементить queued"

    def test_enqueue_before_start_after_stop(self) -> None:
        """stop_event уже set → enqueue тихо игнорирует."""
        sender = AsyncSender("test", send_fn=lambda msg: None)
        # Не стартуем, но ставим stop_event напрямую
        sender._stop_event.set()
        sender.enqueue({"ignored": True})
        assert sender.queued == 0


class TestSentinelPriorityOrdering:
    """(d) sentinel не ломает PriorityQueue при смешанных приоритетах."""

    def test_mixed_priorities_with_sentinel(self) -> None:
        """Sentinel с приоритетом -1 корректно забирается из heap рядом с обычными."""
        delivered: list[dict] = []

        def send_fn(msg: dict) -> None:
            delivered.append(msg)

        sender = AsyncSender("test", send_fn=send_fn, queue_size=64)
        sender.start()

        # Кладём сообщения разных приоритетов
        sender.enqueue({"p": "low"}, priority="low")
        sender.enqueue({"p": "urgent"}, priority="urgent")
        sender.enqueue({"p": "high"}, priority="high")
        sender.enqueue({"p": "normal"}, priority="normal")

        # Даём worker забрать всё
        time.sleep(0.1)
        sender.stop(timeout=2.0)

        assert not sender.is_alive
        assert len(delivered) == 4

        # Проверяем порядок: urgent (0) → high (1) → normal (2) → low (3)
        priorities = [d["p"] for d in delivered]
        assert priorities == ["urgent", "high", "normal", "low"]


class TestNormalDelivery:
    """(e) обычная доставка работает корректно."""

    def test_basic_send(self) -> None:
        """Сообщение enqueue → send_fn вызван."""
        delivered: list[dict] = []
        sender = AsyncSender("test", send_fn=lambda msg: delivered.append(msg))
        sender.start()

        sender.enqueue({"hello": "world"})
        time.sleep(0.1)
        sender.stop(timeout=2.0)

        assert len(delivered) == 1
        assert delivered[0] == {"hello": "world"}

    def test_dropped_on_full_queue(self) -> None:
        """Переполнение очереди → dropped увеличивается."""
        log_warnings: list[str] = []
        # Блокирующий send_fn: worker застревает на первом сообщении,
        # оставшиеся 2 слота остаются занятыми → третий put_nowait → Full.
        block = threading.Event()
        entered = threading.Event()

        def slow_send(msg: dict) -> None:
            entered.set()
            block.wait()

        sender = AsyncSender(
            "test",
            send_fn=slow_send,
            queue_size=3,
            log_warning=lambda msg: log_warnings.append(msg),
        )
        sender.start()

        # Первое сообщение — worker заберёт из очереди и застрянет в send_fn
        sender.enqueue({"a": 1})
        entered.wait(timeout=2.0)  # Дождаться, пока worker застрял в send_fn
        # Теперь worker блокирован, очередь пуста (1 уже забрана).
        # Заполняем оставшиеся 3 слота (queue_size=3)
        sender.enqueue({"b": 2})
        sender.enqueue({"c": 3})
        sender.enqueue({"d": 4})
        # Четвёртое в очередь (всего 4-й enqueue, очередь полна) → drop
        sender.enqueue({"e": 5})

        assert sender.dropped >= 1
        assert len(log_warnings) >= 1

        block.set()
        sender.stop(timeout=2.0)

    def test_queued_counter(self) -> None:
        """queued инкрементируется при каждом успешном enqueue."""
        sender = AsyncSender("test", send_fn=lambda msg: None, queue_size=64)
        sender.start()

        for _ in range(10):
            sender.enqueue({"x": 1})

        assert sender.queued == 10
        sender.stop(timeout=2.0)


class TestWorkerErrorRecovery:
    """(f) worker продолжает после ошибки send_fn."""

    def test_error_in_send_fn_continues(self) -> None:
        """Ошибка в send_fn логируется, worker не падает."""
        delivered: list[dict] = []
        errors: list[str] = []
        call_count = {"n": 0}

        def failing_then_ok(msg: dict) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("injected failure")
            delivered.append(msg)

        sender = AsyncSender(
            "test",
            send_fn=failing_then_ok,
            log_error=lambda msg: errors.append(msg),
        )
        sender.start()

        sender.enqueue({"first": True})  # → ошибка
        sender.enqueue({"second": True})  # → успех
        time.sleep(0.2)
        sender.stop(timeout=2.0)

        assert len(errors) == 1
        assert "injected failure" in errors[0]
        assert len(delivered) == 1
        assert delivered[0] == {"second": True}


class TestSentinelTupleComparison:
    """Гарантия: heap НИКОГДА не сравнивает payload (третий элемент кортежа)."""

    def test_uncomparable_payloads(self) -> None:
        """Сообщения с одинаковым приоритетом, но несравнимые → counter разрешает."""
        delivered: list = []

        class Uncomparable:
            """Объект без __lt__ — если heap попробует сравнить, будет TypeError."""

            def __lt__(self, other):
                raise TypeError("сравнение не должно происходить")

        sender = AsyncSender("test", send_fn=lambda msg: delivered.append(msg))
        sender.start()

        # Два сообщения с одинаковым приоритетом, несравнимые payload'ы
        sender.enqueue({"val": Uncomparable()}, priority="normal")
        sender.enqueue({"val": Uncomparable()}, priority="normal")

        time.sleep(0.1)
        sender.stop(timeout=2.0)

        # Оба доставлены без TypeError
        assert len(delivered) == 2
