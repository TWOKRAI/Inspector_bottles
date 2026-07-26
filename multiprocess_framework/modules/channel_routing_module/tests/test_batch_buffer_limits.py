# -*- coding: utf-8 -*-
"""Потолок пачки и учёт потерь в BatchBuffer (задача Ф0.3 плана
``observability-unified-routing``).

Болезнь: у ``BatchBuffer`` не было потолка вообще. Медленный сток (диск под
нагрузкой, зависший stdout, канал под удержанным локом) заставлял deque расти
без предела — процесс тихо съедал память, а плоскость, которая должна была об
этом сказать, сама и была причиной. Потери при этом не считались никак.

Лечение: ``max_pending`` на канал + политика переполнения + ``dropped`` /
``dropped_by_channel`` в stats, с именем канала-виновника.

Каждая пара ниже устроена одинаково: сначала показано поведение БЕЗ потолка
(``max_pending=0`` — ровно то, что было до Ф0.3), затем то же самое с потолком.
"""

from __future__ import annotations

import threading

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


# ====================================================================== #
#  Пара 1 — память ограничена                                             #
# ====================================================================== #


class TestPendingIsBounded:
    def test_without_limit_pending_grows_unbounded(self) -> None:
        """Болезнь: до Ф0.3 потолка не было — deque растёт на сколько положат."""
        cfg = _never_flushes()
        cfg.max_pending = 0  # 0 = «без потолка», поведение до Ф0.3
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        for i in range(5_000):
            buf.enqueue("slow", {"n": i})

        assert buf.stats["pending"]["slow"] == 5_000
        assert buf.stats["dropped"] == 0

    def test_with_limit_pending_never_exceeds_max_pending(self) -> None:
        """Лечение: сколько бы ни клали, в памяти висит не больше потолка."""
        cfg = _never_flushes()
        cfg.max_pending = 100
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        for i in range(5_000):
            buf.enqueue("slow", {"n": i})

        assert buf.stats["pending"]["slow"] == 100
        assert buf.stats["dropped"] == 4_900


# ====================================================================== #
#  Пара 2 — потеря названа, а не молчалива                                #
# ====================================================================== #


class TestDropIsVisible:
    def test_dropped_by_channel_names_the_guilty_channel(self) -> None:
        """Счётчик указывает КАКОЙ сток тормозит — иначе сигнал бесполезен."""
        cfg = _never_flushes()
        cfg.max_pending = 3
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        for i in range(10):
            buf.enqueue("slow", {"n": i})
        for i in range(2):
            buf.enqueue("healthy", {"n": i})

        dropped = buf.stats["dropped_by_channel"]
        assert dropped == {"slow": 7}
        assert "healthy" not in dropped
        assert buf.stats["pending"]["healthy"] == 2

    def test_limit_and_policy_are_published_with_the_counter(self) -> None:
        """Число потерь без потолка, к которому оно относится, не читается."""
        cfg = _never_flushes()
        cfg.max_pending = 7
        cfg.overflow_policy = OVERFLOW_DROP_NEWEST
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        stats = buf.stats
        assert stats["max_pending"] == 7
        assert stats["overflow_policy"] == OVERFLOW_DROP_NEWEST

    def test_dropped_by_channel_is_a_snapshot_not_a_live_reference(self) -> None:
        """stats отдаёт копию: потребитель не должен видеть мутации задним числом."""
        cfg = _never_flushes()
        cfg.max_pending = 1
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        buf.enqueue("ch", {"n": 0})
        buf.enqueue("ch", {"n": 1})
        snapshot = buf.stats["dropped_by_channel"]
        assert snapshot == {"ch": 1}

        buf.enqueue("ch", {"n": 2})
        assert snapshot == {"ch": 1}, "снимок изменился задним числом"
        assert buf.stats["dropped_by_channel"] == {"ch": 2}


# ====================================================================== #
#  Политики переполнения — что именно теряется                            #
# ====================================================================== #


class TestOverflowPolicy:
    def test_drop_oldest_keeps_the_records_closest_to_now(self) -> None:
        """Кольцо: ближний к падению контекст важнее давнего."""
        cfg = _never_flushes()
        cfg.max_pending = 3
        cfg.overflow_policy = OVERFLOW_DROP_OLDEST
        flushed: list = []
        buf = BatchBuffer(flush_fn=lambda ch, batch: flushed.extend(batch), config=cfg)

        for i in range(6):
            buf.enqueue("ch", {"n": i})
        buf.flush("ch")

        assert [r["n"] for r in flushed] == [3, 4, 5]

    def test_drop_newest_keeps_the_earliest_records(self) -> None:
        """Обратная политика: пачка замораживается, новое не принимается."""
        cfg = _never_flushes()
        cfg.max_pending = 3
        cfg.overflow_policy = OVERFLOW_DROP_NEWEST
        flushed: list = []
        buf = BatchBuffer(flush_fn=lambda ch, batch: flushed.extend(batch), config=cfg)

        for i in range(6):
            buf.enqueue("ch", {"n": i})
        buf.flush("ch")

        assert [r["n"] for r in flushed] == [0, 1, 2]

    def test_unknown_policy_fails_at_construction_not_at_overflow(self) -> None:
        """Опечатка в политике обязана падать сразу, а не на первом переполнении."""
        cfg = _never_flushes()
        cfg.overflow_policy = "drop_middle"
        with pytest.raises(ValueError, match="overflow_policy"):
            BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)


