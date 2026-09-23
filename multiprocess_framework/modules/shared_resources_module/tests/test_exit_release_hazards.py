# -*- coding: utf-8 -*-
"""Тесты автора на опасности механизма ``release_queues_at_exit`` (ADR-SRM-015).

Что может сломаться именно в ЭТОМ механизме:

- дедлайн считается на каждую очередь, а не общий → K застрявших очередей стоят
  K×бюджет, и процесс снова не укладывается в стоп;
- одна и та же очередь в двух ProcessData → двойной подсчёт / двойное ожидание;
- очередь уже закрыта и дожата → повторный close()/join не должен бросать;
- исключение в одной очереди обрывает цикл → остальные остаются блокировать выход;
- повторный вызов (runner вызван дважды) → не бросает, не ждёт бесконечно;
- «сирота»: объект очереди собран GC, а feeder и его ``_finalize_join`` живы —
  именно такой держал ProcessManager на ``inspection_full``;
- живой читатель: отпуск не должен терять то, что читатель успевает забрать.

Каждый вызов, который может заблокироваться, идёт в daemon-потоке / дочернем
процессе с дедлайном join — зависание превращается в провал, а не в таймаут.
"""

from __future__ import annotations

import gc
import multiprocessing
import threading
import time

from multiprocess_framework.modules.shared_resources_module.queues.core.exit_release import (
    EXIT_RELEASE_BUDGET_S,
    release_queues_at_exit,
)

_CTX = multiprocessing.get_context("spawn")
_CHUNK = b"x" * 65536


def _call_bounded(fn, *args, deadline: float = 10.0, **kwargs):
    """Вызвать ``fn`` в daemon-потоке; зависание → AssertionError, не хэнг сьюта."""
    box: dict = {}

    def target():
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — переносим в тест
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    started = time.monotonic()
    t.start()
    t.join(deadline)
    elapsed = time.monotonic() - started
    assert not t.is_alive(), f"вызов завис дольше {deadline}s"
    if "error" in box:
        raise box["error"]
    return box["result"], elapsed


def _stuck_queue(chunks: int = 40):
    """Очередь без читателя с feeder'ом, застрявшим в send_bytes на полном pipe."""
    q = _CTX.Queue()
    for _ in range(chunks):
        q.put(_CHUNK)
    time.sleep(0.2)  # feeder стартовал и упёрся в полный pipe
    return q


def _drain_raw(q) -> None:
    """Зачистка: вычерпать pipe напрямую, чтобы застрявший feeder дописал и вышел.

    ``get()`` у закрытой очереди бросает ValueError, поэтому читаем приватный
    ``_reader`` — только в тесте.
    """
    reader = q._reader
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        thread = getattr(q, "_thread", None)
        try:
            if reader.poll(0.05):
                reader.recv_bytes()
                continue
        except (OSError, EOFError):
            return  # feeder дописал, получил sentinel и сам закрыл концы pipe
        if thread is None or not thread.is_alive():
            return


class TestSharedDeadline:
    def test_k_stuck_queues_cost_one_budget_not_k(self) -> None:
        queues = [_stuck_queue() for _ in range(4)]
        try:
            (drained, abandoned), elapsed = _call_bounded(release_queues_at_exit, queues, 0.3)
            assert (drained, abandoned) == (0, 4)
            # K×бюджет = 1.2 s; общий дедлайн — ~0.3 s. Порог посередине.
            assert elapsed < 0.7, f"elapsed={elapsed:.3f}s — дедлайн похоже считается на очередь"
        finally:
            for q in queues:
                _drain_raw(q)


