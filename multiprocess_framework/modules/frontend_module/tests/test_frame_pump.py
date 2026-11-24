# -*- coding: utf-8 -*-
"""Тесты FramePump (T2 плана gui-frame-path): таймер на ключ вытягивает кадры из ящика.

Ящик — настоящий ``LatestMailbox`` (T1); фейковый ящик ``_AgedMailbox`` нужен только там, где
важны точные возрасты кадров. Допуски частот — окно >= 1 с и диапазон, а не точное число
(джиттер таймера Windows). Источники кадров — daemon-потоки с ``join(timeout)``.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import types
import weakref
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer  # noqa: E402

from multiprocess_framework.modules.frontend_module.bridge import frame_pump as frame_pump_mod  # noqa: E402
from multiprocess_framework.modules.frontend_module.bridge.frame_pump import FramePump  # noqa: E402
from multiprocess_framework.modules.process_module.generic.latest_mailbox import LatestMailbox  # noqa: E402

_JOIN_S = 3.0


class _Calls:
    """Запись вызовов sink: ключ, item, поток, время."""

    def __init__(self) -> None:
        self.records: list[tuple[str, Any, int, float]] = []

    def sink(self, key: str, item: Any) -> None:
        self.records.append((key, item, threading.get_ident(), time.perf_counter()))

    def count(self, key: str | None = None) -> int:
        return sum(1 for k, *_ in self.records if key is None or k == key)

    def items(self, key: str) -> list[Any]:
        return [item for k, item, *_ in self.records if k == key]


class _Source:
    """Daemon-источник: кладёт в ящик ``rate`` кадров в секунду по часам (``due = int(t*rate)+1``)."""

    def __init__(self, mailbox: Any, key: str, rate: float) -> None:
        self.put_count = 0
        self._mailbox = mailbox
        self._key = key
        self.rate = rate
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "_Source":
        self._thread.start()
        return self

    def _run(self) -> None:
        started = time.perf_counter()
        while not self._stop.is_set():
            due = int((time.perf_counter() - started) * self.rate) + 1
            while self.put_count < due:
                self.put_count += 1
                self._mailbox.put(self._key, {"n": self.put_count})
            time.sleep(0.001)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=_JOIN_S)
        assert not self._thread.is_alive(), "источник не остановился"


@pytest.fixture
def mailbox() -> LatestMailbox:
    return LatestMailbox()


@pytest.fixture
def calls() -> _Calls:
    return _Calls()


@pytest.fixture
def pump(qtbot: Any, mailbox: LatestMailbox, calls: _Calls):  # noqa: ARG001
    p = FramePump(mailbox, calls.sink)
    yield p
    p.stop()
    p.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def make_pump(qtbot: Any):  # noqa: ARG001
    """Фабрика насосов с произвольным sink/ящиком; teardown: ``stop()`` и ``deleteLater()``."""
    made: list[FramePump] = []

    def factory(mailbox_: Any, sink_: Any) -> FramePump:
        p = FramePump(mailbox_, sink_)
        made.append(p)
        return p

    yield factory
    for p in made:
        p.stop()
        p.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _run_window(qtbot: Any, calls: _Calls, sources: list[_Source], window_s: float) -> dict[str, int]:
    """Крутить цикл событий ``window_s`` с работающими источниками; вернуть число вызовов по ключам."""
    for source in sources:
        source.start()
    qtbot.wait(int(window_s * 1000))
    counts = {key: calls.count(key) for key in {k for k, *_ in calls.records}}
    puts = [(source.put_count, source.rate) for source in sources]
    for source in sources:
        source.stop()
    for put, rate in puts:
        assert put >= 0.9 * rate * window_s, (
            f"источник дал только {put} put за {window_s} с (предусловие >= 0,9 x {rate}/с)"
        )
    return counts


# ---------------------------------------------------------------------------------------
# REDS
# ---------------------------------------------------------------------------------------


def test_pump_delivers_only_latest_after_blocked_loop(qtbot, pump, mailbox, calls) -> None:
    """Цикл заблокирован 0,5 с, пока источник кладёт 300 кадров: sink получает последний, а не 300."""
    pump.set_keys({"a": 30})
    done = threading.Event()

    def burst() -> None:
        for n in range(1, 301):
            mailbox.put("a", {"n": n})
        done.set()

    thread = threading.Thread(target=burst, daemon=True)
    thread.start()
    time.sleep(0.5)  # блокировка цикла событий Qt-потока
    thread.join(timeout=_JOIN_S)
    assert not thread.is_alive()
    assert done.is_set(), "предусловие: все 300 put выполнены"

    deadline = time.perf_counter() + 2.0
    while calls.count("a") == 0 and time.perf_counter() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    qtbot.wait(200)  # ещё несколько тиков: пустой ящик не должен давать вызовов sink

    assert 1 <= calls.count("a") <= 2
    assert calls.items("a")[-1] == {"n": 300}


@pytest.mark.parametrize(
    ("fps_limit", "window_s", "low", "high"),
    [(20, 1.0, 14, 22), (30, 2.0, 52, 62)],
)
def test_rate_capped_by_fps_limit(qtbot, pump, mailbox, calls, fps_limit, window_s, low, high) -> None:
    """200 put/с: показ не чаще ``fps_limit``. 30 Гц за 2 с: Coarse-таймер даёт 42, Precise 58-59."""
    pump.set_keys({"a": fps_limit})
    counts = _run_window(qtbot, calls, [_Source(mailbox, "a", 200)], window_s)
    assert low <= counts["a"] <= high, f"вызовов sink {counts['a']}, ожидалось {low}..{high}"


def test_per_key_rates_differ(qtbot, pump, mailbox, calls) -> None:
    """Ключи с пределами 20 и 40 за 2 с: у каждого свой предел."""
    pump.set_keys({"slow": 20, "fast": 40})
    counts = _run_window(qtbot, calls, [_Source(mailbox, "slow", 200), _Source(mailbox, "fast", 200)], 2.0)
    assert 34 <= counts["slow"] <= 44, counts
    assert 70 <= counts["fast"] <= 84, counts


def test_slow_key_not_starved_by_fast_key(qtbot, pump, mailbox, calls) -> None:
    """Быстрый ключ (300 put/с) не голодит медленный: 4 кадра раз в 250 мс доходят все, по порядку."""
    pump.set_keys({"fast": 30, "slow": 30})
    fast = _Source(mailbox, "fast", 300).start()

    def slow_producer() -> None:
        for n in range(1, 5):
            time.sleep(0.25)
            mailbox.put("slow", {"n": n})

    thread = threading.Thread(target=slow_producer, daemon=True)
    thread.start()
    qtbot.wait(1300)
    thread.join(timeout=_JOIN_S)
    assert not thread.is_alive()
    fast.stop()
    assert [item["n"] for item in calls.items("slow")] == [1, 2, 3, 4]
    assert calls.count("fast") > 10


def test_put_posts_no_qt_event(qtbot, pump, mailbox, calls) -> None:
    """300 put из потока не создают Qt-событий (кроме Timer); контроль: postEvent из потока виден."""
    pump.set_keys({"a": 30})
    QCoreApplication.processEvents()  # осесть: ChildAdded и прочее от создания таймеров

    seen: list[int] = []

    class _Counter(QObject):
        def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
            if event.type() != QEvent.Type.Timer:
                seen.append(int(event.type()))
            return False

    app = QCoreApplication.instance()
    counter = _Counter()
    app.installEventFilter(counter)
    try:
        seen.clear()
        thread = threading.Thread(target=lambda: [mailbox.put("a", {"n": n}) for n in range(1, 301)], daemon=True)
        thread.start()
        thread.join(timeout=_JOIN_S)
        assert not thread.is_alive()
        QCoreApplication.processEvents()
        assert seen == [], f"put породил Qt-события: {seen}"

        # контроль: тот же счётчик видит postEvent из потока (без него тест зелёный на любой реализации)
        poster = threading.Thread(
            target=lambda: QCoreApplication.postEvent(pump, QEvent(QEvent.Type.User)), daemon=True
        )
        poster.start()
        poster.join(timeout=_JOIN_S)
        assert not poster.is_alive()
        QCoreApplication.processEvents()
        assert int(QEvent.Type.User) in seen, f"контроль слеп: {seen}"
    finally:
        app.removeEventFilter(counter)


def test_sink_exception_does_not_stop_pump(qtbot, make_pump, mailbox) -> None:
    """Исключение sink: ``errors`` растёт, показ продолжается."""
    attempts: list[int] = []
    shown: list[int] = []

    def sink(key: str, item: Any) -> None:  # noqa: ARG001
        attempts.append(item["n"])
        if len(attempts) <= 3:
            raise ValueError("boom")
        shown.append(item["n"])

    pump = make_pump(mailbox, sink)
    pump.set_keys({"a": 60})
    source = _Source(mailbox, "a", 200).start()
    qtbot.wait(800)
    source.stop()
    qtbot.wait(150)  # пустые тики после остановки источника
    st = pump.stats()["a"]
    assert st["errors"] == 3
    assert st["errors"] + st["shown"] == mailbox.stats()["taken"], "sink вызван не по снятому кадру"
    assert st["shown"] == len(shown) and len(shown) >= 5


def test_unconfigured_key_found_by_scan_and_served(qtbot, pump, mailbox, calls) -> None:
    """Ключ вне set_keys: скан находит его и обслуживает на 30 Гц (за 2 с от первого вызова 50..62)."""
    pump.set_keys({"other": 20})
    source = _Source(mailbox, "stranger", 200).start()
    deadline = time.perf_counter() + 1.5
    while calls.count("stranger") == 0 and time.perf_counter() < deadline:
        qtbot.wait(10)
    assert calls.count("stranger") > 0, "скан не нашёл ключ вне set_keys"
    first = calls.records[0][3]
    qtbot.wait(2000)
    in_window = sum(1 for k, _, _, t in calls.records if k == "stranger" and first <= t < first + 2.0)
    source.stop()
    assert 50 <= in_window <= 62, in_window


@pytest.mark.parametrize("fps_limit", [0, 120, 240, float("inf")])
def test_zero_fps_limit_capped_at_60(qtbot, pump, mailbox, calls, fps_limit) -> None:
    """``fps_limit`` 0 и всё выше 60 = потолок 60 Гц: за 1 с 40..60 (``int`` вместо ``ceil`` дал бы 62,
    снятый верхний зажим — 111 для 120)."""
    pump.set_keys({"a": fps_limit})
    counts = _run_window(qtbot, calls, [_Source(mailbox, "a", 400)], 1.0)
    assert 40 <= counts["a"] <= 60, counts


def test_stop_no_calls_after(qtbot, pump, mailbox, calls) -> None:
    """После ``stop()`` sink не вызывается, повторный ``stop()`` и ``set_keys`` безопасны."""
    pump.set_keys({"a": 60})
    source = _Source(mailbox, "a", 200).start()
    qtbot.wait(300)
    assert calls.count("a") > 0
    pump.stop()
    frozen = calls.count("a")
    qtbot.wait(400)
    pump.stop()
    pump.set_keys({"a": 60})
    qtbot.wait(200)
    source.stop()
    assert calls.count("a") == frozen


def test_sink_runs_in_qt_thread(qtbot, pump, mailbox, calls) -> None:
    """sink вызывается в потоке, где создан насос, не в потоке источника."""
    pump.set_keys({"a": 60})
    source = _Source(mailbox, "a", 100).start()
    qtbot.wait(300)
    source.stop()
    idents = {ident for _, _, ident, _ in calls.records}
    assert calls.count("a") > 0
    assert idents == {threading.get_ident()}


# ---------------------------------------------------------------------------------------
# Вне REDS: контракт насоса, жизненный цикл, потокобезопасность stats()
# ---------------------------------------------------------------------------------------


class _AgedMailbox:
    """Фейк ящика с заданными возрастами: ``take`` отдаёт кадры очереди по одному."""

    def __init__(self, queued: list[tuple[Any, float]]) -> None:
        self._queued = list(queued)

    def push(self, item: Any, age_s: float) -> None:
        self._queued.append((item, age_s))

    def take(self, key: str) -> tuple[Any, float] | None:  # noqa: ARG002
        return self._queued.pop(0) if self._queued else None

    def pending_keys(self) -> list[str]:
        return []


def test_sink_gets_whole_item_untouched(qtbot, pump, mailbox, calls) -> None:
    """item приходит тем же объектом: ``capture_ns``, ``capture_ts``, ``replay`` насос не трогает."""
    item = {"frame": object(), "capture_ns": 123, "capture_ts": 4.5, "replay": True}
    pump.set_keys({"a": 60})
    mailbox.put("a", item)
    qtbot.wait(100)
    assert calls.items("a") == [item]
    assert calls.items("a")[0] is item


def test_window_max_age_resets_only_on_request(qtbot, calls) -> None:
    """Окно возраста: 40 и 10 мс; ``stats(reset_window=True)`` отдаёт 40, следующий кадр — 10."""
    fake = _AgedMailbox([("f1", 0.040), ("f2", 0.010)])
    p = FramePump(fake, calls.sink)
    try:
        p.set_keys({"a": 60})
        qtbot.wait(150)
        peek = p.stats()["a"]
        assert (peek["max_age_ms"], peek["window_max_age_ms"], peek["shown"]) == (
            pytest.approx(40.0),
            pytest.approx(40.0),
            2,
        )
        assert p.stats()["a"]["window_max_age_ms"] == pytest.approx(40.0), "stats() без аргумента окно не сбрасывает"
        assert p.stats(reset_window=True)["a"]["window_max_age_ms"] == pytest.approx(40.0)
        assert p.stats()["a"]["window_max_age_ms"] == 0.0
        fake.push("f3", 0.010)
        qtbot.wait(150)
        after = p.stats(reset_window=True)["a"]
        assert after["window_max_age_ms"] == pytest.approx(10.0)
        assert after["max_age_ms"] == pytest.approx(40.0)
    finally:
        p.stop()
        p.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_set_keys_drops_removed_key(qtbot, pump, mailbox, calls) -> None:
    """Ключ, снятый из ``set_keys``, не обслуживается (а скан не заводит ему таймер без кадра в ящике)."""
    pump.set_keys({"a": 60, "b": 60})
    mailbox.put("b", {"n": 1})
    qtbot.wait(100)
    assert calls.count("b") == 1
    pump.set_keys({"a": 60})
    assert "b" not in pump.stats()
    qtbot.wait(250)  # два прохода скана: в ящике для b пусто — таймер не появляется
    assert "b" not in pump.stats()


def test_set_keys_retunes_scan_found_key(qtbot, pump, mailbox, calls) -> None:
    """``set_keys`` перехватывает ключ, найденный сканом, и меняет ему период (30 Гц -> 20 Гц)."""
    source = _Source(mailbox, "stranger", 200).start()
    deadline = time.perf_counter() + 1.5
    while calls.count("stranger") == 0 and time.perf_counter() < deadline:
        qtbot.wait(10)
    assert calls.count("stranger") > 0
    pump.set_keys({"stranger": 20})
    base = calls.count("stranger")
    qtbot.wait(1000)
    got = calls.count("stranger") - base
    source.stop()
    assert 14 <= got <= 22, got


@pytest.mark.parametrize("bad", [None, 0, float("nan"), "abc", object(), float("inf")])
def test_odd_fps_limit_does_not_break_set_keys(qtbot, pump, mailbox, calls, bad) -> None:
    """Нечисловой, NaN, бесконечный и нулевой ``fps_limit`` не роняют ``set_keys``; ключ обслуживается."""
    pump.set_keys({"a": bad})
    assert "a" in pump.stats()
    mailbox.put("a", {"n": 1})
    qtbot.wait(150)
    assert calls.count("a") == 1


def test_stats_thread_safe_during_set_keys(qtbot, pump, mailbox) -> None:
    """Читатель ``stats()`` в цикле, пока основной поток 200 раз меняет набор ключей: ни одного исключения."""
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                pump.stats()
                pump.stats(reset_window=True)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    thread = threading.Thread(target=reader, daemon=True)
    try:
        thread.start()
        for i in range(200):
            pump.set_keys({f"k{j}": 60 for j in range(i % 7 + 1)} | {f"extra{i}": 30})
    finally:
        stop.set()
        thread.join(timeout=_JOIN_S)
        sys.setswitchinterval(old_interval)
    assert not thread.is_alive()
    assert errors == []


def test_stats_snapshot_has_no_references_to_internal_state(qtbot, pump, mailbox) -> None:
    """Снимок ``stats()`` — копия: правка внешнего и вложенного словаря не меняет счётчики насоса."""
    pump.set_keys({"a": 60})
    mailbox.put("a", {"n": 1})
    qtbot.wait(100)
    first = pump.stats()
    assert first["a"]["shown"] == 1

    first["a"]["shown"] = 999
    first["a"]["extra"] = 1
    first["zz"] = {"shown": 5}
    del first["a"]["errors"]

    second = pump.stats()
    assert second["a"]["shown"] == 1
    assert second["a"]["errors"] == 0
    assert "extra" not in second["a"]
    assert "zz" not in second
    assert second is not first
    assert second["a"] is not first["a"]


def test_real_mailbox_wiring_scan_and_latest(qtbot, pump, mailbox, calls) -> None:
    """Сквозь настоящий ящик: источник из потока, ключ вне набора найден сканом, а в sink доходит свежий кадр."""
    source = _Source(mailbox, "x", 200).start()
    qtbot.wait(600)
    source.stop()
    qtbot.wait(100)
    assert calls.count("x") > 0
    last_put = source.put_count
    assert calls.items("x")[-1] == {"n": last_put}
    assert math.isfinite(pump.stats()["x"]["busy_ms_total"])


def test_pump_not_kept_alive_by_timer_connections(qtbot, mailbox, calls) -> None:  # noqa: ARG001
    """Обработчики таймеров не держат насос сильной ссылкой: цикл разрушался сборщиком после
    ``stop()`` и ронял процесс (Fatal Python error: Aborted в следующем ``exec()``)."""
    p = FramePump(mailbox, calls.sink)
    p.set_keys({"a": 20, "b": 30})
    p.stop()
    ref = weakref.ref(p)
    del p
    assert ref() is None


class _SpyMailbox(LatestMailbox):
    """Настоящий ящик, который помнит, по каким ключам звали ``take``."""

    def __init__(self) -> None:
        super().__init__()
        self.take_keys: list[str] = []

    def take(self, key: str):
        self.take_keys.append(key)
        return super().take(key)


def test_negative_fps_limit_is_one_hertz(qtbot, pump, mailbox, calls) -> None:
    """``fps_limit`` -5 = 1 Гц (нижний зажим), а не 60 Гц: через 0,3 с кадра ещё нет, к 1,3 с он один."""
    pump.set_keys({"a": -5})
    mailbox.put("a", {"n": 1})
    qtbot.wait(300)
    assert calls.count("a") == 0
    qtbot.wait(1000)
    assert calls.count("a") == 1


def test_set_keys_after_stop_starts_no_timers(qtbot, pump) -> None:
    """После ``stop()`` ``set_keys`` ничего не заводит: ни одного активного ``QTimer`` среди детей."""
    pump.set_keys({"a": 60})
    pump.stop()
    pump.set_keys({"a": 60, "b": 30})
    qtbot.wait(100)
    assert [t for t in pump.findChildren(QTimer) if t.isActive()] == []
    assert pump.stats()["a"]["shown"] == 0
    assert "b" not in pump.stats()


def test_dropped_key_is_no_longer_taken(qtbot, make_pump, calls) -> None:
    """Таймер снятого ключа остановлен: после ``set_keys`` без ``b`` ящик по ``b`` не опрашивается."""
    spy = _SpyMailbox()
    pump = make_pump(spy, calls.sink)
    pump.set_keys({"a": 60, "b": 60})
    qtbot.wait(100)
    assert "b" in spy.take_keys
    pump.set_keys({"a": 60})
    spy.take_keys.clear()
    qtbot.wait(300)
    assert "b" not in spy.take_keys
    assert "a" in spy.take_keys


def test_set_keys_drops_scan_found_key_and_scan_readopts(qtbot, pump, mailbox) -> None:
    """Найденный сканом ключ ``set_keys`` снимает (FE-007); пока идут кадры, скан заводит его снова."""
    source = _Source(mailbox, "stranger", 200).start()
    deadline = time.perf_counter() + 1.5
    while "stranger" not in pump.stats() and time.perf_counter() < deadline:
        qtbot.wait(10)
    assert "stranger" in pump.stats(), "скан не нашёл ключ"
    pump.set_keys({"other": 20})
    assert "stranger" not in pump.stats()
    qtbot.wait(300)
    assert "stranger" in pump.stats(), "скан не завёл ключ заново"
    source.stop()


def test_sink_may_call_stats_and_set_keys(qtbot, make_pump, mailbox) -> None:
    """``sink`` вызывается вне замка насоса: ``stats()`` доступен из соседнего потока, ``set_keys`` — из sink.

    Проверка замка — из daemon-потока (только ``stats()``: ``set_keys`` вызывается из Qt-потока) с
    join-дедлайном: на насосе, держащем замок во время ``sink``, поток не возвращается за дедлайн
    (красный по дедлайну, а не зависание прогона).
    """
    outcome: dict[str, Any] = {}
    holder: dict[str, Any] = {}

    def sink(key: str, item: Any) -> None:  # noqa: ARG001
        if outcome:
            return
        pump = holder["pump"]
        probe = threading.Thread(target=pump.stats, daemon=True)
        probe.start()
        probe.join(timeout=1.0)
        outcome["free"] = not probe.is_alive()
        holder["probe"] = probe
        if outcome["free"]:  # из самого sink: Qt-поток насоса, повторный вход
            pump.stats()
            pump.set_keys({"a": 60, "c": 30})
            outcome["reentered"] = True

    pump = holder["pump"] = make_pump(mailbox, sink)
    pump.set_keys({"a": 60})
    mailbox.put("a", {"n": 1})
    qtbot.waitUntil(lambda: bool(outcome), timeout=3000)
    holder["probe"].join(timeout=_JOIN_S)
    assert not holder["probe"].is_alive()
    assert outcome == {"free": True, "reentered": True}
    assert "c" in pump.stats()


def test_busy_ms_total_counts_milliseconds_in_sink(qtbot, make_pump, mailbox) -> None:
    """``busy_ms_total`` — миллисекунды, проведённые в ``sink``: 6 кадров по ~10 мс дают 55..250, а не 0 и не 0,06."""

    def sink(key: str, item: Any) -> None:  # noqa: ARG001
        time.sleep(0.01)

    pump = make_pump(mailbox, sink)
    pump.set_keys({"a": 60})
    for n in range(6):
        mailbox.put("a", {"n": n})
        qtbot.wait(60)
    st = pump.stats()["a"]
    assert st["shown"] == 6
    assert 55.0 <= st["busy_ms_total"] <= 250.0, st["busy_ms_total"]


def _recording_log(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """Подменить логгер насоса записывающим (``caplog`` через фасад логгера проекта не работает)."""
    records: list[tuple[Any, ...]] = []

    class _Rec:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            records.append(args)

    monkeypatch.setattr(frame_pump_mod, "_log", _Rec())
    return records


def test_sink_error_log_is_rate_limited(qtbot, make_pump, mailbox, monkeypatch) -> None:
    """20+ сбоев ``sink`` за 0,4 с дают ровно одну запись лога (а не строку на тик и не ноль)."""
    records = _recording_log(monkeypatch)

    def sink(key: str, item: Any) -> None:  # noqa: ARG001
        raise ValueError("boom")

    pump = make_pump(mailbox, sink)
    pump.set_keys({"a": 60})
    source = _Source(mailbox, "a", 200).start()
    qtbot.wait(400)
    source.stop()
    assert pump.stats()["a"]["errors"] >= 20
    assert len(records) == 1


def test_sink_error_log_period_is_five_seconds(qtbot, make_pump, mailbox, monkeypatch) -> None:
    """Управляемые часы: повторная запись о сбое — не раньше чем через 5 с (4,9 с — нет, 5,1 с — да)."""
    records = _recording_log(monkeypatch)
    now = [100.0]
    monkeypatch.setattr(frame_pump_mod, "time", types.SimpleNamespace(perf_counter=lambda: now[0]))

    def sink(key: str, item: Any) -> None:  # noqa: ARG001
        raise ValueError("boom")

    pump = make_pump(mailbox, sink)
    pump.set_keys({"a": 60})

    def fail_once(expected_errors: int) -> None:
        mailbox.put("a", {"n": expected_errors})
        qtbot.waitUntil(lambda: pump.stats()["a"]["errors"] == expected_errors, timeout=2000)

    fail_once(1)
    assert len(records) == 1
    now[0] = 104.9
    fail_once(2)
    assert len(records) == 1, "запись раньше 5 с"
    now[0] = 105.1
    fail_once(3)
    assert len(records) == 2, "записи через 5,1 с нет"


class _BadFps:
    """``fps_limit``, у которого ``float()`` бросает исключение, не ловимое ``_period_ms``."""

    def __float__(self) -> float:
        raise RuntimeError("bad fps_limit")


def test_set_keys_is_atomic_when_a_period_fails(qtbot, pump) -> None:  # noqa: ARG001
    """Сбой расчёта периода одного ключа не оставляет набор применённым наполовину."""
    pump.set_keys({"old": 30})
    before = pump.stats()
    active_before = sum(1 for t in pump.findChildren(QTimer) if t.isActive())
    with pytest.raises(RuntimeError, match="bad fps_limit"):
        pump.set_keys({"new1": 30, "bad": _BadFps(), "new2": 30})
    assert pump.stats() == before
    assert set(pump.stats()) == {"old"}
    assert sum(1 for t in pump.findChildren(QTimer) if t.isActive()) == active_before


def test_huge_fps_limit_does_not_half_apply_set_keys(qtbot, pump, mailbox, calls) -> None:
    """``10**400`` не помещается в float: ``set_keys`` не бросает, применяет набор целиком, ключ работает на 60 Гц."""
    pump.set_keys({"old": 30})
    pump.set_keys({"new1": 30, "bad": 10**400, "new2": 30})
    assert set(pump.stats()) == {"new1", "bad", "new2"}
    counts = _run_window(qtbot, calls, [_Source(mailbox, "bad", 400)], 1.0)
    assert 40 <= counts["bad"] <= 60, counts