# ====================================================================== #
#  Инвариант учёта                                                        #
# ====================================================================== #


class TestAccountingInvariant:
    def test_nothing_disappears_from_the_books(self) -> None:
        """total_enqueued == total_flushed + Σ pending + dropped.

        Иначе счётчик потерь нельзя использовать как ответ на вопрос
        «а всё ли записалось» — часть записей терялась бы вне учёта.

        Сценарий намеренно проходит через все три исхода записи: часть уходит
        в сток (явный flush), часть висит в pending, часть потеряна потолком.
        """
        cfg = _never_flushes()
        cfg.max_pending = 25
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        for i in range(30):  # 25 осядут, 5 вытеснятся
            buf.enqueue("a", {"n": i})
        buf.flush("a")  # 25 уходят в сток
        for i in range(30):  # ещё 25 осядут, ещё 5 вытеснятся
            buf.enqueue("a", {"n": i})

        stats = buf.stats
        pending_total = sum(stats["pending"].values())
        assert stats["total_enqueued"] == 60
        assert stats["total_flushed"] == 25
        assert pending_total == 25
        assert stats["dropped"] == 10
        assert stats["total_enqueued"] == stats["total_flushed"] + pending_total + stats["dropped"]

    def test_invariant_holds_under_concurrent_writers(self) -> None:
        """Учёт не рассыпается при конкурентных enqueue из нескольких потоков."""
        cfg = BatchConfig(max_size=50, flush_interval=3600.0, max_pending=40)
        buf = BatchBuffer(flush_fn=lambda ch, batch: None, config=cfg)

        def _writer(tag: int) -> None:
            for i in range(500):
                buf.enqueue("shared", {"t": tag, "n": i})

        threads = [threading.Thread(target=_writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = buf.stats
        pending_total = sum(stats["pending"].values())
        assert stats["total_enqueued"] == 4 * 500
        assert stats["total_enqueued"] == stats["total_flushed"] + pending_total + stats["dropped"]


# ====================================================================== #
#  Совместимость: потолок не мешает штатной работе                        #
# ====================================================================== #


class TestDefaultBehaviourUnchanged:
    def test_default_limit_does_not_drop_on_normal_load(self) -> None:
        """Дефолтный потолок заведомо выше рабочей пачки — потерь быть не должно."""
        buf = BatchBuffer(flush_fn=lambda ch, batch: None)  # дефолтный BatchConfig

        for i in range(1_000):
            buf.enqueue("ch", {"n": i})

        assert buf.stats["dropped"] == 0
        assert buf.stats["dropped_by_channel"] == {}

    def test_slow_sink_does_not_lose_the_batch_being_flushed(self) -> None:
        """Записи, уже отданные в flush_fn, потолком не затрагиваются.

        Пачка извлекается из deque ДО вызова flush_fn (вне lock-а), поэтому
        медленный сток не приводит к тому, что переполнение съест то, что
        уже находится в пути на диск. Это и есть главный сценарий Ф0.3:
        сток встал, а писать в него продолжают.
        """
        cfg = _never_flushes()
        cfg.max_pending = 5
        started = threading.Event()
        release = threading.Event()
        flushed: list = []

        def _slow_flush(ch: str, batch: list) -> None:
            started.set()
            release.wait(timeout=5.0)
            flushed.extend(batch)

        buf = BatchBuffer(flush_fn=_slow_flush, config=cfg)
        for i in range(5):
            buf.enqueue("ch", {"n": i})

        # Сток "залипает" на этой пачке в отдельном потоке.
        drainer = threading.Thread(target=lambda: buf.flush("ch"))
        drainer.start()
        assert started.wait(timeout=5.0), "flush_fn не был вызван"

        # Пока сток занят — пишем ещё, переполняя буфер.
        for i in range(100, 200):
            buf.enqueue("ch", {"n": i})

        release.set()
        drainer.join(timeout=5.0)

        assert [r["n"] for r in flushed] == [0, 1, 2, 3, 4], "пачка в пути пострадала от вытеснения"
        assert buf.stats["dropped"] == 95
        assert buf.stats["pending"]["ch"] == 5
