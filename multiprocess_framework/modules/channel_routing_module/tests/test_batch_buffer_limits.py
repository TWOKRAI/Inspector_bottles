# -*- coding: utf-8 -*-
"""Потолок пачки и учёт потерь в BatchBuffer (задача Ф0.3 плана
``observability-unified-routing``).

Болезнь. Буфер был безлимитным, но росла память НЕ там, где казалось: deque
держит триггер ``max_size``, а вот число пачек «в полёте» не держало ничто —
медленный сток не мешал каждому следующему потоку начать СВОЙ сброс. Потери
при этом не считались никак, а `total_flushed` означал «отдано в сток», а не
«записано»: при мёртвом приёмнике счётчики рапортовали здоровую плоскость.

Лечение (двойное):
  1. ``_in_flight`` — один сбрасывающий поток на канал;
  2. ``max_pending`` + политика переполнения, срабатывающие ТОЛЬКО пока сток
     занят: при свободном стоке переполнение лечится сбросом, а не потерей.

Плюс контракт ``flush_fn``: возврат int = сколько записей сток реально принял.

Пары ниже устроены одинаково: сначала показано поведение БЕЗ потолка
(``max_pending=0`` — ровно то, что было до Ф0.3), затем то же с потолком.
"""

from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import pytest

from multiprocess_framework.modules.channel_routing_module.buffers.batch_buffer import (
    OVERFLOW_DROP_NEWEST,
    OVERFLOW_DROP_OLDEST,
    BatchBuffer,
    BatchConfig,
)


def _never_flushes() -> BatchConfig:
    """Конфиг, при котором пачка не сбрасывается сама: только накапливается.

    ``max_size`` заведомо больше числа записей в тестах, ``flush_interval``
    больше длительности теста — так изолируется именно рост pending.
    """
    return BatchConfig(max_size=10_000, flush_interval=3600.0)


