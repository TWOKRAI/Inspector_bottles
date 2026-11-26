"""C-36, ``retire_queue`` — hazard-тесты автора: гонка с первым ``put``, замки, повторный вызов.

Настоящие ``ReaderGoneQueue``, ``ProcessStateRegistry``, ``multiprocessing.queues`` этого интерпретатора.
Каждое ожидание имеет срок: повисший вызов — красный тест, а не повисший прогон.
"""

from __future__ import annotations

import multiprocessing
import threading
from typing import Any

from ..queues.core.reader_gone import RETIRE_STATS, ReaderGoneQueue, _buffered, retire_queue
from ..state.process_state_registry import ProcessStateRegistry

_BIG = b"x" * (1024 * 1024)  # заведомо больше буфера pipe: без читателя feeder встаёт


class _GatedSem:
    """Семафор очереди с паузой: ``put`` уже прошёл проверку ``_closed``, но ещё не вошёл в ``_notempty``."""

    def __init__(self, real: Any, entered: threading.Event, go: threading.Event) -> None:
        self._real, self._entered, self._go = real, entered, go

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        got = self._real.acquire(*args, **kwargs)
        self._entered.set()
        self._go.wait(10.0)
        return got

    def release(self) -> None:
        self._real.release()


def _race_first_put_with_retire(q: Any, conn: Any) -> None:
    """Spawn-писатель: первый ``put`` стоит внутри ``_start_thread`` между чтением ``_joincancelled`` и join."""
    import multiprocessing.queues as mp_queues

    real_finalize, real_close, real_sem = mp_queues.Finalize, q.close, q._sem
    in_put, go_put, closed, go_retire, in_finalize, go_finalize = (threading.Event() for _ in range(6))

    def _slow_finalize(obj: Any, callback: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(callback, "__name__", "") == "_finalize_join":
            in_finalize.set()
            go_finalize.wait(10.0)
        return real_finalize(obj, callback, *args, **kwargs)

    def _close_then_pause() -> None:
        real_close()
        closed.set()
        go_retire.wait(10.0)

    mp_queues.Finalize = _slow_finalize
    q._sem = _GatedSem(real_sem, in_put, go_put)
    q.close = _close_then_pause

    writer = threading.Thread(target=q.put, args=(_BIG,), daemon=True)
    writer.start()
    steps = [in_put.wait(10.0)]
    retirer = threading.Thread(target=retire_queue, args=(q,), daemon=True)
    retirer.start()
    steps.append(closed.wait(10.0))
    go_put.set()
    steps.append(in_finalize.wait(10.0))
    go_retire.set()
    retirer.join(0.5)  # с замком отпуск ждёт здесь, пока put не зарегистрирует join
    go_finalize.set()
    writer.join(10.0)
    retirer.join(10.0)
    conn.send((steps, writer.is_alive(), retirer.is_alive()))


def test_first_put_in_flight_during_retire_does_not_leave_a_join_registered() -> None:
    ctx = multiprocessing.get_context("spawn")
    q = ReaderGoneQueue(ctx=ctx)
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_race_first_put_with_retire, args=(q, child), daemon=True)
    proc.start()
    try:
        assert parent.poll(40.0), "ребёнок не прошёл сценарий"
        steps, writer_alive, retirer_alive = parent.recv()
        assert (steps, writer_alive, retirer_alive) == ([True, True, True], False, False)
        proc.join(5.0)
        assert proc.exitcode == 0, "писатель не вышел за 5 с: join feeder'а остался зарегистрированным"
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join(5.0)
        q.cancel_join_thread()
        q.close()


