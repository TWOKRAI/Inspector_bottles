# -*- coding: utf-8 -*-
"""Ф0.5: независимые тесты на изоляцию контекста логирования.

Контракт (см. постановку задачи, не реализацию):
  1. push_context/pop_context изолированы ПО ПОТОКУ — поток A не видит и не
     портит контекст потока B.
  2. Вложенность и разворачивание контекста — тоже по потоку: внутренний
     push_context мержится поверх внешнего (конфликт ключа — побеждает
     внутренний), pop_context возвращает на предыдущий уровень ТОЛЬКО этого
     потока; pop_context() в потоке, который ничего не пушил — тихий no-op,
     а не исключение, и не должен стирать чужой контекст.
  3. Есть процессный (base) слой: set_base_context(**vars) — виден из ЛЮБОГО
     потока, включая свежесозданные воркер-потоки, которые никогда сами не
     вызывали push_context/set_base_context.
  4. Приоритет (低→高): log_context (ContextVar) → base_context → thread
     context (push_context) → явный extra= в вызове log().
  5. Если реализация хранит context в ContextVar — asyncio-таски (которые
     делят один OS-поток) должны получать ту же изоляцию, что и потоки.
  6. ErrorManager — брат LoggerManager (общий предок LoggerCore), баг и
     фикс должны воспроизводиться одинаково в обоих потомках.

Этот файл написан НЕЗАВИСИМО от реализации core/logger_core.py — источник
контракта: interfaces.py (push_context/pop_context) + постановка задачи Ф0.5
(_get_thread_context, set_base_context, log_context ContextVar, приоритет
слоёв). core/logger_core.py в ходе написания тестов не открывался.
"""

from __future__ import annotations

import asyncio
import sys
import threading