class TestInputShapes:
    def test_same_queue_listed_twice_counts_once(self) -> None:
        q = _stuck_queue()
        try:
            (drained, abandoned), elapsed = _call_bounded(release_queues_at_exit, [q, q], 0.3)
            assert (drained, abandoned) == (0, 1)
            assert elapsed < 0.55, f"elapsed={elapsed:.3f}s — дубль ждали дважды"
        finally:
            _drain_raw(q)

    def test_already_closed_and_joined_queue(self) -> None:
        q = _CTX.Queue()
        q.put("x")
        q.get(timeout=2.0)
        q.close()
        q.join_thread()
        (drained, abandoned), _ = _call_bounded(release_queues_at_exit, [q], 0.3)
        assert (drained, abandoned) == (1, 0)

    def test_queue_never_written_is_not_touched(self) -> None:
        q = _CTX.Queue()
        (drained, abandoned), _ = _call_bounded(release_queues_at_exit, [q], 0.3)
        assert (drained, abandoned) == (0, 0)
        # не закрыта: процесс, который из неё только читает, читает дальше
        q.put("still-open")
        assert q.get(timeout=2.0) == "still-open"
        q.close()
        q.join_thread()

    def test_exception_in_one_queue_does_not_stop_the_others(self) -> None:
        class _Broken:
            _thread = object()

            def close(self):
                raise RuntimeError("boom on close")

            def cancel_join_thread(self):
                raise RuntimeError("boom on cancel")

        class _BrokenThread:
            """feeder, у которого join бросает, а отпуск — тоже бросает."""

            def join(self, timeout=None):
                raise RuntimeError("boom on join")

            def is_alive(self):
                return True

        class _BrokenRelease:
            _thread = _BrokenThread()

            def close(self):
                pass

            def cancel_join_thread(self):
                raise RuntimeError("boom on cancel")

        stuck = _stuck_queue()
        try:
            (drained, abandoned), _ = _call_bounded(release_queues_at_exit, [_Broken(), _BrokenRelease(), stuck], 0.3)
            # _Broken отсеян на close(); _BrokenRelease и stuck — брошены, stuck отпущен
            assert (drained, abandoned) == (0, 2)
            assert stuck._joincancelled is True
        finally:
            _drain_raw(stuck)

    def test_broken_iterable_does_not_raise(self) -> None:
        def gen():
            yield _CTX.Queue()
            raise RuntimeError("iterator broke")

        (drained, abandoned), _ = _call_bounded(release_queues_at_exit, gen(), 0.3)
        assert (drained, abandoned) == (0, 0)

    def test_repeated_call_is_safe_and_bounded(self) -> None:
        q = _stuck_queue()
        try:
            first, _ = _call_bounded(release_queues_at_exit, [q], 0.2)
            second, elapsed = _call_bounded(release_queues_at_exit, [q], 0.2)
            assert first == (0, 1)
            assert second == (0, 1)
            assert elapsed < 0.5
        finally:
            _drain_raw(q)


def _live_reader(q, n, result_q) -> None:
    """Ребёнок-читатель: забирает ровно n элементов и отдаёт их индексы."""
    got = [q.get(timeout=10.0)[0] for _ in range(n)]
    result_q.put(got)
    result_q.close()
    result_q.join_thread()


class TestLiveReader:
    def test_everything_put_before_release_reaches_a_live_reader(self) -> None:
        q = _CTX.Queue()
        result_q = _CTX.Queue()
        # 200 × 64 КБ = 12.5 МБ — заведомо больше pipe: feeder дожимает под release
        for i in range(200):
            q.put((i, _CHUNK))
        reader = _CTX.Process(target=_live_reader, args=(q, 200, result_q))
        reader.start()
        try:
            (drained, abandoned), _ = _call_bounded(release_queues_at_exit, [q], 30.0, deadline=40.0)
            got = result_q.get(timeout=30.0)
            assert (drained, abandoned) == (1, 0)
            assert got == list(range(200))
        finally:
            reader.join(5.0)
            if reader.is_alive():
                reader.kill()
                reader.join(3.0)


def _orphan_child(result_q) -> None:
    """Ребёнок: делает сироту (очередь собрана GC, feeder застрял) и отпускает её."""
    q = multiprocessing.get_context("spawn").Queue()
    for _ in range(40):
        q.put(_CHUNK)
    time.sleep(0.2)
    del q
    gc.collect()
    result_q.put(release_queues_at_exit([], 0.3))
    result_q.close()
    result_q.join_thread()


class TestOrphanFeeder:
    def test_orphan_feeder_does_not_block_interpreter_exit(self) -> None:
        result_q = _CTX.Queue()
        child = _CTX.Process(target=_orphan_child, args=(result_q,))
        child.start()
        try:
            result = result_q.get(timeout=15.0)
            child.join(5.0)
            assert not child.is_alive(), "ребёнок висит на выходе — сирота не отпущена"
            assert result == (0, 1)
        finally:
            if child.is_alive():
                child.kill()
                child.join(3.0)


def test_budget_constant_is_the_measured_value() -> None:
    # ADR-SRM-015: 0.25 s — живой feeder дожимает за ≤0.5 мс (замер inspection_full).
    assert EXIT_RELEASE_BUDGET_S == 0.25
