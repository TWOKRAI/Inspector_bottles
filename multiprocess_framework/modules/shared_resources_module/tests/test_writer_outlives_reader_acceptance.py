# -*- coding: utf-8 -*-
"""Task 1.2 (`plans/lifecycle-graceful-stop.md`) — независимый акцептанс, ДО реализации.

Второй источник 5s-зависания на стопе (первый, EventManager, закрыт Task 1.1,
см. ``test_event_manager_exit.py``): реальный межпроцессный ``mp.Queue`` между
двумя framework-процессами. Замер 2026-09-23 (faulthandler, 3 из 3 зависаний):
``gui`` выходит, пока ``renderer`` кладёт кадр в его очередь ``data`` через
``QueueRegistry.send_to_queue``; кадр крупнее свободного места в OS pipe;
EPIPE не приходит, потому что каждый процесс, получивший ссылку на очередь,
держит read-конец открытым; на выходе интерпретатора ``multiprocessing``
джойнит feeder-поток очереди (``queues._finalize_join``) — навсегда.

Контракт — ДВЕ стороны одновременно (обе пинуются здесь, из чёрного ящика,
без знания будущего механизма):
  (1) читатель мёртв НАВСЕГДА (вышел раньше put ИЛИ вышел, не читая, уже
      после put) → писатель обязан выйти по своему ``stop_event`` быстро;
  (2) читатель ЖИВ, но МЕДЛЕННЫЙ → доставка ПОЛНАЯ, читатель не виснет.
      (2) — guard находки ревью Task 1.1 (generic wall-clock отпуск feeder'а
      обрезал кадр живому читателю); эти тесты обязаны остаться GREEN и до, и
      после фикса — это пин на ОТСУТСТВИЕ такого механизма.

Топология зеркалит прод: очередь принадлежит читателю (``queues={"data": q}``
в его bundle), писатель достаёт её как соседа через ``routing_map`` (см.
``bundle_builder._build_shared_resources_from_bundle``) и шлёт ЕДИНСТВЕННО
продовым путём — ``SharedResourcesManager.queue_registry.send_to_queue``, а
не сырым ``queue.put``.

Дочерние процессы — top-level классы (dotted-path для spawn-pickle), тот же
приём, что в ``test_event_manager_exit.py``.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

from multiprocess_framework.modules.process_manager_module.runner.process_runner import (
    run_process_function,
)

# ---------------------------------------------------------------------------
# Top-level классы дочерних процессов (spawn пиклит цель по dotted-пути).
# ---------------------------------------------------------------------------


class _ReaderDoesNotRead:
    """Читатель владеет очередью 'data' (bundle ``queues={"data": q}``), но НИКОГДА
    её не читает. Выходит штатно — ждёт СВОЙ ``stop_event`` (framework lifecycle),
    никогда не через terminate. Тесты 1 и 2 различаются только МОМЕНТОМ, когда
    тест взводит этот ``stop_event`` относительно отправки писателем.
    """

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        pass

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _SendOneBigMessageThenWaitForStop:
    """Писатель: кладёт ОДНО сообщение 1 MiB продовым путём
    (``queue_registry.send_to_queue``) соседу 'Reader' через ``routing_map``,
    затем штатно ждёт СВОЙ ``stop_event`` — ровно framework-путь выхода."""

    TARGET_PROCESS = "Reader"
    QUEUE_TYPE = "data"
    PAYLOAD = b"x" * (1024 * 1024)  # 1 MiB — заведомо больше OS pipe buffer

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        self.shared_resources.queue_registry.send_to_queue(self.TARGET_PROCESS, self.QUEUE_TYPE, self.PAYLOAD)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _SendBigThenSmallMessagesThenWaitForStop:
    """Писатель: 1 сообщение 1 MiB + 5 маленьких (индекс, метка) продовым путём,
    затем штатно ждёт СВОЙ ``stop_event``. Для guard-теста «медленный, но живой
    читатель» — топология писателя идентична (routing_map), читает тест-процесс
    напрямую из общей ``q`` (см. ``TestSlowLiveReaderNoTruncation`` в
    ``test_event_manager_exit.py`` — тот же приём: единственный дочерний процесс —
    писатель, читает тред в процессе pytest)."""

    TARGET_PROCESS = "Reader"
    QUEUE_TYPE = "data"
    BIG_PAYLOAD = b"x" * (1024 * 1024)
    SMALL_COUNT = 5

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        reg = self.shared_resources.queue_registry
        reg.send_to_queue(self.TARGET_PROCESS, self.QUEUE_TYPE, ("big", self.BIG_PAYLOAD))
        for i in range(self.SMALL_COUNT):
            reg.send_to_queue(self.TARGET_PROCESS, self.QUEUE_TYPE, ("small", i))

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _SendOneHundredMessagesThenWaitForStop:
    """E-d guard, но продовым путём: 100 сообщений по 4 КБ через
    ``send_to_queue`` + ``routing_map`` вместо сырого ``queue.put``."""

    TARGET_PROCESS = "Reader"
    QUEUE_TYPE = "data"

    def __init__(self, name: str, shared_resources: Any, config: dict) -> None:
        self.name = name
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        reg = self.shared_resources.queue_registry
        payload = b"x" * 4096
        for i in range(100):
            reg.send_to_queue(self.TARGET_PROCESS, self.QUEUE_TYPE, (i, payload))

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _class_path(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _join_bounded(proc, timeout: float):
    """join с дедлайном; если жив — terminate/kill (НЕ основной путь теста,
    только уборка), возвращает elapsed и alive-до-уборки."""
    start = time.monotonic()
    proc.join(timeout=timeout)
    elapsed = time.monotonic() - start
    alive = proc.is_alive()
    return elapsed, alive


def _cleanup(*procs) -> None:
    for proc in procs:
        if proc is None:
            continue
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=3.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=3.0)


def _read_n(queue, n: int, result_box: dict, timeout_per_item: float = 10.0) -> None:
    try:
        got = [queue.get(timeout=timeout_per_item) for _ in range(n)]
        result_box["result"] = got
    except BaseException as exc:  # noqa: BLE001 — переносим в тест
        result_box["error"] = exc


# ---------------------------------------------------------------------------
# (1) reader мёртв ДО put писателя.
# ---------------------------------------------------------------------------


class TestWriterExitsFastWhenReaderExitedBeforePut:
    def test_writer_exits_fast_when_reader_exited_before_put(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        reader_stop = ctx.Event()
        writer_stop = ctx.Event()

        reader_bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        writer_bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"Reader": {"data": q}},
        }

        reader = ctx.Process(
            target=run_process_function,
            args=(_class_path(_ReaderDoesNotRead), "Reader", reader_stop, reader_bundle, None),
        )
        writer = ctx.Process(
            target=run_process_function,
            args=(
                _class_path(_SendOneBigMessageThenWaitForStop),
                "Writer",
                writer_stop,
                writer_bundle,
                None,
            ),
        )
        try:
            reader.start()
            reader_stop.set()  # читатель мёртв НАВСЕГДА, ещё до put
            reader.join(timeout=5.0)
            assert not reader.is_alive(), "reader не вышел сам за 5.0s — тест не смог подготовить сценарий"

            writer.start()
            time.sleep(0.2)  # дать run() отправить сообщение до взвода stop
            writer_stop.set()
            elapsed, alive = _join_bounded(writer, timeout=2.0)

            assert not alive, f"writer не вышел за 2.0s после своего stop_event; elapsed={elapsed:.3f}s"
            assert elapsed < 2.0, f"writer вышел за {elapsed:.3f}s (>= 2.0s) — не уложился в дедлайн"
        finally:
            _cleanup(reader, writer)
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# (2) reader жив на момент put, выходит (не читая) ПОСЛЕ put писателя.
# ---------------------------------------------------------------------------


class TestWriterExitsFastWhenReaderExitsAfterPut:
    def test_writer_exits_fast_when_reader_exits_after_put(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        reader_stop = ctx.Event()
        writer_stop = ctx.Event()

        reader_bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        writer_bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"Reader": {"data": q}},
        }

        reader = ctx.Process(
            target=run_process_function,
            args=(_class_path(_ReaderDoesNotRead), "Reader", reader_stop, reader_bundle, None),
        )
        writer = ctx.Process(
            target=run_process_function,
            args=(
                _class_path(_SendOneBigMessageThenWaitForStop),
                "Writer",
                writer_stop,
                writer_bundle,
                None,
            ),
        )
        try:
            reader.start()
            writer.start()
            time.sleep(0.2)  # writer.run() успевает отправить 1 MiB

            reader_stop.set()  # reader жив был при put, теперь уходит — НЕ читая
            reader.join(timeout=5.0)
            assert not reader.is_alive(), "reader не вышел сам за 5.0s — тест не смог подготовить сценарий"

            writer_stop.set()
            elapsed, alive = _join_bounded(writer, timeout=2.0)

            assert not alive, f"writer не вышел за 2.0s после своего stop_event; elapsed={elapsed:.3f}s"
            assert elapsed < 2.0, f"writer вышел за {elapsed:.3f}s (>= 2.0s) — не уложился в дедлайн"
        finally:
            _cleanup(reader, writer)
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# (3) guard: reader ЖИВ, но МЕДЛЕННЫЙ — доставка ПОЛНАЯ, без обрезанного кадра.
# ---------------------------------------------------------------------------


class TestSlowLiveReaderGetsWholeBigMessage:
    """Ревью Task 1.1: generic-отпуск feeder'а по wall-clock рвал кадр живому, но
    медленному читателю. Без такого механизма (текущий код) — GREEN уже сейчас;
    после фикса Task 1.2 обязан остаться GREEN — это и есть guard."""

    def test_slow_reader_gets_whole_big_message_and_writer_exits(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        writer_stop = ctx.Event()

        writer_bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"Reader": {"data": q}},
        }
        writer = ctx.Process(
            target=run_process_function,
            args=(
                _class_path(_SendBigThenSmallMessagesThenWaitForStop),
                "Writer",
                writer_stop,
                writer_bundle,
                None,
            ),
        )
        try:
            writer.start()
            time.sleep(0.1)
            writer_stop.set()
            time.sleep(0.7)  # читатель стартует на 0.7s позже стопа писателя

            n = 1 + _SendBigThenSmallMessagesThenWaitForStop.SMALL_COUNT
            result_box: dict = {}
            reader_thread = threading.Thread(target=_read_n, args=(q, n, result_box), daemon=True)
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
            assert got is not None and len(got) == n, f"получено {len(got or [])}/{n}"
            assert got[0] == ("big", _SendBigThenSmallMessagesThenWaitForStop.BIG_PAYLOAD), (
                "большое сообщение обрезано или пришло не первым"
            )
            assert got[1:] == [("small", i) for i in range(_SendBigThenSmallMessagesThenWaitForStop.SMALL_COUNT)]

            # Читатель разобрал очередь — писатель обязан довыйти (feeder дописал).
            elapsed, alive = _join_bounded(writer, timeout=8.0)
            assert not alive, f"writer не вышел после того, как читатель всё разобрал; elapsed={elapsed:.3f}s"
        finally:
            _cleanup(writer)
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:
                pass


class TestSlowLiveReaderGetsAll100AfterWriterExit:
    """E-d guard (см. ``test_event_manager_exit.py``), но через
    ``send_to_queue`` + ``routing_map`` — топология писателя должна пинить то же
    свойство и продовым путём отправки, не только сырым ``queue.put``."""

    def test_slow_reader_gets_all_100_messages_after_normal_exit(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        writer_stop = ctx.Event()

        writer_bundle = {
            "queues": {},
            "config": {},
            "custom": {},
            "routing_map": {"Reader": {"data": q}},
        }
        writer = ctx.Process(
            target=run_process_function,
            args=(
                _class_path(_SendOneHundredMessagesThenWaitForStop),
                "Writer",
                writer_stop,
                writer_bundle,
                None,
            ),
        )
        try:
            writer.start()
            time.sleep(0.1)
            writer_stop.set()
            time.sleep(0.7)  # читатель стартует на 0.7s позже стопа писателя

            result_box: dict = {}
            reader_thread = threading.Thread(target=_read_n, args=(q, 100, result_box), daemon=True)
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
            assert got == [(i, b"x" * 4096) for i in range(100)], f"получено {len(got or [])}/100"

            elapsed, alive = _join_bounded(writer, timeout=8.0)
            assert not alive, f"writer не вышел после того, как читатель всё разобрал; elapsed={elapsed:.3f}s"
        finally:
            _cleanup(writer)
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:
                pass
