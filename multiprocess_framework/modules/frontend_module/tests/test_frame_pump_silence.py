# -*- coding: utf-8 -*-
"""Приёмочные тесты колбэка тишины ``FramePump`` (W2-c), написаны вслепую до кода.

Purpose: закрепить контракт ``FramePump(..., on_silence=None, silence_s=0.0)``: тишина по ключу
считается от последнего показанного кадра (без кадров — от ``set_keys``), колбэк зовётся не чаще
раза на целую секунду возраста, показанный кадр после тишины даёт ``on_silence(key, None)``.

Время реальное. Ящик — фейк (``take``/``pending_keys``), всё идёт в одном Qt-потоке; события Qt
крутит цикл с дедлайном, кадры «источника» кладёт тот же цикл.
"""

from __future__ import annotations

import faulthandler
import os
import time
from collections.abc import Callable
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

__all__: list[str] = []

_DEADLINE_S = 3.0  # дедлайн одного ожидания в цикле событий
_FEED_PERIOD_S = 0.05  # период подачи кадров «источником»
_HARD_DEADLINE_S = 30.0  # на тест: если насос не вернул управление из processEvents


@pytest.fixture(autouse=True)
def _hard_deadline():
    """Аварийный дедлайн: дедлайны циклов не сработают, если зависнет сам ``processEvents``."""
    faulthandler.dump_traceback_later(_HARD_DEADLINE_S, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


class _Mailbox:
    """Фейк ящика: на ключ хранится только последний кадр, ``take`` забирает его."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def put(self, key: str, item: Any) -> None:
        self._items[key] = item

    def take(self, key: str) -> tuple[Any, float] | None:
        if key not in self._items:
            return None
        return self._items.pop(key), 0.0

    def pending_keys(self) -> list[str]:
        return list(self._items)


class _Journal:
    """Общий журнал вызовов: ``("silence", key, age)`` и ``("sink", key)`` в порядке вызова."""

    def __init__(self) -> None:
        self.entries: list[tuple[Any, ...]] = []

    def sink(self, key: str, item: Any) -> None:  # noqa: ARG002
        self.entries.append(("sink", key))

    def on_silence(self, key: str, age_s: float | None) -> None:
        self.entries.append(("silence", key, age_s))

    def silences(self, start: int = 0) -> list[tuple[Any, ...]]:
        return [e for e in self.entries[start:] if e[0] == "silence"]

    def sinks(self, key: str) -> int:
        return sum(1 for e in self.entries if e == ("sink", key))

    def nones(self) -> list[tuple[Any, ...]]:
        return [e for e in self.silences() if e[2] is None]


@pytest.fixture
def make_pump(qtbot: Any):  # noqa: ARG001
    """Фабрика насосов; teardown: ``stop()`` и ``deleteLater()``."""
    made: list[Any] = []

    def factory(mailbox: Any, sink: Any, **kwargs: Any) -> Any:
        # импорт внутри вызова из теста: отсутствие параметра краснит тест, а не сбор
        from multiprocess_framework.modules.frontend_module.bridge.frame_pump import FramePump

        pump = FramePump(mailbox, sink, **kwargs)
        made.append(pump)
        return pump

    yield factory
    for pump in made:
        pump.stop()
        pump.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _tick() -> None:
    QCoreApplication.processEvents()
    time.sleep(0.005)


def _spin(seconds: float) -> None:
    """Крутить цикл событий ``seconds`` секунд."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        _tick()


def _wait_for(predicate: Callable[[], bool], what: str) -> None:
    """Крутить цикл событий до выполнения условия, не дольше ``_DEADLINE_S``."""
    end = time.perf_counter() + _DEADLINE_S
    while not predicate():
        assert time.perf_counter() < end, f"не дождались за {_DEADLINE_S} с: {what}"
        _tick()


def _feed(mailbox: _Mailbox, key: str, seconds: float) -> None:
    """Крутить цикл ``seconds`` секунд, кладя кадр ключа каждые 50 мс (первый — сразу)."""
    start = time.perf_counter()
    next_put = start
    while time.perf_counter() - start < seconds:
        if time.perf_counter() >= next_put:
            mailbox.put(key, {"key": key})
            next_put += _FEED_PERIOD_S
        _tick()


def test_silence_reported_once_per_second_with_bounds(make_pump) -> None:
    """Один кадр и 2,4 с пустоты: по одной записи на целые секунды возраста 0, 1 и 2."""
    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=0.3)
    pump.set_keys({"cam_a": 30})
    mailbox.put("cam_a", {"n": 1})
    _wait_for(lambda: journal.sinks("cam_a") == 1, "первый кадр в sink")
    _spin(2.4)

    after_sink = journal.silences(journal.entries.index(("sink", "cam_a")) + 1)
    assert [e[1] for e in after_sink] == ["cam_a", "cam_a", "cam_a"], journal.entries
    ages = [e[2] for e in after_sink]
    assert [int(age) for age in ages] == [0, 1, 2], ages
    assert all(age >= 0.3 for age in ages), ages
    assert isinstance(ages[0], float), type(ages[0])
    assert 0.3 <= ages[0] <= 1.0, ages


