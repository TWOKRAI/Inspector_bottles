# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 1.1 (`plans/lifecycle-graceful-stop.md`): выход процесса не
ждёт очередь к мёртвому читателю, но не теряет данные для живого.

Независимый прогон (tester, RED-стадия, ДО реализации): тестируется ЧЕРЕЗ
``run_process_function`` в настоящем дочернем OS-процессе (spawn), т.к. дефект
(feeder thread блокируется в ``send_bytes`` к мёртвому читателю, а
``cancel_join_thread()`` нигде не вызывается) живёт на границе
``multiprocessing.util._exit_function`` — эту границу не воспроизвести на
уровне одного процесса/мока.

Property A (ожидается RED): пишущий процесс забивает pipe очереди, читатель
которой мёртв (никто её не осушает) → после ``stop_event`` процесс обязан
завершиться за < 2.0s. Сегодня — виснет до ``join(5.0)`` в спавнере.

Property B (ожидается GREEN уже сегодня, guard против «нулевой отсрочки»):
живой читатель осушает очередь; процесс пишет одно сообщение перед стопом →
читатель его получает, и процесс всё равно укладывается в срок.
"""

from __future__ import annotations

import multiprocessing
import time

from multiprocess_framework.modules.process_manager_module.runner.process_runner import (
    run_process_function,
)

# ---------------------------------------------------------------------------
# Классы процессов — ОБЯЗАНЫ быть на верхнем уровне модуля: run_process_function
# грузит их динамически по dotted-пути (importlib), не пиклит.
# ---------------------------------------------------------------------------


class _FillQueueThenIdle:
    """Забивает очередь ~5 МБ payload'ом (читатель никогда не осушает), затем
    ждёт stop_event в обычном lifecycle-цикле (should_stop всегда False).

    ``put_nowait`` не блокируется сам (у ``multiprocessing.Queue`` maxsize=0
    по умолчанию — внутренний deque не ограничен), поэтому ``run()``
    завершается быстро; зависание — не здесь, а в фоновом feeder-потоке,
    который пытается протолкнуть накопленное в pipe, где никто не читает.
    """

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name
        self.shared_resources = shared_resources
        self.config = config

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        queue = self.shared_resources.process_state_registry.get_queue(self.name, "out")
        payload = b"x" * 1024
        for _ in range(5000):
            try:
                queue.put_nowait(payload)
            except Exception:
                break

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _PutMarkerThenIdle:
    """Кладёт ОДНО сообщение-маркер в очередь (читатель живой), затем ждёт stop_event."""

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name
        self.shared_resources = shared_resources
        self.config = config

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        queue = self.shared_resources.process_state_registry.get_queue(self.name, "out")
        queue.put("marker")

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _class_path(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _cleanup_child(child, queue) -> None:
    """Гарантированная зачистка: терминировать/убить ребёнка, освободить очередь.

    Вызывается ПОСЛЕ измерения (в finally), чтобы висящий (RED) сценарий не
    оставлял осиротевший процесс после теста — сам тест уже получил свой
    ``join(timeout=...)`` дедлайн выше.
    """
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


class TestExitBoundedWhenReaderDead:
    """Property A: дедлайн выхода не зависит от того, кто (и жив ли) читает очередь."""

    def _run_once(self) -> tuple[float, bool]:
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        stop_event = ctx.Event()
        bundle = {"queues": {"out": queue}, "config": {}, "custom": {}}

        child = ctx.Process(
            target=run_process_function,
            args=(_class_path(_FillQueueThenIdle), "Writer", stop_event, bundle, None),
        )
        child.start()
        try:
            # Дать ребёнку время выполнить run() и забить pipe (без читателя это
            # происходит быстро — но небольшой запас снимает гонку старта).
            time.sleep(1.0)
            stop_event.set()
            start = time.monotonic()
            child.join(timeout=2.0)
            elapsed = time.monotonic() - start
            alive = child.is_alive()
            return elapsed, alive
        finally:
            _cleanup_child(child, queue)

    def test_exit_is_bounded_when_queue_reader_is_dead(self) -> None:
        elapsed, alive = self._run_once()
        assert not alive, f"процесс всё ещё жив после join(timeout=2.0); elapsed={elapsed:.3f}s"
        assert elapsed < 2.0, f"выход занял {elapsed:.3f}s (>= 2.0s) — не уложился в дедлайн"


class TestMessageToLiveReaderDeliveredBeforeExit:
    """Property B (guard): живой читатель получает сообщение, и выход всё равно быстрый."""

    def test_message_to_live_reader_is_delivered_before_exit(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        stop_event = ctx.Event()
        bundle = {"queues": {"out": queue}, "config": {}, "custom": {}}

        child = ctx.Process(
            target=run_process_function,
            args=(_class_path(_PutMarkerThenIdle), "Writer", stop_event, bundle, None),
        )
        child.start()
        try:
            received = queue.get(timeout=2.0)
            stop_event.set()
            start = time.monotonic()
            child.join(timeout=2.0)
            elapsed = time.monotonic() - start
            alive = child.is_alive()

            assert received == "marker", f"читатель получил не то: {received!r}"
            assert not alive, f"процесс всё ещё жив после join(timeout=2.0); elapsed={elapsed:.3f}s"
            assert elapsed < 2.0, f"выход занял {elapsed:.3f}s (>= 2.0s) — не уложился в дедлайн"
        finally:
            _cleanup_child(child, queue)