def test_unforced_first_put_against_retire_200_repeats_never_leaves_a_join() -> None:
    """Без подстроенного порядка. Инъекцию «отмена вне ``_notempty``» этот тест может и не ловить."""
    left: list[int] = []
    for i in range(200):
        q = ReaderGoneQueue()
        barrier = threading.Barrier(2, timeout=5.0)

        def _put(queue: Any = q, gate: threading.Barrier = barrier) -> None:
            gate.wait()
            try:
                queue.put(b"x")
            except ValueError:  # отпуск успел раньше — отказ законен
                pass

        def _retire(queue: Any = q, gate: threading.Barrier = barrier) -> None:
            gate.wait()
            retire_queue(queue)

        threads = [threading.Thread(target=_put, daemon=True), threading.Thread(target=_retire, daemon=True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5.0)
        assert not any(thread.is_alive() for thread in threads), f"повтор {i} завис"
        if q._jointhread is not None and q._jointhread.still_active():
            left.append(i)
    assert left == []


def test_retire_does_not_touch_the_reader_gone_event() -> None:
    """Замок ``Event`` занят (читатель убит внутри ``is_set``): отпуск обязан вернуться."""
    q = ReaderGoneQueue()
    q.put(b"x")
    assert q._reader_gone._cond.acquire(False) is True
    try:
        thread = threading.Thread(target=retire_queue, args=(q,), daemon=True)
        thread.start()
        thread.join(3.0)
        assert not thread.is_alive(), "retire_queue взял замок Event метки"
    finally:
        q._reader_gone._cond.release()


def test_drop_does_not_hold_the_registry_lock_while_retiring() -> None:
    """``q._notempty`` занят — отпуск ждёт, но реестр состояний остаётся доступен другим потокам."""
    psr = ProcessStateRegistry()
    psr.register_process("peer")
    q = ReaderGoneQueue()
    psr.add_queue("peer", "data", q)
    assert q._notempty.acquire(timeout=1.0)
    dropper = threading.Thread(target=psr.drop_process_queues, args=("peer",), daemon=True)
    try:
        dropper.start()
        dropper.join(0.3)
        assert dropper.is_alive(), "предусловие: отпуск стоит на q._notempty"
        seen: list[bool] = []
        reader = threading.Thread(target=lambda: seen.append(psr.has_process("peer")), daemon=True)
        reader.start()
        reader.join(2.0)
        assert seen == [True], "реестр заблокирован на время отпуска"
    finally:
        q._notempty.release()
        dropper.join(5.0)


def test_second_retire_of_the_same_queue_counts_nothing() -> None:
    q = ReaderGoneQueue()
    q.put(b"x")
    before = dict(RETIRE_STATS)
    retire_queue(q)
    assert retire_queue(q) == 0
    assert RETIRE_STATS["queues_retired"] - before["queues_retired"] == 1


def test_plain_queue_objects_are_left_alone() -> None:
    """Очередь не из реестра (``mp.Queue``) не закрывается — то же правило, что у метки (ADR-SRM-016)."""
    q = multiprocessing.Queue()
    try:
        assert retire_queue(q) == 0
        q.put(b"x")
        assert q.get(timeout=5.0) == b"x"
    finally:
        q.close()


def test_never_written_queue_is_not_counted() -> None:
    q = ReaderGoneQueue()
    before = dict(RETIRE_STATS)
    assert retire_queue(q) == 0
    assert RETIRE_STATS == before


def test_counting_the_buffer_survives_a_feeder_popping_without_the_lock() -> None:
    """``_feed`` снимает элементы ``popleft`` без ``_notempty``: счёт не должен падать на мутации deque."""
    q = ReaderGoneQueue()
    q._buffer.extend([b"x"] * 200_000)
    stop = threading.Event()

    def _churn() -> None:
        while not stop.is_set():
            q._buffer.append(b"x")
            q._buffer.popleft()

    worker = threading.Thread(target=_churn, daemon=True)
    worker.start()
    errors: list[str] = []
    try:
        for _ in range(20):
            try:
                _buffered(q)
            except RuntimeError as exc:
                errors.append(str(exc))
    finally:
        stop.set()
        worker.join(5.0)
        q._buffer.clear()
        q.close()
    assert errors == []