def test_frame_after_silence_reports_none_once(make_pump) -> None:
    """Кадр после тишины даёт ровно один ``None`` сразу после своего ``sink``; следующий кадр — нет."""
    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=0.3)
    pump.set_keys({"cam_a": 30})
    mailbox.put("cam_a", {"n": 1})
    _wait_for(lambda: journal.sinks("cam_a") == 1, "первый кадр в sink")
    _wait_for(lambda: bool(journal.silences()), "запись о тишине")
    # предпосылка: есть и показанный кадр, и тишина, а None ещё не было
    assert ("sink", "cam_a") in journal.entries
    assert journal.silences()
    assert journal.nones() == [], journal.entries

    mailbox.put("cam_a", {"n": 2})
    _wait_for(lambda: journal.sinks("cam_a") == 2, "кадр после тишины в sink")
    mailbox.put("cam_a", {"n": 3})
    _wait_for(lambda: journal.sinks("cam_a") == 3, "второй кадр следом в sink")
    _spin(0.1)

    assert journal.nones() == [("silence", "cam_a", None)], journal.entries
    at = journal.entries.index(("silence", "cam_a", None))
    assert journal.entries[at - 1] == ("sink", "cam_a"), journal.entries
    # «свой» sink — второй по счёту (кадр после тишины), а не более ранний и не более поздний
    assert journal.entries[:at].count(("sink", "cam_a")) == 2, journal.entries


def test_configured_key_without_any_frame_is_silent(make_pump) -> None:
    """Ключ из ``set_keys`` без единого кадра: возраст считается от ``set_keys``."""
    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=0.3)
    pump.set_keys({"cam_a": 30})
    _spin(1.0)

    silences = journal.silences()
    assert silences, "за 1 с нет записи о тишине"
    assert silences[0][1] == "cam_a"
    assert silences[0][2] is not None
    assert 0.3 <= silences[0][2] <= 1.0, silences
    assert journal.sinks("cam_a") == 0


def test_disabled_modes_never_call_back(make_pump) -> None:
    """``silence_s`` 0 и -1 выключают колбэк; без ``on_silence`` положительный порог ничего не ломает."""
    for silence_s in (0.0, -1):
        mailbox, journal = _Mailbox(), _Journal()
        pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=silence_s)
        pump.set_keys({"cam_a": 30})
        _spin(1.0)
        pump.stop()
        assert journal.silences() == [], f"silence_s={silence_s}: {journal.entries}"

    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, silence_s=0.3)
    pump.set_keys({"cam_a": 30})
    _spin(1.0)  # исключение в слоте таймера уронило бы тест через перехват pytest-qt
    assert pump.stats()["cam_a"]["errors"] == 0


def test_steady_frames_report_nothing(make_pump) -> None:
    """Кадры каждые 50 мс — тишины нет; после остановки подачи первая запись в пределах 0,5..1,0 с."""
    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=0.5)
    pump.set_keys({"cam_a": 30})
    _feed(mailbox, "cam_a", 1.5)
    assert journal.sinks("cam_a") >= 20, "предпосылка: кадры действительно показывались"
    assert journal.silences() == [], journal.silences()

    _wait_for(lambda: bool(journal.silences()), "тишина после остановки кадров")
    first = journal.silences()[0]
    assert first[1] == "cam_a"
    assert first[2] is not None, journal.entries
    assert 0.5 <= first[2] <= 1.0, first


def test_silence_is_per_key(make_pump) -> None:
    """Кормится только ``cam_b``: тишина сообщается только про ``cam_a``."""
    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=0.3)
    pump.set_keys({"cam_a": 30, "cam_b": 30})
    _feed(mailbox, "cam_b", 1.5)

    assert journal.sinks("cam_b") >= 20, "предпосылка: cam_b действительно показывался"
    silences = journal.silences()
    assert len(silences) >= 1, "про cam_a нет ни одной записи"
    assert {e[1] for e in silences} == {"cam_a"}, silences


@pytest.mark.parametrize("how", ["returns_false", "raises"])
def test_unshown_frame_keeps_silence(make_pump, how) -> None:
    """Кадр, который ``sink`` не показал (``False`` или исключение), тишину не прерывает."""
    mailbox, journal = _Mailbox(), _Journal()

    def sink(key: str, item: Any) -> bool:
        journal.sink(key, item)
        if how == "raises":
            raise ValueError("кадр не показан")
        return False

    pump = make_pump(mailbox, sink, on_silence=journal.on_silence, silence_s=0.3)
    pump.set_keys({"cam_a": 30})
    _wait_for(
        lambda: any(e[2] is not None and int(e[2]) == 1 for e in journal.silences()),
        "запись о тишине с возрастом в 1 с",
    )
    mailbox.put("cam_a", {"n": 1})
    _wait_for(lambda: journal.sinks("cam_a") == 1, "кадр дошёл до sink")
    after = journal.entries.index(("sink", "cam_a")) + 1
    _wait_for(lambda: bool(journal.silences(after)), "запись о тишине после непоказанного кадра")

    next_age = journal.silences(after)[0][2]
    assert next_age is not None, journal.entries
    assert int(next_age) == 2, journal.entries
    assert journal.nones() == [], journal.entries
    stats = pump.stats()["cam_a"]
    if how == "returns_false":
        assert (stats["shown"], stats["errors"]) == (1, 0)  # shown считает и вызовы с False
    else:
        assert (stats["shown"], stats["errors"]) == (0, 1)


def test_stats_keys_unchanged(make_pump) -> None:
    """После тишины и кадра набор ключей ``stats()`` прежний."""
    mailbox, journal = _Mailbox(), _Journal()
    pump = make_pump(mailbox, journal.sink, on_silence=journal.on_silence, silence_s=0.3)
    pump.set_keys({"cam_a": 30})
    _wait_for(lambda: bool(journal.silences()), "запись о тишине")
    mailbox.put("cam_a", {"n": 1})
    _wait_for(lambda: journal.sinks("cam_a") == 1, "кадр после тишины в sink")

    assert set(pump.stats()["cam_a"]) == {"shown", "errors", "max_age_ms", "window_max_age_ms", "busy_ms_total"}
