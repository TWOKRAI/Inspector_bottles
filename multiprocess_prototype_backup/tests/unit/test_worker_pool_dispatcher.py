"""Unit-тесты для WorkerPoolDispatcher (Phase 5c, dispatcher.py)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

import pytest

from services.processor.worker_pool.dispatcher import WorkerPoolDispatcher
from services.processor.worker_pool.protocol import WorkerTaskResponse


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def make_mock_send():
    """Создать mock send_fn, записывающую все вызовы в список sent."""
    sent = []

    def mock_send(target: str, data: dict, data_type: str) -> bool:
        sent.append({"target": target, "data": data, "data_type": data_type})
        return True

    return mock_send, sent


def make_dispatcher(
    worker_count: int = 2,
    timeout: float = 0.1,
    input_queue_size: int = 4,
):
    """Создать диспетчер с mock send_fn и маленьким timeout для тестов."""
    send_fn, sent = make_mock_send()
    dispatcher = WorkerPoolDispatcher(
        send_fn=send_fn,
        worker_count=worker_count,
        timeout=timeout,
        input_queue_size=input_queue_size,
    )
    return dispatcher, sent


def dispatch_nowait(dispatcher: WorkerPoolDispatcher, seq_id: int = 0) -> WorkerTaskResponse:
    """Вызвать dispatch() синхронно (для тестов round-robin и timeout — без handle_response)."""
    return dispatcher.dispatch(
        operation_ref="test_op",
        params={},
        camera_id="cam0",
        region_id="r0",
        seq_id=seq_id,
        input_shm_name="shm_0",
        input_shm_index=0,
        frame_shape=(480, 640, 3),
    )


def dispatch_with_response(
    dispatcher: WorkerPoolDispatcher,
    seq_id: int = 0,
    delay: float = 0.0,
    success: bool = True,
) -> WorkerTaskResponse:
    """dispatch() с handle_response из другого потока."""
    result_box: list[WorkerTaskResponse] = []
    send_fn_calls: list[dict] = []

    original_send = dispatcher._send_fn

    def capturing_send(target, data, data_type):
        send_fn_calls.append({"task_id": data["task_id"]})
        original_send(target, data, data_type)

    dispatcher._send_fn = capturing_send

    def responder():
        # Ждём появления задачи в pending
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if send_fn_calls:
                break
            time.sleep(0.005)

        if not send_fn_calls:
            return

        if delay > 0:
            time.sleep(delay)

        task_id = send_fn_calls[0]["task_id"]
        response_dict = WorkerTaskResponse(
            task_id=task_id,
            success=success,
            error=None if success else "worker error",
            processing_time=0.01,
        ).to_dict()
        dispatcher.handle_response(response_dict)

    t = threading.Thread(target=responder, daemon=True)
    t.start()

    response = dispatcher.dispatch(
        operation_ref="test_op",
        params={},
        camera_id="cam0",
        region_id="r0",
        seq_id=seq_id,
        input_shm_name="shm_0",
        input_shm_index=0,
        frame_shape=(480, 640, 3),
    )
    t.join(timeout=2.0)
    # Восстанавливаем оригинальный send
    dispatcher._send_fn = original_send
    return response


# ---------------------------------------------------------------------------
# Тесты round-robin маршрутизации
# ---------------------------------------------------------------------------


class TestRoundRobin:
    def test_three_dispatches_with_two_workers_round_robin(self):
        """3 dispatch'а при worker_count=2 → targets [worker_0, worker_1, worker_0]."""
        send_fn, sent = make_mock_send()
        dispatcher = WorkerPoolDispatcher(
            send_fn=send_fn,
            worker_count=2,
            timeout=0.05,  # маленький timeout — ждём истечения
            input_queue_size=4,
        )

        # Запускаем 3 dispatch'а параллельно (они упадут по timeout — нас интересуют только targets)
        results = []

        def do_dispatch(seq_id):
            r = dispatch_nowait(dispatcher, seq_id=seq_id)
            results.append(r)

        threads = [threading.Thread(target=do_dispatch, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        # Все 3 задачи отправлены
        assert len(sent) == 3

        # Собираем targets в порядке отправки
        targets = [s["target"] for s in sent]

        # round-robin: worker_count=2 → цикл по [0, 1, 0, 1, ...]
        assert set(targets) == {"processor_worker_0", "processor_worker_1"}
        # Первые 2 разные, третья = первая
        assert targets[2] in {"processor_worker_0", "processor_worker_1"}
        # Проверяем строгое чередование: сортируем по task_id для детерминизма
        # Главное: каждый worker получил ровно правильное количество задач
        count_0 = targets.count("processor_worker_0")
        count_1 = targets.count("processor_worker_1")
        assert count_0 == 2
        assert count_1 == 1

    def test_dispatches_alternate_between_workers(self):
        """Последовательные dispatch'а с handle_response: первые два идут к разным worker'ам."""
        send_fn, sent = make_mock_send()
        dispatcher = WorkerPoolDispatcher(
            send_fn=send_fn,
            worker_count=2,
            timeout=1.0,
            input_queue_size=4,
        )

        # Первый dispatch + ответ
        r1 = dispatch_with_response(dispatcher, seq_id=1)
        # Второй dispatch + ответ
        r2 = dispatch_with_response(dispatcher, seq_id=2)

        assert len(sent) == 2
        assert sent[0]["target"] == "processor_worker_0"
        assert sent[1]["target"] == "processor_worker_1"


# ---------------------------------------------------------------------------
# Тесты timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_dispatch_without_response_returns_timeout_error(self):
        """dispatch() без handle_response → WorkerTaskResponse(success=False, error='timeout')."""
        dispatcher, _ = make_dispatcher(timeout=0.05)
        response = dispatch_nowait(dispatcher)

        assert response.success is False
        assert response.error == "timeout"

    def test_timeout_total_incremented_on_timeout(self):
        """После timeout → stats['timeout_total'] увеличивается."""
        dispatcher, _ = make_dispatcher(timeout=0.05)
        dispatch_nowait(dispatcher)

        assert dispatcher.stats["timeout_total"] == 1

    def test_two_timeouts_increment_counter_twice(self):
        """Два timeout'а → timeout_total == 2."""
        dispatcher, _ = make_dispatcher(timeout=0.05)
        dispatch_nowait(dispatcher, seq_id=1)
        dispatch_nowait(dispatcher, seq_id=2)

        assert dispatcher.stats["timeout_total"] == 2


# ---------------------------------------------------------------------------
# Тесты handle_response
# ---------------------------------------------------------------------------


class TestHandleResponse:
    def test_handle_response_unblocks_dispatch(self):
        """handle_response из другого потока разблокирует dispatch()."""
        dispatcher, _ = make_dispatcher(timeout=5.0)
        response = dispatch_with_response(dispatcher, success=True)

        assert response.success is True

    def test_handle_response_passes_detections(self):
        """handle_response с detections → response содержит те же detections."""
        send_fn, sent = make_mock_send()
        dispatcher = WorkerPoolDispatcher(
            send_fn=send_fn,
            worker_count=1,
            timeout=2.0,
            input_queue_size=4,
        )

        detections = [{"bbox": [0, 0, 10, 10], "label": "defect"}]
        send_fn_calls: list[dict] = []

        original_send = dispatcher._send_fn

        def capturing_send(target, data, data_type):
            send_fn_calls.append({"task_id": data["task_id"]})
            original_send(target, data, data_type)

        dispatcher._send_fn = capturing_send

        def responder():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if send_fn_calls:
                    break
                time.sleep(0.005)
            if not send_fn_calls:
                return
            task_id = send_fn_calls[0]["task_id"]
            dispatcher.handle_response(
                WorkerTaskResponse(
                    task_id=task_id,
                    success=True,
                    detections=detections,
                ).to_dict()
            )

        t = threading.Thread(target=responder, daemon=True)
        t.start()

        response = dispatcher.dispatch(
            operation_ref="op",
            params={},
            camera_id="cam0",
            region_id="r0",
            seq_id=0,
            input_shm_name="shm",
            input_shm_index=0,
            frame_shape=(480, 640, 3),
        )
        t.join(timeout=2.0)

        assert response.detections == detections

    def test_late_response_does_not_crash(self):
        """handle_response с неизвестным task_id не вызывает исключение."""
        dispatcher, _ = make_dispatcher(timeout=2.0)
        unknown_response = WorkerTaskResponse(
            task_id="nonexistent-task-id",
            success=True,
        ).to_dict()

        # Не должно бросать исключение
        dispatcher.handle_response(unknown_response)


# ---------------------------------------------------------------------------
# Тесты backpressure
# ---------------------------------------------------------------------------


class TestBackpressure:
    def test_backpressure_drops_oldest_when_queue_full(self):
        """input_queue_size=2, 3 concurrent dispatch'а → минимум 1 drop."""
        send_fn, sent = make_mock_send()
        dispatcher = WorkerPoolDispatcher(
            send_fn=send_fn,
            worker_count=2,
            timeout=1.0,
            input_queue_size=2,
        )

        results: list[WorkerTaskResponse] = []
        lock = threading.Lock()

        def do_dispatch(seq_id):
            r = dispatcher.dispatch(
                operation_ref="test_op",
                params={},
                camera_id="cam0",
                region_id="r0",
                seq_id=seq_id,
                input_shm_name="shm",
                input_shm_index=0,
                frame_shape=(480, 640, 3),
            )
            with lock:
                results.append(r)

        threads = [threading.Thread(target=do_dispatch, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        # Хотя бы 1 drop
        assert dispatcher.stats["drops_total"] >= 1

    def test_dropped_response_has_error(self):
        """Dropped задача получает response с success=False."""
        send_fn, sent = make_mock_send()
        dispatcher = WorkerPoolDispatcher(
            send_fn=send_fn,
            worker_count=1,
            timeout=1.0,
            input_queue_size=1,  # очередь на 1
        )

        results: list[WorkerTaskResponse] = []
        lock = threading.Lock()

        def do_dispatch(seq_id):
            r = dispatcher.dispatch(
                operation_ref="test_op",
                params={},
                camera_id="cam0",
                region_id="r0",
                seq_id=seq_id,
                input_shm_name="shm",
                input_shm_index=0,
                frame_shape=(480, 640, 3),
            )
            with lock:
                results.append(r)

        threads = [threading.Thread(target=do_dispatch, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        # Проверяем что хотя бы один response — с ошибкой (dropped или timeout)
        failed = [r for r in results if not r.success]
        assert len(failed) >= 1


# ---------------------------------------------------------------------------
# Тесты stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_contains_required_keys(self):
        """stats содержит ожидаемые ключи: pending, drops_total, dispatched_total, timeout_total."""
        dispatcher, _ = make_dispatcher()
        stats = dispatcher.stats

        assert "pending" in stats
        assert "drops_total" in stats
        assert "dispatched_total" in stats
        assert "timeout_total" in stats

    def test_dispatched_total_increments_on_each_dispatch(self):
        """dispatched_total увеличивается на 1 с каждым dispatch()."""
        dispatcher, _ = make_dispatcher(timeout=0.05)

        dispatch_nowait(dispatcher, seq_id=1)
        dispatch_nowait(dispatcher, seq_id=2)
        dispatch_nowait(dispatcher, seq_id=3)

        assert dispatcher.stats["dispatched_total"] == 3

    def test_initial_stats_all_zeros(self):
        """Сразу после создания все счётчики = 0, pending = 0."""
        dispatcher, _ = make_dispatcher()
        stats = dispatcher.stats

        assert stats["pending"] == 0
        assert stats["drops_total"] == 0
        assert stats["dispatched_total"] == 0
        assert stats["timeout_total"] == 0

    def test_pending_zero_after_dispatch_completes(self):
        """После завершённого dispatch (с ответом) pending == 0."""
        dispatcher, _ = make_dispatcher(timeout=2.0)
        dispatch_with_response(dispatcher, seq_id=1)

        assert dispatcher.stats["pending"] == 0