from multiprocess_framework.modules.logger_module.core.logger_manager import (
    LoggerManager,
    log_context,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager


class _ThreadSafeTap:
    """Tap-канал (IChannel-совместимый: только write(dict)), безопасный для
    записи из нескольких потоков одновременно.

    list.append() в CPython атомарен под GIL, но замок явно снимает тест с
    зависимости от деталей текущего интерпретатора (в т.ч. на будущее —
    free-threaded CPython, PEP 703). Каждая запись копируется на месте —
    если реализация мутирует один и тот же dict "extra" вместо создания
    нового на каждый вызов log(), поверхностная копия record + отдельная
    копия extra всё равно зафиксируют состояние на момент write(), а не на
    момент чтения тестом (иначе гонка пряталась бы уже в самом тапе).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        snapshot = dict(record)
        snapshot["extra"] = dict(record.get("extra") or {})
        with self._lock:
            self.records.append(snapshot)

    def close(self) -> None:
        pass


def _make_logger(name: str) -> LoggerManager:
    mgr = LoggerManager(manager_name=name)
    mgr.initialize()
    return mgr


class TestThreadContextIsolation:
    """Пункт 1 контракта: push_context изолирован по потоку."""

    def test_push_context_isolated_between_two_threads_under_concurrent_load(self) -> None:
        """Два потока непрерывно пушат/логируют/попают СВОЙ контекст под
        барьером одновременного старта.

        ВАЖНАЯ ОГОВОРКА ПРО НАДЁЖНОСТЬ (проверено эмпирически при написании
        теста, 10 прогонов подряд без вмешательства в switch interval):
        короткая последовательность push→log→pop укладывается в один
        тайм-слайс потока (switch interval CPython по умолчанию ~5мс), из-за
        чего потоки нередко не перемежаются ВНУТРИ итерации даже при 1000
        итерациях на поток — тест ловил гонку примерно в half of прогонов
        и был бы задокументирован как «ловит иногда», если бы остался в
        этом виде. Вместо ``time.sleep()`` (который сам вносит таймингом
        управляемую, а не по-настоящему конкурентную гонку) здесь временно
        уменьшается ``sys.setswitchinterval()`` — интерпретатор чаще
        рассматривает переключение между потоками, окно гонки открывается
        внутри push→log почти на каждой итерации. Проверено эмпирически:
        10/10 прогонов дали 8-57 несовпадений из 600 записей — систематически,
        не эпизодически. Интервал восстанавливается в finally, чтобы не
        протечь в остальные тесты процесса.
        """
        mgr = _make_logger("CtxIsolationThreads")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        barrier = threading.Barrier(2)
        iterations = 300

        def worker(marker: str) -> None:
            barrier.wait(timeout=10)
            for i in range(iterations):
                mgr.push_context(worker=marker, seq=i)
                mgr.info("tick", module="ctx_test", thread_name=marker)
                mgr.pop_context()

        original_interval = sys.getswitchinterval()
        sys.setswitchinterval(0.00005)
        try:
            t_a = threading.Thread(target=worker, args=("A",))
            t_b = threading.Thread(target=worker, args=("B",))
            t_a.start()
            t_b.start()
            t_a.join(timeout=30)
            t_b.join(timeout=30)
        finally:
            sys.setswitchinterval(original_interval)
        mgr.shutdown()

        assert not t_a.is_alive() and not t_b.is_alive(), "поток завис — барьер/join не сработали"
        # Фильтр по module: mgr.shutdown() сам пишет служебную запись
        # (module="logger_manager") — она не наш сигнал, отсекаем её явно,
        # а не подгоняем счётчик под побочный эффект реализации.
        records = [r for r in tap.records if r["module"] == "ctx_test"]
        assert len(records) == 2 * iterations

        mismatches = [r for r in records if r["extra"].get("worker") != r["extra"].get("thread_name")]
        assert not mismatches, (
            f"контекст протёк между потоками: {len(mismatches)}/{len(records)} записей "
            f"несут чужой worker; пример: {mismatches[0]}"
        )


class TestNestedContextSingleThread:
    """Пункт 2 контракта (часть, не требующая многопоточности): вложенность
    push_context внутри ОДНОГО потока — мерж инера поверх внешнего, pop
    возвращает предыдущий уровень. Ожидаемо уже проходит сегодня — баг в
    задаче именно про МЕЖпоточную изоляцию, а не про сам стек как таковой."""

    def test_nested_push_context_merges_inner_wins_and_pop_restores_previous_level(self) -> None:
        mgr = _make_logger("CtxNestedSingleThread")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        mgr.push_context(a=1, b="outer")
        mgr.push_context(a=2, c="inner")  # конфликт по 'a' — внутренний должен победить
        mgr.info("nested", module="ctx_test")
        nested = tap.records[-1]
        assert nested["extra"]["a"] == 2
        assert nested["extra"]["b"] == "outer"
        assert nested["extra"]["c"] == "inner"

        mgr.pop_context()
        mgr.info("unwound", module="ctx_test")
        unwound = tap.records[-1]
        assert unwound["extra"]["a"] == 1
        assert unwound["extra"]["b"] == "outer"
        assert "c" not in unwound["extra"]

        mgr.pop_context()
        mgr.shutdown()


class TestPopContextCrossThreadSafety:
    """Пункт 2 контракта: pop_context() не должен ни бросать исключение в
    потоке с пустым СВОИМ стеком, ни стирать контекст ЧУЖОГО потока."""

    def test_pop_context_on_empty_own_stack_is_noop_not_exception(self) -> None:
        """Свежий поток, который никогда не вызывал push_context, вызывает
        pop_context() — ожидается тихий no-op, а не исключение (например
        IndexError от list.pop() на пустом списке)."""
        mgr = _make_logger("CtxPopEmptyOwnStack")
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                mgr.pop_context()
            except BaseException as exc:  # noqa: BLE001 — тест ловит ЛЮБОЕ исключение
                errors.append(exc)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=10)
        mgr.shutdown()

        assert not t.is_alive(), "поток завис"
        assert errors == [], f"pop_context() на пустом стеке потока бросил исключение: {errors!r}"

    def test_pop_context_in_other_thread_does_not_remove_this_threads_context(self) -> None:
        """Поток A пушит свой контекст и ждёт. Поток B, который сам НИЧЕГО
        не пушил, вызывает pop_context(). После этого поток A логирует —
        его собственный контекст обязан остаться на месте.

        Синхронизация через два Event (не таймингом) — детерминированный
        порядок: A push → B pop → A log. Никакой гонки в самом тесте нет,
        гонка — только в проверяемом поведении менеджера."""
        mgr = _make_logger("CtxPopOtherThread")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        a_pushed = threading.Event()
        b_popped = threading.Event()

        def thread_a() -> None:
            mgr.push_context(owner="A")
            a_pushed.set()
            assert b_popped.wait(timeout=10), "поток B не подал сигнал о pop_context()"
            mgr.info("a-after-b-pop", module="ctx_test", thread_name="A")

        def thread_b() -> None:
            assert a_pushed.wait(timeout=10), "поток A не подал сигнал о push_context()"
            mgr.pop_context()  # у B собственный стек пуст — это "чужой" pop для A
            b_popped.set()

        t_a = threading.Thread(target=thread_a)
        t_b = threading.Thread(target=thread_b)
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)
        mgr.shutdown()

        assert not t_a.is_alive() and not t_b.is_alive(), "поток завис"
        matching = [r for r in tap.records if r["extra"].get("thread_name") == "A"]
        assert matching, "запись потока A не найдена в tap"
        assert matching[-1]["extra"].get("owner") == "A", (
            f"pop_context() в ЧУЖОМ потоке (B) стёр контекст потока A — запись: {matching[-1]}"
        )


class TestBaseContext:
    """Пункт 3 контракта — САМЫЙ ВАЖНЫЙ тест файла: процессный (base) слой
    обязан быть виден из воркер-потока, который сам ничего не пушил."""

    def test_set_base_context_visible_from_worker_thread(self) -> None:
        """Главный поток один раз выставляет set_base_context(proc_name=...)
        при старте процесса (реальный сценарий: ProcessModule кладёт своё
        имя процесса в лог-контекст на старте). Свежий воркер-поток, который
        НИКОГДА не вызывал push_context ни set_base_context, обязан всё
        равно видеть proc_name в своих записях.

        Наивный фикс "сделать push_context threading.local()" эту проверку
        завалит: base-слой должен жить отдельно от per-thread стека и быть
        общим для всех потоков процесса."""
        mgr = _make_logger("CtxBaseFromWorker")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        mgr.set_base_context(proc_name="proc_main")

        def worker() -> None:
            mgr.info("from worker", module="ctx_test", thread_name="worker")

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=10)
        mgr.shutdown()

        assert not t.is_alive(), "поток завис"
        matching = [r for r in tap.records if r["extra"].get("thread_name") == "worker"]
        assert matching, "запись воркер-потока не найдена в tap"
        assert matching[-1]["extra"].get("proc_name") == "proc_main", (
            f"base-контекст (set_base_context) не виден из воркер-потока — запись: {matching[-1]}"
        )


class TestContextPrecedence:
    """Пункт 4 контракта: log_context (ContextVar) < base_context <
    thread context (push_context) < явный extra= в вызове log(). Каждая
    смежная пара фиксируется отдельным тестом с конфликтующим ключом."""

    def test_precedence_base_context_overrides_log_context_var(self) -> None:
        mgr = _make_logger("CtxPrecedenceBaseOverVar")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        token = log_context.set({"env": "from_contextvar"})
        try:
            mgr.set_base_context(env="from_base")
            mgr.info("precedence-base-vs-var", module="ctx_test")
            rec = tap.records[-1]
            assert rec["extra"]["env"] == "from_base", f"base_context обязан перебивать module-level log_context: {rec}"
        finally:
            log_context.reset(token)
            mgr.shutdown()

    def test_precedence_thread_context_overrides_base_context(self) -> None:
        mgr = _make_logger("CtxPrecedenceThreadOverBase")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        mgr.set_base_context(env="from_base")
        mgr.push_context(env="from_thread")
        try:
            mgr.info("precedence-thread-vs-base", module="ctx_test")
            rec = tap.records[-1]
            assert rec["extra"]["env"] == "from_thread", f"push_context обязан перебивать set_base_context: {rec}"
        finally:
            mgr.pop_context()
            mgr.shutdown()

    def test_precedence_explicit_extra_overrides_thread_context(self) -> None:
        """Эта половина приоритета уже верна сегодня (extra= в вызове log()
        побеждает контекст) — тест фиксирует существующее поведение как
        регресс-страж, а не ожидается красным."""
        mgr = _make_logger("CtxPrecedenceExtraOverThread")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        mgr.push_context(env="from_thread")
        try:
            mgr.info("precedence-extra-vs-thread", module="ctx_test", env="from_explicit")
            rec = tap.records[-1]
            assert rec["extra"]["env"] == "from_explicit"
        finally:
            mgr.pop_context()
            mgr.shutdown()


class TestAsyncioTaskIsolation:
    """Пункт 5 контракта: если push_context хранится в ContextVar, то у
    asyncio-тасков (общий OS-поток, разные логические задачи) должна быть
    та же изоляция, что и у потоков. Если это НЕ так — тест не удалять,
    зафиксировать как отдельную находку в отчёте (см. инструкцию задачи)."""

    def test_asyncio_tasks_get_isolated_context(self) -> None:
        mgr = _make_logger("CtxAsyncioIsolation")
        tap = _ThreadSafeTap()
        mgr.add_tap(tap, min_level=LogLevel.DEBUG)

        async def task(marker: str) -> None:
            mgr.push_context(worker=marker)
            await asyncio.sleep(0)  # уступить цикл событий — окно для гонки
            mgr.info("tick-async", module="ctx_test_async", thread_name=marker)
            await asyncio.sleep(0)
            mgr.pop_context()

        async def main() -> None:
            await asyncio.gather(task("A"), task("B"))

        asyncio.run(main())
        mgr.shutdown()

        records = [r for r in tap.records if r["module"] == "ctx_test_async"]
        assert len(records) == 2
        mismatches = [r for r in records if r["extra"].get("worker") != r["extra"].get("thread_name")]
        assert not mismatches, f"контекст протёк между asyncio-тасками: {mismatches}"


class TestErrorManagerContextIsolationRegressionGuard:
    """Пункт 6 контракта: ErrorManager — брат LoggerManager, общий предок
    LoggerCore. Баг (и фикс) обязаны воспроизводиться одинаково."""

    def test_error_manager_thread_context_isolated_under_concurrent_load(self) -> None:
        """Тот же приём, что и в LoggerManager-версии
        (``TestThreadContextIsolation``): временно уменьшенный
        ``sys.setswitchinterval()`` заставляет интерпретатор чаще
        рассматривать переключение потоков, открывая окно гонки внутри
        push→error почти на каждой итерации — без этого короткая
        push→log→pop последовательность может уложиться в один тайм-слайс
        и тест окажется ложно-зелёным."""
        em = ErrorManager(config=None)
        em.initialize()
        tap = _ThreadSafeTap()
        em.add_tap(tap, min_level=LogLevel.DEBUG)

        barrier = threading.Barrier(2)
        iterations = 200

        def worker(marker: str) -> None:
            barrier.wait(timeout=10)
            for i in range(iterations):
                em.push_context(worker=marker, seq=i)
                em.error("tick", module="ctx_test_err", thread_name=marker)
                em.pop_context()

        original_interval = sys.getswitchinterval()
        sys.setswitchinterval(0.00005)
        try:
            t_a = threading.Thread(target=worker, args=("A",))
            t_b = threading.Thread(target=worker, args=("B",))
            t_a.start()
            t_b.start()
            t_a.join(timeout=30)
            t_b.join(timeout=30)
        finally:
            sys.setswitchinterval(original_interval)
        em.shutdown()

        assert not t_a.is_alive() and not t_b.is_alive(), "поток завис"
        # Фильтр по module: shutdown()/внутренние WARNING про нерезолвленные
        # каналы (см. captured log) тоже уходят в tap с порогом DEBUG — это
        # не сигнал теста, отсекаем по имени модуля.
        records = [r for r in tap.records if r["module"] == "ctx_test_err"]
        assert len(records) == 2 * iterations

        mismatches = [r for r in records if r["extra"].get("worker") != r["extra"].get("thread_name")]
        assert not mismatches, (
            f"ErrorManager: контекст протёк между потоками: "
            f"{len(mismatches)}/{len(records)} записей несут чужой worker; "
            f"пример: {mismatches[0]}"
        )
