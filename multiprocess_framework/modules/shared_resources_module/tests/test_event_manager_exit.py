# -*- coding: utf-8 -*-
"""Тесты Task 1.1 итерация 2 (`plans/lifecycle-graceful-stop.md`): реальный корень
5s-зависания на стопе — процесс-локальная `_event_queue` в EventManager
(`events/core/manager.py`), которую пишет только `emit_event`, а читает только
`wait_for_event` (вне тестов никто не зовёт). Раньше это была `multiprocessing.Queue`
без единого читателя в другом процессе — pipe набивался, `Queue._finalize_join` на
выходе ждал feeder вечно. Фикс: процесс-локальная bounded `queue.Queue`
(ADR-SRM-015, пересмотр).

(a) — RED на старом коде (mp.Queue): ребёнок эмитит 5000 событий и не читает их сам →
    висит на выходе. GREEN после фикса.
(b), (c) — свойства новой bounded-очереди (drop-oldest, wait_for_event).
(d) — guard ревьюера (находка 1, c7636aa3): живой, но медленный читатель ДОЛЖЕН
    получить всё без обрезанного кадра в pipe — GREEN и до, и после (пин на то, что
    generic-отпуск очереди больше НЕ применяется; ADR-SRM-015 rejected-часть).
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from queue import Empty

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import (
    run_process_function,
)

from ..events import EventManager
from ..events.core.manager import EVENT_QUEUE_MAXSIZE
from ..types import EventType

# ---------------------------------------------------------------------------
# (a) — top-level функция: multiprocessing spawn пиклит цель по dotted-пути,
# ей нужно жить на верхнем уровне модуля.
# ---------------------------------------------------------------------------


def _emit_5000_and_exit() -> None:
    em = EventManager()
    em.initialize()
    for _ in range(5000):
        em.emit_event(EventType.CONFIG_UPDATED)
    # Никто не читает _event_queue — ровно сценарий сироты (ADR-SRM-015).


class TestChildExitsDespiteUndrainedQueue:
    """Property (a): child с непрочитанными 5000 событий обязан выйти быстро."""

    def test_child_with_5000_unread_events_exits_within_2s(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        child = ctx.Process(target=_emit_5000_and_exit)
        start = time.monotonic()
        child.start()
        child.join(timeout=2.0)
        elapsed = time.monotonic() - start
        alive = child.is_alive()
        if alive:
            child.terminate()
            child.join(timeout=3.0)
            if child.is_alive():
                child.kill()
                child.join(timeout=3.0)
        assert not alive, f"дочерний процесс не вышел за 2.0s; elapsed={elapsed:.3f}s"
        assert elapsed < 2.0, f"выход занял {elapsed:.3f}s (>= 2.0s) — не уложился в дедлайн"


@pytest.fixture
def em():
    """EventManager в процессе pytest; teardown вычитывает очередь.

    Страж от зависания всего набора при регрессии: если очередь снова станет
    ``multiprocessing.Queue`` (инъекция J1, 2026-09-23), непрочитанные события
    держат feeder, и pytest виснет на СВОЁМ выходе вместо того, чтобы упасть.
    """
    manager = EventManager()
    manager.initialize()
    yield manager
    queue = manager.get_event_queue()
    while queue is not None:
        try:
            queue.get(timeout=0.2)
        except Empty:
            break


def test_event_queue_capacity_is_1000() -> None:
    """Литерал отдельно от кода: тесты (b) выводят ожидаемое из константы."""
    assert EVENT_QUEUE_MAXSIZE == 1000


class TestBoundedDropOldest:
    """Property (b): переполнение вытесняет старейшее, считает dropped."""

    def test_overflow_drops_oldest_keeps_newest_and_counts_dropped(self, em) -> None:
        n = EVENT_QUEUE_MAXSIZE + 10
        for i in range(n):
            em.emit_event(EventType.CONFIG_UPDATED, seq=i)

        assert em.get_event_queue().qsize() == EVENT_QUEUE_MAXSIZE
        assert em.get_stats()["events"]["dropped"] == 10

        seqs = []
        while True:
            try:
                seqs.append(em.get_event_queue().get_nowait()["seq"])
            except Empty:
                break
        assert len(seqs) == EVENT_QUEUE_MAXSIZE
        assert seqs[0] == 10  # 0..9 вытеснены (10 dropped)
        assert seqs[-1] == n - 1  # новейшее сохранено


class TestWaitForEventRequeuesNonMatching:
    """Property (c): wait_for_event находит совпадение, остальное возвращает в очередь."""

    def test_wait_for_event_returns_match_and_requeues_others(self, em) -> None:
        em.emit_event(EventType.QUEUE_ADDED, seq=1)
        em.emit_event(EventType.PROCESS_REGISTERED, seq=2)
        em.emit_event(EventType.QUEUE_ADDED, seq=3)

        found = em.wait_for_event(EventType.PROCESS_REGISTERED, timeout=1.0)
        assert found is not None
        assert found["event_type"] == "process_registered"
        assert found["seq"] == 2

        remaining = []
        while True:
            try:
                remaining.append(em.get_event_queue().get_nowait()["seq"])
            except Empty:
                break
        assert sorted(remaining) == [1, 3]


# ---------------------------------------------------------------------------
# (d) — guard ревьюера: живой, но медленный читатель. Top-level класс — тот же
# повод, что и у (a): run_process_function грузит его по dotted-пути.
# ---------------------------------------------------------------------------


class _Put100Messages:
    """Кладёт 100 сообщений по 4 КБ в очередь бандла и завершается нормально."""

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name
        self.shared_resources = shared_resources
        self.config = config

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        queue = self.shared_resources.process_state_registry.get_queue(self.name, "out")
        payload = b"x" * 4096
        for i in range(100):
            queue.put((i, payload))

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _class_path(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _read_all(queue, n: int, result_box: dict) -> None:
    try:
        got = [queue.get(timeout=10.0)[0] for _ in range(n)]
        result_box["result"] = got
    except BaseException as exc:  # noqa: BLE001 — переносим в тест
        result_box["error"] = exc


class TestSlowLiveReaderNoTruncation:
    """Guard: находка 1 ревью c7636aa3 — generic-отпуск очереди рвал кадр живому,
    но медленному читателю (15/100 доставлено, читатель зависал навсегда). Без
    generic-отпуска (эта итерация) доставка полная и читатель не виснет — GREEN
    и на старом, и на новом коде: это пин на ОТСУТСТВИЕ механизма, а не на фикс.
    """

    def test_slow_reader_gets_all_100_messages_after_normal_exit(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        stop_event = ctx.Event()
        bundle = {"queues": {"out": queue}, "config": {}, "custom": {}}

        child = ctx.Process(
            target=run_process_function,
            args=(_class_path(_Put100Messages), "Writer", stop_event, bundle, None),
        )
        child.start()
        try:
            time.sleep(0.1)
            stop_event.set()
            time.sleep(0.7)  # читатель стартует на 0.7s позже стопа (случай ревьюера)

            result_box: dict = {}
            reader_thread = threading.Thread(target=_read_all, args=(queue, 100, result_box), daemon=True)
            reader_started = time.monotonic()
            reader_thread.start()
            reader_thread.join(timeout=8.0)
            reader_elapsed = time.monotonic() - reader_started

            assert not reader_thread.is_alive(), (
                f"reader.get() завис дольше 8.0s (elapsed={reader_elapsed:.3f}s) — "
                "обрезанный кадр в pipe к живому читателю"
            )
            assert "error" not in result_box, f"reader упал: {result_box.get('error')}"
            got = result_box.get("result")
            assert got == list(range(100)), f"получено {len(got or [])}/100"
        finally:
            if child.is_alive():
                child.terminate()
                child.join(timeout=3.0)
            if child.is_alive():
                child.kill()
                child.join(timeout=3.0)
            try:
                queue.close()
                queue.cancel_join_thread()
            except Exception:
                pass
