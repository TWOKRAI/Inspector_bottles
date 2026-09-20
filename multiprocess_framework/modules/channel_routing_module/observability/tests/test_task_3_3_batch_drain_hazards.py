# -*- coding: utf-8 -*-
"""Hazard-тесты АВТОРА к Task 3.3 — то, что видно только изнутри механизма.

Приёмочный набор слепого тестера (``test_task_3_3_store_tap_batch_acceptance.py``)
проверяет КОНТРАКТ: пара ``flush``, имя счётчика параметром, голос окном, класс
без знания о сторе. Здесь — опасные места самого механизма, о которых из
критериев приёмки не догадаться, потому что они следуют из УСТРОЙСТВА:

* критическая секция ``drain()`` — свойство ЛОКА, а не латентности; латентностью
  из Python оно не меряется вовсе (см. докстринг класса ниже);
* порядок записей, когда пачек несколько, а писателей — два;
* живучесть потока дренажа после отказа стока (мёртвый поток не жалуется —
  он просто перестаёт разгребать, и очередь молча переполняется);
* реентрантность: отказ стока выпускает ГОЛОС, а голос в проде уезжает в тот же
  логгер, на котором висит tap, — то есть обратно в ``write()`` того же воркера;
* потолок, переживший подмену дека (``maxlen`` — единственное, что делает
  ``drop_oldest`` вытеснением, а не ростом);
* инвариант «принято = записано + потеряно» под конкуренцией и на аварийном
  закрытии.

Дисциплина: всё, что способно заблокироваться, — в демон-потоке с дедлайном
``join``; тест, который ВИСИТ вместо падения, хуже отсутствующего.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.observability import (
    DROP_OLDEST,
    BatchDrainWorker,
    BoundedChannel,
)

JOIN_DEADLINE = 5.0


def _rec(i: int) -> Dict[str, Any]:
    return {"n": i, "message": "x" * 32}


class _CollectingSink:
    """Сток, помнящий ПАЧКИ (а не только записи) — порядок проверяется по ним."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.batches: List[List[Dict[str, Any]]] = []

    def append_records(self, records: List[Dict[str, Any]]) -> int:
        with self._lock:
            self.batches.append(list(records))
        return len(records)

    @property
    def flat(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [r for batch in self.batches for r in batch]


# ---------------------------------------------------------------------------
# Копия буфера вышла ИЗ-ПОД лока — свойство конструкции, без порога времени
# ---------------------------------------------------------------------------


class _BlockingDeque(deque):
    """Дек, чьё КОПИРОВАНИЕ (``__iter__``) останавливается по требованию теста.

    Ключ к детерминизму. Прежняя редакция ``drain()`` звала ``list(self._buffer)``
    ПОД локом, новая — подменяет дек под локом и копирует снаружи. Разница — в
    том, держится ли лок во время копирования, и порогом времени это НЕ
    проверяется: сквозная латентность постановки у обеих редакций одинакова
    (см. докстринг метода К-Т1(б) приёмочного набора — наблюдаемой разницы не
    нашлось ни в одном прогоне с достаточным числом повторов).

    Здесь копирование останавливается явно, и вопрос становится булевым:
    успевает ли ``write()`` пройти, пока копия ещё не сделана. Это утверждение
    о ГРАНИЦЕ критической секции, а не о скорости.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()

    def __iter__(self):  # noqa: D105 — поведение описано в докстринге класса
        self.entered.set()
        self.release.wait(timeout=JOIN_DEADLINE)
        return super().__iter__()


def test_drain_does_not_hold_the_lock_while_copying_the_buffer() -> None:
    """Пока ``drain()`` копирует буфер, ``write()`` не ждёт лока.

    Сломается ровно на редакции с копией внутри ``with self._lock``: писатель
    уснёт на локе до конца копии, и его завершения тест не дождётся. Сторож
    свойства конструкции, а не измеренной регрессии.
    """
    ch = BoundedChannel("hazard_d1", capacity=1024, overflow=DROP_OLDEST)
    slow: _BlockingDeque = _BlockingDeque(maxlen=1024)
    for i in range(64):
        slow.append(_rec(i))
    ch._buffer = slow  # белый ящик намеренно: предмет — дисциплина лока

    drained: List[Any] = []
    write_done = threading.Event()
    errors: List[str] = []

    def drainer() -> None:
        try:
            drained.append(ch.drain())
        except Exception as exc:
            errors.append(repr(exc))

    def writer() -> None:
        try:
            assert slow.entered.wait(timeout=JOIN_DEADLINE), "копирование буфера не началось"
            ch.write(_rec(999))
            write_done.set()
        except Exception as exc:
            errors.append(repr(exc))

    t_d = threading.Thread(target=drainer, daemon=True)
    t_w = threading.Thread(target=writer, daemon=True)
    t_d.start()
    t_w.start()

    # Главное утверждение: постановка прошла ДО того, как копию отпустили.
    put_passed = write_done.wait(timeout=2.0)
    slow.release.set()
    t_w.join(timeout=JOIN_DEADLINE)
    t_d.join(timeout=JOIN_DEADLINE)

    assert not errors, f"поток бросил исключение вместо чистого прогона: {errors}"
    assert not t_w.is_alive() and not t_d.is_alive(), "поток завис — обнаружено явно, а не таймаутом снаружи"
    assert put_passed, (
        "write() не прошёл, пока drain() копировал буфер — значит копия делается ПОД локом "
        "критическая секция стала O(ёмкость), и постановка ждёт слива"
    )
    assert drained and len(drained[0]) == 64, f"дренаж потерял записи: {drained!r}"


def test_the_swapped_deque_keeps_its_maxlen_so_the_ceiling_survives_a_drain() -> None:
    """Подмена дека обязана нести ``maxlen`` — иначе потолок становится декоративным.

    Наиболее вероятная ошибка при подмене дека: создать ``deque()`` без ``maxlen``.
    Тогда ПЕРВЫЙ же слив снимает потолок, очередь растёт неограниченно, а
    счётчик вытеснений замирает на нуле — то есть память течёт МОЛЧА.
    """
    ch = BoundedChannel("hazard_maxlen", capacity=4, overflow=DROP_OLDEST)
    for i in range(4):
        ch.write(_rec(i))
    assert len(ch.drain()) == 4

    for i in range(20):
        ch.write(_rec(100 + i))

    assert len(ch) == 4, f"после слива потолок 4 перестал действовать: глубина {len(ch)}"
    assert ch.dropped == 16, f"вытеснения после слива не считаются: dropped={ch.dropped}"


# ---------------------------------------------------------------------------
# Д-2 / Д-3: аварийное закрытие и атомарность снимка
# ---------------------------------------------------------------------------


def test_close_counts_the_remainder_as_loss_instead_of_dropping_it_silently() -> None:
    """Д-2: ``принято == отдано + потеряно`` держится и на пути БЕЗ ``drain()``."""
    ch = BoundedChannel("hazard_d2", capacity=8, overflow=DROP_OLDEST)
    for i in range(10):
        ch.write(_rec(i))
    before = ch.get_info()
    assert (before["depth"], before["dropped"], before["written"]) == (8, 2, 10)

    ch.close()

    after = ch.get_info()
    assert after["depth"] == 0
    assert after["dropped"] == 10, (
        f"восемь принятых записей исчезли молча: dropped={after['dropped']} (ожидалось 2 вытеснения + 8 остатка)"
    )


class _HookedLock:
    """Обёртка над локом канала: делает ОДНУ запись сразу после его отпускания.

    Так окно между «отпустили лок» и «прочитали остальные числа» перестаёт быть
    вопросом везения. Прежняя редакция этого теста ловила расхождение живым
    писателем в 20 000 попыток — и инъекция (вернуть неатомарный ``get_info``)
    не убила её НИ РАЗУ: окно в два чтения атрибута GIL почти не даёт занять.
    Вакуумный сторож хуже отсутствующего, поэтому окно занимается принудительно.
    """

    def __init__(self, lock, on_release) -> None:
        self._lock = lock
        self._on_release = on_release
        self.armed = False

    def acquire(self, *a, **kw):
        return self._lock.acquire(*a, **kw)

    def release(self):
        return self._lock.release()

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *exc):
        result = self._lock.__exit__(*exc)
        if self.armed:
            self.armed = False  # ровно один раз: иначе рекурсия через write()
            self._on_release()
        return result


def test_get_info_reads_all_four_numbers_from_one_critical_section() -> None:
    """Д-3: снимок собран ПОД ОДНИМ локом — проверено занятым окном, не везением.

    Без ``drain()`` инвариант точный: ``depth == written - dropped``. Прежняя
    редакция читала ``depth`` под локом, а ``written``/``dropped`` уже после его
    отпускания — запись, попавшая ровно в это окно, делает снимок рваным, и
    всякий, кто сверяет по нему равенство литералом, видит «флак», а не дефект.
    """
    ch = BoundedChannel("hazard_d3", capacity=1024, overflow=DROP_OLDEST)
    for i in range(5):
        ch.write(_rec(i))

    hooked = _HookedLock(ch._lock, lambda: ch.write(_rec(999)))
    ch._lock = hooked  # белый ящик намеренно: предмет — граница критической секции
    hooked.armed = True

    info = ch.get_info()

    assert len(ch) == 6, "предусловие: запись в окне обязана была пройти"
    assert info["depth"] == info["written"] - info["dropped"], f"снимок рваный — числа сняты не под одним локом: {info}"
    assert (info["depth"], info["written"], info["dropped"]) == (5, 5, 0), (
        f"снимок обязан описывать ОДИН момент — состояние до записи в окне: {info}"
    )


# ---------------------------------------------------------------------------
# Порядок, живучесть потока, реентрантность
# ---------------------------------------------------------------------------


def test_records_reach_the_sink_in_write_order_across_several_batches() -> None:
    """Порядок записей журнала — свойство, которого от него ждут.

    Два писателя (фоновый поток и ``flush()`` вызывающего) ходят к стоку через
    один лок; сними его — пачки приедут вперемешку. Здесь один писатель и
    несколько пачек: проверяется склейка пачек, а не гонка.
    """
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 1024, counter_name="evicted", batch_size=10, flush_interval_sec=5.0)
    for i in range(95):
        w.write(_rec(i))
    written, lost = w.close()

    assert (written, lost) == (95, 0), f"written={written} lost={lost}"
    assert [r["n"] for r in sink.flat] == list(range(95)), "порядок записей нарушен"
    assert max(len(b) for b in sink.batches) <= 10, (
        f"пачка крупнее batch_size — одна транзакция стала неограниченной: {[len(b) for b in sink.batches]}"
    )


def test_a_failing_sink_does_not_kill_the_drain_thread() -> None:
    """Отказ стока не имеет права УБИТЬ поток дренажа.

    Мёртвый поток не жалуется: очередь просто перестаёт разгребаться, и через
    несколько секунд начинается тихое вытеснение. Это худший исход из всех, что
    может дать сток, — поэтому свойство проверяется отдельно от «потеря
    считается».
    """
    state = {"fail": True}

    class _FlakySink:
        def __init__(self) -> None:
            self.taken: List[Dict[str, Any]] = []

        def append_records(self, records: List[Dict[str, Any]]) -> int:
            if state["fail"]:
                raise RuntimeError("сток недоступен")
            self.taken.extend(records)
            return len(records)

    sink = _FlakySink()
    w = BatchDrainWorker(sink, 64, counter_name="evicted", batch_size=8, flush_interval_sec=0.02)
    for i in range(8):
        w.write(_rec(i))
    time.sleep(0.2)  # дать фоновому потоку упасть на отказе стока

    state["fail"] = False
    for i in range(100, 108):
        w.write(_rec(i))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not sink.taken:
        time.sleep(0.02)

    assert sink.taken, "поток дренажа умер на первом отказе стока: вторая партия не доехала"
    assert [r["n"] for r in sink.taken] == list(range(100, 108))
    written, lost = w.close()
    assert lost >= 8, f"первая партия обязана числиться потерянной, а не исчезнуть: lost={lost}"


def test_a_sink_that_writes_back_into_the_worker_does_not_deadlock() -> None:
    """Реентрантность: отказ стока выпускает ГОЛОС, а голос в проде — лог-запись.

    На боевой раскладке tap висит на том же ``LoggerManager``, в который уезжает
    голос: сток упал → голос → лог-запись → tap → ``worker.write()``. Если бы
    голос выпускался под локом стока или под локом счётчиков, это был бы
    дедлок на первом же отказе БД — то есть ровно в момент аварии.
    """
    worker_box: List[BatchDrainWorker] = []
    reentered = threading.Event()

    class _ReentrantSink:
        def append_records(self, records: List[Dict[str, Any]]) -> int:
            reentered.set()
            worker_box[0].write({"n": -1, "message": "запись из самого стока"})
            return len(records)

    w = BatchDrainWorker(_ReentrantSink(), 64, counter_name="evicted", flush_interval_sec=5.0)
    worker_box.append(w)
    w.write(_rec(1))

    done: List[Any] = []

    def call_flush() -> None:
        done.append(w.flush(timeout=2.0))

    t = threading.Thread(target=call_flush, daemon=True)
    t.start()
    t.join(timeout=JOIN_DEADLINE)

    assert not t.is_alive(), "flush() не вернулся — сток, пишущий обратно в воркер, встал дедлоком"
    assert reentered.is_set(), "предусловие: сток обязан был позвать write() воркера"
    assert done and done[0][0] >= 1, f"исход flush(): {done}"
    w.close()


def test_nothing_vanishes_under_concurrent_writers_and_an_immediate_close() -> None:
    """Инвариант «принято = записано + потеряно» на 4000 записях восьми потоков.

    **Гонки здесь НЕТ, и докстринг это признаёт (находка ревью).** Писатели
    дожидаются ``join``, и только потом зовётся ``close()`` — тест
    детерминирован и стережёт учёт при конкурентной ЗАПИСИ, а не при
    конкурентном останове. Останов посреди работы писателей проверяет
    ``test_nothing_vanishes_when_close_arrives_while_writers_are_still_running``
    ниже; прежняя редакция этого докстринга обещала гонку, которой в теле не
    было, — то есть девятый критерий на конкуренции не стерёг никто.
    """
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 512, counter_name="evicted", batch_size=32, flush_interval_sec=0.01)
    threads = 8
    per_thread = 500
    errors: List[str] = []
    start = threading.Barrier(threads)

    def writer(tid: int) -> None:
        try:
            start.wait(timeout=JOIN_DEADLINE)
            for i in range(per_thread):
                w.write({"n": tid * per_thread + i})
        except Exception as exc:
            errors.append(repr(exc))

    pool = [threading.Thread(target=writer, args=(t,), daemon=True) for t in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join(timeout=JOIN_DEADLINE)

    assert not errors, errors
    assert all(not t.is_alive() for t in pool), "писательский поток завис"

    written, lost = w.close()
    total = threads * per_thread
    assert written + lost == total, (
        f"принято {total}, а записано+потеряно = {written}+{lost} = {written + lost}: часть записей исчезла молча"
    )
    stored = sink.flat
    assert len(stored) == written, f"сток принял {len(stored)}, воркер насчитал {written}"
    assert len({r["n"] for r in stored}) == len(stored), "запись доехала до стока ДВАЖДЫ"


def test_write_after_close_is_counted_not_swallowed() -> None:
    """Запись, пришедшая ПОСЛЕ останова, — тоже потеря с именем.

    Гонка реальна: tap снимают в одном потоке, а эмитент в другом ещё живёт.
    """
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 64, counter_name="evicted", flush_interval_sec=5.0)
    w.write(_rec(1))
    written, lost = w.close()
    assert (written, lost) == (1, 0)

    result = w.write(_rec(2))
    assert result["status"] == "dropped", result
    assert w.counters()["evicted"] == 1, f"потеря после закрытия не сосчитана: {w.counters()}"
    assert w.totals() == (1, 1), f"итоги после записи в закрытый воркер: {w.totals()}"


def test_close_is_idempotent_and_does_not_double_count() -> None:
    """Повторный ``close()`` не имеет права ни удвоить итоги, ни зависнуть."""
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 64, counter_name="evicted", flush_interval_sec=5.0)
    for i in range(5):
        w.write(_rec(i))
    first = w.close()
    second = w.close()
    assert first == (5, 0), first
    assert second == first, f"второй close() изменил итоги: {first} → {second}"


@pytest.mark.parametrize("overflow", ["drop_oldest", "drop_newest"])
def test_the_invariant_holds_for_both_overflow_policies(overflow: str) -> None:
    """Обе политики переполнения обязаны считать одинаково честно.

    ``drop_newest`` отказывает В МОМЕНТ постановки (``written`` канала не
    растёт), ``drop_oldest`` вытесняет уже принятую. Формула итогов у них общая,
    и разъехаться ей нельзя — иначе одна из политик молча теряла бы разницу.
    """
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 8, counter_name="evicted", overflow=overflow, batch_size=64, flush_interval_sec=5.0)
    total = 50
    for i in range(total):
        w.write(_rec(i))
    written, lost = w.close()
    assert written + lost == total, f"{overflow}: принято {total}, учтено {written}+{lost}"
    assert len(sink.flat) == written


def test_flush_returns_at_the_deadline_when_the_sink_blocks_and_close_still_accounts() -> None:
    """Дедлайн ``flush`` обязан держаться и против ЗАВИСШЕГО стока, не только против падающего.

    Приёмочный набор проверяет недостижимый сток, который БРОСАЕТ, — очередь при
    этом пустеет мгновенно, и дедлайн не проверяется вовсе. Зависший сток (сеть
    у трека otel, залоченная БД у нас) — другой случай: он держит лок стока, и
    ``flush`` обязан вернуть управление по дедлайну, а не ждать его. То, что
    осталось в очереди, не числится ни записанным, ни потерянным до ``close()``,
    и это сказано вслух: ``close()`` закрывает счёт.
    """
    gate = threading.Event()

    class _StuckSink:
        def append_records(self, records: List[Dict[str, Any]]) -> int:
            gate.wait(timeout=30.0)  # много больше дедлайна join — зависание видно как зависание
            return len(records)

    # Такт дренажа заведомо длиннее теста: очередь обязана достаться ИМЕННО
    # flush'у, иначе он сливал бы пустоту и о зависшем стоке не узнал бы вовсе
    # (первая редакция этого теста была ровно такой — инъекция «flush сливает
    # сам» не убила её).
    # batch_size заведомо больше очереди — иначе досрочное пробуждение по порогу
    # отдало бы записи потоку ещё до flush'а, и он снова сливал бы пустоту.
    w = BatchDrainWorker(_StuckSink(), 64, counter_name="evicted", batch_size=1000, flush_interval_sec=30.0)
    for i in range(10):
        w.write(_rec(i))

    result: List[Any] = []

    def call() -> None:
        result.append(w.flush(timeout=0.05))

    t0 = time.perf_counter()
    t = threading.Thread(target=call, daemon=True)
    t.start()
    t.join(timeout=3.0)
    elapsed = time.perf_counter() - t0

    assert not t.is_alive(), (
        "flush() повис на зависшем стоке вместо возврата по дедлайну — значит работу он делает "
        "в кадре вызывающего, а прервать заблокировавшийся сток там нечем"
    )
    assert elapsed < 1.0, f"flush(timeout=0.05) занял {elapsed:.2f}с — дедлайн не соблюдён"
    assert result, "flush() не вернул значение"

    gate.set()
    written, lost = w.close(timeout=2.0)
    assert written + lost == 10, f"после close() счёт обязан сойтись: {written}+{lost}"


def test_a_sink_stuck_forever_still_closes_with_a_named_loss() -> None:
    """Останов против НАВСЕГДА зависшего стока: счёт сходится, процесс не встаёт.

    Боевой случай — ``database is locked`` дольше ``busy_timeout``. ``close()``
    ждёт поток ровно свой дедлайн, а всё, что осталось в очереди, засчитывает в
    ПОТЕРИ. Без этого остаток исчезал бы молча — тот же девятый критерий, но на
    аварийном пути, которого ни один тест контракта не проходит: там сток либо
    работает, либо бросает.
    """
    gate = threading.Event()

    class _ForeverStuckSink:
        def append_records(self, records: List[Dict[str, Any]]) -> int:
            gate.wait(timeout=30.0)
            return len(records)

    w = BatchDrainWorker(_ForeverStuckSink(), 128, counter_name="evicted", batch_size=1, flush_interval_sec=0.01)
    for i in range(20):
        w.write(_rec(i))
    time.sleep(0.1)  # дать потоку войти в сток и там застрять
    # Эти пять уже НЕ достанутся потоку: он держит первые двадцать. Значит на
    # останове есть ОБЕ корзины — пачка «в полёте» и остаток очереди, — и
    # каждая закрывается своей веткой close().
    for i in range(100, 105):
        w.write(_rec(i))

    done: List[Any] = []

    def call_close() -> None:
        done.append(w.close(timeout=0.3))

    t0 = time.perf_counter()
    t = threading.Thread(target=call_close, daemon=True)
    t.start()
    t.join(timeout=JOIN_DEADLINE)
    elapsed = time.perf_counter() - t0

    gate.set()  # отпустить поток дренажа, чтобы он не пережил тест
    assert not t.is_alive(), "close() повис на зависшем стоке — останов процесса встал бы намертво"
    assert elapsed < 2.0, f"close(timeout=0.3) занял {elapsed:.2f}с"
    written, lost = done[0]
    assert lost > 0, "остаток очереди при зависшем стоке обязан числиться потерянным, а не исчезнуть"
    assert written + lost == 25, (
        f"счёт не сошёлся: {written}+{lost} при 25 принятых — 20 в полёте у потока и 5 в очереди"
    )


def test_channel_routing_shutdown_closes_taps_not_only_registered_channels() -> None:
    """Останов БАЗЫ тоже закрывает tap'ы — не только тот shutdown, что у логгера.

    ``LoggerCore.shutdown`` — полный override и базовый не зовёт, поэтому
    проводка останова понадобилась в ДВУХ местах. Живой store-tap висит на
    наследниках LoggerCore, и половина базы (StatsManager, ObservationManager)
    сегодня носит tap'ы, чей ``close()`` не делает ничего — то есть эта ветка
    без своего сторожа была бы проверена только «на глаз». Проверяется она
    шпионом: канал, который помнит, закрывали ли его.
    """
    from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
        ChannelRoutingManager,
    )

    class _SpyTap:
        name = "spy_tap"

        def __init__(self) -> None:
            self.closed = 0

        def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
            return {"status": "success", "channel": self.name}

        def close(self) -> None:
            self.closed += 1

    mgr = ChannelRoutingManager(manager_name="TapShutdownProbe", config={"channels": {}})
    mgr.initialize()
    spy = _SpyTap()
    mgr.add_tap(spy, min_level="DEBUG", name=spy.name)
    assert mgr.has_tap(spy.name), "предусловие: tap обязан стоять"

    mgr.shutdown()

    assert spy.closed == 1, (
        f"останов менеджера не закрыл tap (closed={spy.closed}) — очередь такого tap'а "
        "исчезла бы молча, а строка об исходе не прозвучала бы никогда"
    )
    assert not mgr.has_tap(spy.name), "останов обязан снять tap из реестра подписок"


class _MeasuringLock:
    """Лок, который помнит, СКОЛЬКО его держали. Замер — внутри критической секции."""

    def __init__(self, lock) -> None:
        self._lock = lock
        self.holds: List[float] = []
        self._entered = 0.0

    def __enter__(self):
        result = self._lock.__enter__()
        self._entered = time.perf_counter()
        return result

    def __exit__(self, *exc):
        self.holds.append(time.perf_counter() - self._entered)
        return self._lock.__exit__(*exc)


def test_drain_holds_the_lock_for_a_constant_time_regardless_of_depth() -> None:
    """Секция ``drain()`` не растёт с глубиной — вторая половина того же инварианта.

    Приёмочный К-Т1(б) держит литерал при ёмкости 1024; здесь добавлена
    ЕДИНСТВЕННАЯ вещь, которой у него нет, — что число не зависит от глубины.
    Без неё зелёный порог мог бы держаться просто потому, что машина быстрая.

    Сторож охраняет ЗАПАС: наблюдавшейся регрессии за этим нет (сквозной
    латентности подмена дека не меняет — см. докстринг К-Т1(б)), а секция
    сегодня укладывается в литерал с запасом. Медиана семи повторов, чтобы
    одиночное вытеснение потока не решало исход.
    """
    holds_1024 = _median_lock_hold(capacity=1024)
    holds_100k = _median_lock_hold(capacity=100_000)

    assert holds_1024 <= 2.0, (
        f"drain() держит лок {holds_1024:.2f} мкс при ёмкости 1024 (потолок 2.0) — "
        "критическая секция снова пропорциональна ёмкости"
    )
    # Вторая половина того же утверждения: секция НЕ растёт с глубиной. Без неё
    # порог мог бы держаться просто потому, что машина быстрая.
    assert holds_100k <= 2.0, (
        f"drain() держит лок {holds_100k:.2f} мкс при ёмкости 100 000 (потолок 2.0) — "
        f"секция растёт с глубиной (при 1024 было {holds_1024:.2f} мкс)"
    )


def _median_lock_hold(capacity: int, repeats: int = 7) -> float:
    """МИНИМУМ времени удержания лока в ``drain()`` за ``repeats`` проб, мкс.

    Оценка — МИНИМУМ, а не медиана (ревью итерации 2 плюс замер ведущего: соло
    3 из 3 зелёных, в общем прогоне каталога красный — в сессии работали ещё шесть
    агентов). Порог НЕ тронут, заменена ОЦЕНКА: конкуренция за процессор время
    только УВЕЛИЧИВАЕТ и никогда не уменьшает, поэтому минимум из N — наименее
    загрязнённая оценка незанятой машины, а медиана уезжает вместе с фоном.
    Сторож от этого не слабеет: настоящая регрессия здесь — возврат копии под
    локом, а это 0.10 -> 4.6 мкс при ёмкости 1024 и 0.20 -> 688 мкс при 100 000,
    то есть разрыв в десятки и сотни раз, который минимум ловит так же, как медиана.
    """
    holds: List[float] = []
    for _ in range(repeats):
        ch = BoundedChannel("hold_probe", capacity=capacity, overflow=DROP_OLDEST)
        for i in range(capacity):
            ch.write(_rec(i))
        meter = _MeasuringLock(ch._lock)  # белый ящик: предмет — граница секции
        ch._lock = meter
        ch.drain()
        assert meter.holds, "предусловие: drain() обязан был взять лок"
        holds.append(max(meter.holds) * 1e6)
    return min(holds)


# ---------------------------------------------------------------------------
# Гонки, найденные ревью: окно расширяется на ЭКЗЕМПЛЯРЕ, предмет не трогается
# ---------------------------------------------------------------------------


def test_flush_does_not_return_before_the_batch_reached_the_sink() -> None:
    """Б-1: ``flush()`` не имеет права сказать «дожимать нечего», пока пачка в пути.

    Между «канал опустошён» и «пачка отмечена в полёте» есть зазор, в котором
    условие ожидания видит 0 и 0. ``flush``/``flush_writers`` — ЕДИНСТВЕННАЯ
    дверь читателя к своим же записям (на неё опираются 18 правленых тестов),
    и дверь, умеющая соврать «пусто», возвращает ровно ту вакуумность, которую
    эти правки снимали.

    Окно расширяется задержкой в ``drain()`` ЭКЗЕМПЛЯРА канала — предмет не
    трогается. На естественном прогоне ложь редка (2 % при
    ``switchinterval=1e-6``, 0 из 12 000 при штатном), и сторож на везении
    смысла не имеет.
    """
    sink = _CollectingSink()
    slow_sink_delay = 0.4

    class _SlowSink:
        def append_records(self, records: List[Dict[str, Any]]) -> int:
            time.sleep(slow_sink_delay)
            return sink.append_records(records)

    w = BatchDrainWorker(_SlowSink(), 64, counter_name="evicted", flush_interval_sec=0.02)
    w.write(_rec(1))

    original_drain = w._channel.drain
    gate = threading.Event()

    def slow_drain():
        items = original_drain()
        if items and not gate.is_set():
            gate.set()
            time.sleep(0.3)  # канал уже пуст, пачка ещё не отмечена «в полёте»
        return items

    w._channel.drain = slow_drain  # белый ящик: расширяем окно, не меняя предмет

    try:
        assert gate.wait(timeout=JOIN_DEADLINE), "поток дренажа не забрал пачку"
        t0 = time.perf_counter()
        written, lost = w.flush(timeout=JOIN_DEADLINE)
        elapsed = time.perf_counter() - t0

        assert (written, lost) == (1, 0), (
            f"flush() отчитался {written}/{lost}, а запись одна — он вернулся до её доставки"
        )
        assert sink.flat, "flush() вернулся, а у стока пусто — «дожимать нечего» было ложью"
        assert elapsed >= slow_sink_delay * 0.5, (
            f"flush() вернулся за {elapsed * 1000:.1f} мс при стоке, которому нужно "
            f"{slow_sink_delay * 1000:.0f} мс — он не дождался пачки"
        )
    finally:
        w._channel.drain = original_drain
        w.close(timeout=2.0)


def test_a_write_racing_the_close_lands_in_exactly_one_bucket() -> None:
    """Б-2: у записи, принятой в зазоре с ``close()``, нет третьего исхода.

    ``write()`` решает «я открыт» и кладёт в канал; если между этими шагами
    прошёл останов, запись ложится в канал ПОСЛЕ последнего ``drain()`` — её
    нет ни в сторе, ни в ``written``, ни в ``lost``. Окно расширяется
    задержкой в ``write()`` ЭКЗЕМПЛЯРА канала: естественным прогоном ревью не
    поймало гонку и на 2.75 млн вызовов, а инвариант либо держится, либо нет.
    """
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 64, counter_name="evicted", flush_interval_sec=5.0)
    w.write(_rec(0))

    original_write = w._channel.write
    entered = threading.Event()

    def slow_write(record):
        entered.set()
        time.sleep(0.4)  # расширенное окно ВНУТРИ постановки
        return original_write(record)

    w._channel.write = slow_write
    outcome: List[Any] = []

    def emitter() -> None:
        outcome.append(w.write(_rec(999)))

    t = threading.Thread(target=emitter, daemon=True)
    t.start()
    assert entered.wait(timeout=JOIN_DEADLINE), "эмитент не вошёл в постановку"

    w.close(timeout=2.0)
    t.join(timeout=JOIN_DEADLINE)
    w._channel.write = original_write

    assert not t.is_alive(), "поток эмитента завис на закрытии"
    assert outcome, "эмитент не вернул ответ"
    accepted = 2 if outcome[0].get("status") == "success" else 1
    written, lost = w.totals()
    assert written + lost == accepted, (
        f"принято {accepted} (ответ эмитента {outcome[0].get('status')!r}), "
        f"а записано+потеряно = {written}+{lost} = {written + lost}: третий исход существует. "
        f"Осиротевшая очередь: {len(w._channel)}"
    )


def test_nothing_vanishes_when_close_arrives_while_writers_are_still_running() -> None:
    """Останов приходит, пока восемь писателей ещё пишут: без зависания,
    без дублей, без просадки учёта.

    Сосед выше (``..._and_an_immediate_close``) дожидается писателей и только
    потом закрывает; здесь ``close()`` зовётся из середины их работы.

    **Чего этот тест НЕ стережёт — сказано прямо, ревью итерации 2.** Прежняя
    редакция докстринга обещала «девятый критерий ПРИ ЖИВОЙ ГОНКЕ», и это было
    шире правды: под инъекцией самой гонки (проверка ``_closed`` вынесена из
    приёмного лока) он остаётся ЗЕЛЁНЫМ — естественное окно в несколько
    байт-кодов сюда не попадает, что подтверждено прогоном в ~2.75 млн вызовов
    с разницей ноль. Собственной гарантии у него нет: единственная заплата,
    которая его краснит, краснит ещё девять тестов заодно.

    Само свойство при этом защищено — детерминированно, через шлюз, соседним
    ``test_a_write_racing_the_close_lands_in_exactly_one_bucket``. Дыры в
    покрытии нет; неверным было обещание, а не набор.
    """
    sink = _CollectingSink()
    w = BatchDrainWorker(sink, 256, counter_name="evicted", batch_size=32, flush_interval_sec=0.01)
    threads = 8
    per_thread = 400
    accepted = [0] * threads
    errors: List[str] = []
    started = threading.Barrier(threads + 1)

    def writer(tid: int) -> None:
        try:
            started.wait(timeout=JOIN_DEADLINE)
            taken = 0
            for i in range(per_thread):
                # Считаем ПРИНЯТЫЕ ответы: после закрытия write() отвечает
                # "dropped", и такие вызовы в инвариант не входят — воркер их
                # учитывает своей корзиной, а не принимает.
                if w.write({"n": tid * per_thread + i}).get("status") == "success":
                    taken += 1
            accepted[tid] = taken
        except Exception as exc:
            errors.append(repr(exc))

    pool = [threading.Thread(target=writer, args=(t,), daemon=True) for t in range(threads)]
    for t in pool:
        t.start()
    started.wait(timeout=JOIN_DEADLINE)
    time.sleep(0.01)  # дать писателям войти в работу — останов приходит В СЕРЕДИНЕ
    written, lost = w.close(timeout=3.0)
    for t in pool:
        t.join(timeout=JOIN_DEADLINE)

    assert not errors, errors
    assert all(not t.is_alive() for t in pool), "писательский поток завис на закрытии"

    final_written, final_lost = w.totals()
    total_accepted = sum(accepted)
    assert final_written + final_lost >= total_accepted, (
        f"принято {total_accepted}, учтено {final_written}+{final_lost} = {final_written + final_lost}: "
        "часть записей исчезла молча"
    )
    assert len(sink.flat) == final_written, f"сток принял {len(sink.flat)}, воркер насчитал {final_written}"
    assert len({r["n"] for r in sink.flat}) == len(sink.flat), "запись доехала до стока ДВАЖДЫ"