class _StuckSink:
    """Сток, который «залип» на первой пачке — модель медленного приёмника.

    Именно этот сценарий описан в приёмке задачи: «медленный сток → счётчик
    растёт, память ограничена». Держит поток внутри ``flush_fn``, пока тест не
    отпустит, и запоминает, что успело уйти.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.written: List[dict] = []
        self.batches: List[int] = []

    def __call__(self, channel: str, batch: List[dict]) -> int:
        self.entered.set()
        self.release.wait(timeout=10.0)
        self.written.extend(batch)
        self.batches.append(len(batch))
        return len(batch)


def _stick_sink(buf: BatchBuffer, sink: _StuckSink, channel: str = "ch") -> threading.Thread:
    """Занять сток канала в отдельном потоке и дождаться входа в flush_fn."""
    drainer = threading.Thread(target=lambda: buf.flush(channel), name="drainer")
    drainer.start()
    assert sink.entered.wait(timeout=10.0), "flush_fn не был вызван — сток не занят"
    return drainer


# ====================================================================== #
#  Пара 1 — память ограничена, пока сток не справляется                   #
# ====================================================================== #


class TestPendingIsBoundedWhileSinkIsBusy:
    def test_without_limit_pending_grows_unbounded(self) -> None:
        """Болезнь: до Ф0.3 потолка не было — deque растёт на сколько положат."""
        cfg = _never_flushes()
        cfg.max_pending = 0  # 0 = «без потолка», поведение до Ф0.3
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("ch", {"n": -1})
        drainer = _stick_sink(buf, sink)
        try:
            for i in range(5_000):
                buf.enqueue("ch", {"n": i})
            assert buf.stats["pending"]["ch"] == 5_000
            assert buf.stats["dropped"] == 0
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)

    def test_with_limit_pending_never_exceeds_max_pending(self) -> None:
        """Лечение: сколько бы ни клали при занятом стоке, в памяти висит потолок."""
        cfg = _never_flushes()
        cfg.max_pending = 100
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("ch", {"n": -1})
        drainer = _stick_sink(buf, sink)
        try:
            for i in range(5_000):
                buf.enqueue("ch", {"n": i})
            stats = buf.stats
            assert stats["pending"]["ch"] == 100
            assert stats["dropped"] == 4_900
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)


# ====================================================================== #
#  Здоровый сток потерь не даёт — даже при потолке ниже пачки             #
# ====================================================================== #


class TestHealthySinkNeverDrops:
    @pytest.mark.parametrize("policy", [OVERFLOW_DROP_OLDEST, OVERFLOW_DROP_NEWEST])
    def test_no_drops_when_sink_keeps_up(self, policy: str) -> None:
        """Ключевое свойство: потолок ниже ``max_size`` НЕ превращает батчинг в сэмплирование.

        Первая редакция Ф0.3 роняла здесь 90% записей при полностью исправном
        стоке — потолок применялся безусловно, а не по признаку «сток занят».
        """
        cfg = BatchConfig(max_size=1_000, flush_interval=3600.0, max_pending=5)
        cfg.overflow_policy = policy
        received: List[dict] = []

        def _fast_sink(channel: str, batch: List[dict]) -> int:
            received.extend(batch)
            return len(batch)

        buf = BatchBuffer(flush_fn=_fast_sink, config=cfg)
        for i in range(500):
            buf.enqueue("ch", {"n": i})
        buf.flush("ch")

        assert buf.stats["dropped"] == 0
        assert [r["n"] for r in received] == list(range(500))

    def test_default_layout_does_not_drop(self) -> None:
        """Дефолтная раскладка логгера (max_pending 10k > batch_size 100) — без потерь."""
        buf = BatchBuffer(flush_fn=lambda ch, batch: len(batch))

        for i in range(16_000):
            buf.enqueue("ch", {"n": i})

        assert buf.stats["dropped"] == 0
        assert buf.stats["dropped_by_channel"] == {}


# ====================================================================== #
#  Один сбрасывающий поток на канал                                       #
# ====================================================================== #


class TestSingleFlusherPerChannel:
    def test_in_flight_is_published_and_blocks_parallel_flush(self) -> None:
        """Иначе память росла бы в пачках «в полёте», которых потолок не касается."""
        cfg = _never_flushes()
        cfg.max_pending = 10_000
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("ch", {"n": 0})
        drainer = _stick_sink(buf, sink)
        try:
            assert buf.stats["in_flight"] == ["ch"]

            buf.enqueue("ch", {"n": 1})
            buf.flush("ch")  # попытка параллельного сброса
            stats = buf.stats
            assert stats["flush_skipped_busy"] >= 1
            assert stats["total_batches"] == 1, "начался второй параллельный сброс"
            assert stats["pending"]["ch"] == 1
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)
        assert buf.stats["in_flight"] == []


# ====================================================================== #
#  Потеря названа, а не молчалива                                         #
# ====================================================================== #


class TestDropIsVisible:
    def test_dropped_by_channel_names_the_guilty_channel(self) -> None:
        """Счётчик указывает КАКОЙ сток тормозит — иначе сигнал бесполезен."""
        cfg = _never_flushes()
        cfg.max_pending = 3
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("slow", {"n": -1})
        drainer = _stick_sink(buf, sink, "slow")
        try:
            for i in range(10):
                buf.enqueue("slow", {"n": i})
            for i in range(2):
                buf.enqueue("healthy", {"n": i})

            dropped = buf.stats["dropped_by_channel"]
            assert dropped == {"slow": 7}
            assert "healthy" not in dropped
            assert buf.stats["pending"]["healthy"] == 2
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)

    def test_limit_and_policy_are_published_with_the_counter(self) -> None:
        """Число потерь без потолка, к которому оно относится, не читается."""
        cfg = _never_flushes()
        cfg.max_pending = 7
        cfg.overflow_policy = OVERFLOW_DROP_NEWEST
        buf = BatchBuffer(flush_fn=lambda ch, batch: len(batch), config=cfg)

        stats = buf.stats
        assert stats["max_pending"] == 7
        assert stats["overflow_policy"] == OVERFLOW_DROP_NEWEST

    def test_stats_is_a_snapshot_not_a_live_reference(self) -> None:
        """stats отдаёт копию: потребитель не должен видеть мутации задним числом."""
        cfg = _never_flushes()
        cfg.max_pending = 1
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("ch", {"n": -1})
        drainer = _stick_sink(buf, sink)
        try:
            buf.enqueue("ch", {"n": 0})
            buf.enqueue("ch", {"n": 1})
            snapshot = buf.stats["dropped_by_channel"]
            assert snapshot == {"ch": 1}

            buf.enqueue("ch", {"n": 2})
            assert snapshot == {"ch": 1}, "снимок изменился задним числом"
            assert buf.stats["dropped_by_channel"] == {"ch": 2}
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)

    def test_counters_in_stats_are_coherent(self) -> None:
        """Все счётчики читаются под ОДНИМ локом — инвариант опубликован наружу.

        Рваный снимок давал бы ``dropped != sum(dropped_by_channel)`` на здоровом
        процессе, а по этому инварианту теперь судят через introspect.observability.
        """
        cfg = _never_flushes()
        cfg.max_pending = 4
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("a", {"n": -1})
        drainer = _stick_sink(buf, sink, "a")
        stop = threading.Event()

        def _writer() -> None:
            i = 0
            while not stop.is_set():
                buf.enqueue("a", {"n": i})
                i += 1

        writers = [threading.Thread(target=_writer) for _ in range(3)]
        for t in writers:
            t.start()
        try:
            for _ in range(50):
                stats = buf.stats
                assert stats["dropped"] == sum(stats["dropped_by_channel"].values())
        finally:
            stop.set()
            for t in writers:
                t.join(timeout=10.0)
            sink.release.set()
            drainer.join(timeout=10.0)


# ====================================================================== #
#  Политики переполнения — что именно теряется                            #
# ====================================================================== #


class TestOverflowPolicy:
    def _overflow(self, policy: str) -> Tuple[BatchBuffer, _StuckSink, threading.Thread]:
        cfg = _never_flushes()
        cfg.max_pending = 3
        cfg.overflow_policy = policy
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)
        buf.enqueue("ch", {"n": -1})
        drainer = _stick_sink(buf, sink)
        for i in range(6):
            buf.enqueue("ch", {"n": i})
        return buf, sink, drainer

    def test_drop_oldest_keeps_the_records_closest_to_now(self) -> None:
        """Кольцо: ближний к падению контекст важнее давнего."""
        buf, sink, drainer = self._overflow(OVERFLOW_DROP_OLDEST)
        sink.release.set()
        drainer.join(timeout=10.0)
        buf.flush("ch")

        tail = [r["n"] for r in sink.written if r["n"] >= 0]
        assert tail == [3, 4, 5]

    def test_drop_newest_keeps_the_earliest_records(self) -> None:
        """Обратная политика: пачка замораживается, новое не принимается."""
        buf, sink, drainer = self._overflow(OVERFLOW_DROP_NEWEST)
        sink.release.set()
        drainer.join(timeout=10.0)
        buf.flush("ch")

        tail = [r["n"] for r in sink.written if r["n"] >= 0]
        assert tail == [0, 1, 2]

    def test_drop_newest_recovers_after_the_sink_frees_up(self) -> None:
        """Регресс: ранний return из-под лока пропускал расчёт триггеров.

        Симптом первой редакции: канал с ``drop_newest``, однажды упёршийся в
        потолок, переставал сбрасываться НАВСЕГДА. Сток уже освободился, но
        каждая следующая запись отвергалась потолком и выходила из метода до
        расчёта триггеров — сброс не назначался никогда, и пачка оставалась
        запертой в памяти при полностью исправном приёмнике.
        """
        cfg = _never_flushes()
        cfg.max_pending = 5
        cfg.overflow_policy = OVERFLOW_DROP_NEWEST
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("ch", {"n": -1})
        drainer = _stick_sink(buf, sink)
        for i in range(20):  # упираемся в потолок, пока сток занят
            buf.enqueue("ch", {"n": i})
        assert buf.stats["pending"]["ch"] == 5
        assert buf.stats["dropped"] == 15

        sink.release.set()  # сток освободился
        drainer.join(timeout=10.0)

        buf.enqueue("ch", {"n": 100})  # обычная запись после разблокировки

        stats = buf.stats
        assert stats["total_batches"] >= 2, "канал заклинило: сток свободен, а сброса нет"
        assert stats["pending"]["ch"] == 0
        assert {r["n"] for r in sink.written} >= {0, 1, 2, 3, 4, 100}

    def test_unknown_policy_fails_at_construction_not_at_overflow(self) -> None:
        """Опечатка в политике обязана падать сразу, а не на первом переполнении."""
        cfg = _never_flushes()
        cfg.overflow_policy = "drop_middle"
        with pytest.raises(ValueError, match="overflow_policy"):
            BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)


# ====================================================================== #
#  Сток не принял — это не «доставлено»                                   #
# ====================================================================== #


class TestFlushFailedAccounting:
    def test_sink_reporting_zero_is_not_counted_as_delivered(self) -> None:
        """Главная находка ревью: `total_flushed` означал «отдано», не «записано».

        Сток, который ничего не принял (канала нет, write упал), давал
        `total_flushed=N` и `dropped=0` при нуле байт на диске.
        """
        cfg = _never_flushes()
        buf = BatchBuffer(flush_fn=lambda ch, batch: 0, config=cfg)

        for i in range(10):
            buf.enqueue("dead", {"n": i})
        buf.flush("dead")

        stats = buf.stats
        assert stats["total_flushed"] == 0
        assert stats["flush_failed"] == 10
        assert stats["flush_failed_by_channel"] == {"dead": 10}

    def test_partial_acceptance_is_split_honestly(self) -> None:
        cfg = _never_flushes()
        buf = BatchBuffer(flush_fn=lambda ch, batch: len(batch) // 2, config=cfg)

        for i in range(10):
            buf.enqueue("half", {"n": i})
        buf.flush("half")

        stats = buf.stats
        assert stats["total_flushed"] == 5
        assert stats["flush_failed"] == 5

    def test_raising_sink_loses_the_whole_batch(self) -> None:
        cfg = _never_flushes()

        def _boom(channel: str, batch: List[dict]) -> int:
            raise RuntimeError("сток упал")

        buf = BatchBuffer(flush_fn=_boom, config=cfg)
        for i in range(4):
            buf.enqueue("ch", {"n": i})
        buf.flush("ch")

        stats = buf.stats
        assert stats["errors"] == 1
        assert stats["total_flushed"] == 0
        assert stats["flush_failed"] == 4

    def test_silent_sink_keeps_the_old_contract(self) -> None:
        """flush_fn без возврата (None) — прежний контракт, пачка считается доставленной."""
        cfg = _never_flushes()
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        for i in range(6):
            buf.enqueue("ch", {"n": i})
        buf.flush("ch")

        stats = buf.stats
        assert stats["total_flushed"] == 6
        assert stats["flush_failed"] == 0


# ====================================================================== #
#  Инвариант учёта                                                        #
# ====================================================================== #


def _assert_books_balance(stats: dict) -> None:
    pending_total = sum(stats["pending"].values())
    assert stats["total_enqueued"] == (
        stats["total_flushed"] + pending_total + stats["dropped"] + stats["flush_failed"] + stats["in_flight_records"]
    ), f"книги не сходятся: {stats}"


class TestAccountingInvariant:
    def test_nothing_disappears_from_the_books(self) -> None:
        """total_enqueued == total_flushed + Σ pending + dropped + flush_failed.

        Сценарий намеренно проходит через все исходы: доставлено, висит в
        pending, потеряно потолком, не принято стоком.
        """
        cfg = _never_flushes()
        cfg.max_pending = 25
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        buf.enqueue("a", {"n": -1})
        drainer = _stick_sink(buf, sink, "a")
        try:
            for i in range(30):  # 25 осядут, 5 вытеснятся
                buf.enqueue("a", {"n": i})
            _assert_books_balance(buf.stats)
            assert buf.stats["dropped"] == 5
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)

        buf.flush("a")
        stats = buf.stats
        _assert_books_balance(stats)
        assert stats["total_flushed"] == 26  # 1 в первой пачке + 25 во второй

    def test_invariant_holds_under_concurrent_writers_and_flushes(self) -> None:
        """Гонка enqueue ↔ flush: ради неё инвариант и написан.

        Первая редакция теста ставила ``max_pending < max_size`` при
        ``flush_interval=3600`` и без ``start()`` — сброс не происходил ни разу,
        `total_flushed` был константным нулём, и гонка не проверялась вовсе.
        """
        cfg = BatchConfig(max_size=50, flush_interval=3600.0, max_pending=500)
        flushed_batches: List[int] = []
        lock = threading.Lock()

        def _sink(channel: str, batch: List[dict]) -> int:
            with lock:
                flushed_batches.append(len(batch))
            return len(batch)

        buf = BatchBuffer(flush_fn=_sink, config=cfg)
        stop = threading.Event()

        def _writer(tag: int) -> None:
            for i in range(500):
                buf.enqueue("shared", {"t": tag, "n": i})

        def _flusher() -> None:
            while not stop.is_set():
                buf.flush("shared")

        writers = [threading.Thread(target=_writer, args=(t,)) for t in range(4)]
        flusher = threading.Thread(target=_flusher)
        flusher.start()
        for t in writers:
            t.start()
        for t in writers:
            t.join(timeout=30.0)
        stop.set()
        flusher.join(timeout=30.0)
        buf.flush("shared")

        stats = buf.stats
        assert stats["total_enqueued"] == 4 * 500
        assert stats["total_batches"] > 0, "ни одного сброса — гонка не воспроизведена"
        _assert_books_balance(stats)


# ====================================================================== #
#  Совместимость                                                          #
# ====================================================================== #


class TestDefaultBehaviourUnchanged:
    def test_batch_in_flight_is_not_touched_by_overflow(self) -> None:
        """Записи, уже отданные в flush_fn, потолком не затрагиваются."""
        cfg = _never_flushes()
        cfg.max_pending = 5
        sink = _StuckSink()
        buf = BatchBuffer(flush_fn=sink, config=cfg)

        for i in range(5):
            buf.enqueue("ch", {"n": i})
        drainer = _stick_sink(buf, sink)
        try:
            for i in range(100, 200):
                buf.enqueue("ch", {"n": i})
        finally:
            sink.release.set()
            drainer.join(timeout=10.0)

        assert [r["n"] for r in sink.written] == [0, 1, 2, 3, 4], "пачка в пути пострадала"
        assert buf.stats["dropped"] == 95
        assert buf.stats["pending"]["ch"] == 5

    def test_stop_drains_what_is_left(self) -> None:
        received: List[dict] = []
        buf = BatchBuffer(
            flush_fn=lambda ch, batch: (received.extend(batch), len(batch))[1],
            config=BatchConfig(max_size=1_000, flush_interval=3600.0),
        )
        buf.start()
        for i in range(7):
            buf.enqueue("ch", {"n": i})
        buf.stop()

        assert len(received) == 7
        assert buf.stats["pending"]["ch"] == 0


def test_flush_fn_signature_is_documented_as_optional_int() -> None:
    """Контракт возврата — часть публичного поведения, а не деталь."""
    doc: Optional[str] = BatchBuffer._flush_channel.__doc__
    assert doc is not None
    assert "int" in doc and "None" in doc
