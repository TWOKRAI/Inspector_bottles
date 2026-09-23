# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 1.1 (`plans/lifecycle-graceful-stop.md`): выход процесса не
ждёт очередь к мёртвому читателю, но не теряет данные для живого.

Property A («writer забивает очередь к мёртвому читателю → выход < 2.0s») здесь
БОЛЬШЕ НЕ ПРОВЕРЯЕТСЯ как контракт writer'а — отклонена итерацией 2 (ревью нашёл:
у процесса нет способа отличить мёртвого читателя от медленного, а generic-отпуск
feeder'а рвёт кадр в pipe живому-но-медленному читателю и вешает его навсегда,
15/100 доставлено вместо 100/100). См. ADR-SRM-015 (rejected) в
`shared_resources_module/DECISIONS.md`: корень сиротской очереди — EventManager
(fixed at the source, `events/core/manager.py`), а внешнее поведение для мёртвого
читателя (terminate спавнером после бюджета) остаётся прежним.

Property B (GREEN, guard против «нулевой отсрочки» и против повторного появления
generic-отпуска): живой читатель осушает очередь; процесс пишет одно сообщение
перед стопом → читатель его получает, и процесс всё равно укладывается в срок.
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
