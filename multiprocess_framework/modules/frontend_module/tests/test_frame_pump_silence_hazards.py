# -*- coding: utf-8 -*-
"""Тесты опасности колбэка тишины ``FramePump`` (W2-c), написаны автором кода.

Purpose: цена выключенного режима (ни одного чтения часов), ``stop()`` изнутри ``on_silence`` и
``sink``, исключение ``on_silence``, снятие ключа с объявленной тишиной.

Всё, что может зависнуть, ограничено: ``stats()`` из колбэка зовётся из daemon-потока с ``join``,
циклы событий — с дедлайном, на весь тест — ``faulthandler``.
"""

from __future__ import annotations

import faulthandler
import os
import threading
import time
import types
from collections.abc import Callable
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # до импорта PySide6

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from multiprocess_framework.modules.frontend_module.bridge import frame_pump as frame_pump_mod  # noqa: E402

__all__: list[str] = []

_DEADLINE_S = 3.0
_JOIN_S = 1.0
_HARD_DEADLINE_S = 30.0


@pytest.fixture(autouse=True)
def _hard_deadline():
    """Аварийный дедлайн на случай, если зависнет сам ``processEvents``."""
    faulthandler.dump_traceback_later(_HARD_DEADLINE_S, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


class _Mailbox:
    """Фейк ящика: последний кадр на ключ; считает вызовы ``take``."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self.takes = 0

    def put(self, key: str, item: Any) -> None:
        self._items[key] = item

    def take(self, key: str) -> tuple[Any, float] | None:
        self.takes += 1
        if key not in self._items:
            return None
        return self._items.pop(key), 0.0

    def pending_keys(self) -> list[str]:
        return list(self._items)


@pytest.fixture
def make_pump(qtbot: Any):  # noqa: ARG001
    made: list[Any] = []

    def factory(mailbox: Any, sink: Any, **kwargs: Any) -> Any:
        pump = frame_pump_mod.FramePump(mailbox, sink, **kwargs)
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
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        _tick()


def _wait_for(predicate: Callable[[], bool], what: str) -> None:
    end = time.perf_counter() + _DEADLINE_S
    while not predicate():
        assert time.perf_counter() < end, f"не дождались за {_DEADLINE_S} с: {what}"
        _tick()


def _stats_is_free(pump: Any) -> bool:
    """``stats()`` из соседнего потока возвращается: замок насоса во время колбэка не взят."""
    probe = threading.Thread(target=pump.stats, daemon=True)
    probe.start()
    probe.join(timeout=_JOIN_S)
    return not probe.is_alive()


def test_disabled_reads_no_clock(make_pump, monkeypatch) -> None:
    """Выключенный механизм: ``set_keys`` и 20 пустых тиков не читают часы ни разу."""
    reads: list[None] = []

    def perf_counter() -> float:
        reads.append(None)
        return 100.0

    monkeypatch.setattr(frame_pump_mod, "time", types.SimpleNamespace(perf_counter=perf_counter))

    def on_silence(key: str, age_s: float | None) -> None:  # noqa: ARG001
        raise AssertionError("выключенный колбэк позван")

    for kwargs in (
        {},
        {"silence_s": 0.3},
        {"on_silence": on_silence, "silence_s": 0.0},
        {"on_silence": on_silence, "silence_s": -1},
    ):
        mailbox = _Mailbox()
        pump = make_pump(mailbox, lambda key, item: None, **kwargs)
        pump.set_keys({"a": 60})
        _wait_for(lambda: mailbox.takes >= 20, "20 пустых тиков")
        pump.stop()
        assert len(reads) == 0, f"{kwargs}: чтений часов {len(reads)}"

    # контроль: подмена часов действует — включённый механизм их читает
    pump = make_pump(_Mailbox(), lambda key, item: None, on_silence=on_silence, silence_s=0.3)
    pump.set_keys({"a": 60})
    assert len(reads) == 1


@pytest.mark.parametrize("stop_in", ["on_silence", "sink"])
def test_stop_inside_on_silence_ends_calls(make_pump, stop_in) -> None:
    """``stop()`` из ``on_silence`` или из ``sink`` кадра после тишины: дальше ни одного вызова.

    Второй случай — в том числе без ``on_silence(key, None)``.
    """
    mailbox = _Mailbox()
    calls: list[tuple[Any, ...]] = []
    free: list[bool] = []
    holder: dict[str, Any] = {}

    def stop_from_callback() -> None:
        pump = holder["pump"]
        free.append(_stats_is_free(pump))
        if free[-1]:  # под взятым замком stop() из того же потока завис бы
            pump.stop()

    def sink(key: str, item: Any) -> None:  # noqa: ARG001
        calls.append(("sink", key))
        if stop_in == "sink":
            stop_from_callback()

    def on_silence(key: str, age_s: float | None) -> None:
        calls.append(("silence", key, age_s is None))
        if stop_in == "on_silence":
            stop_from_callback()

    pump = holder["pump"] = make_pump(mailbox, sink, on_silence=on_silence, silence_s=0.2)
    pump.set_keys({"a": 60, "b": 60})
    if stop_in == "on_silence":
        _wait_for(lambda: bool(calls), "первая тишина")
        expected = list(calls)
        assert len(expected) == 1, expected
        mailbox.put("a", {"n": 1})
        mailbox.put("b", {"n": 1})
    else:
        _wait_for(lambda: len(calls) >= 2, "тишина обоих ключей")
        mailbox.put("a", {"n": 1})
        _wait_for(lambda: ("sink", "a") in calls, "кадр после тишины в sink")
        expected = list(calls)
        assert expected[-1] == ("sink", "a"), expected
        mailbox.put("b", {"n": 1})
    _spin(1.3)  # дольше следующей целой секунды тишины

    assert free == [True]
    assert calls == expected


def test_on_silence_exception_on_number_and_none(make_pump, monkeypatch) -> None:
    """``on_silence`` бросает на числе и на ``None``: ``errors`` = 2, кадр показан, насос жив."""
    records: list[tuple[Any, ...]] = []

    class _Rec:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            records.append(args)

    monkeypatch.setattr(frame_pump_mod, "_log", _Rec())
    mailbox = _Mailbox()
    ages: list[float | None] = []
    shown: list[str] = []
    free: list[bool] = []
    holder: dict[str, Any] = {}

    def on_silence(key: str, age_s: float | None) -> None:  # noqa: ARG001
        ages.append(age_s)
        free.append(_stats_is_free(holder["pump"]))
        if free[-1]:  # под взятым замком обработка исключения зависла бы
            raise ValueError("boom")

    pump = holder["pump"] = make_pump(
        mailbox, lambda key, item: shown.append(key), on_silence=on_silence, silence_s=0.3
    )
    pump.set_keys({"a": 60})
    _wait_for(lambda: len(ages) == 1, "тишина")
    mailbox.put("a", {"n": 1})
    _wait_for(lambda: None in ages, "on_silence(key, None)")

    st = pump.stats()["a"]
    assert (st["errors"], st["shown"]) == (2, 1)
    assert shown == ["a"]
    assert free == [True, True]
    assert len(records) == 1, records  # свой дроссель: одна строка на два сбоя
    assert "on_silence" in records[0][0]

    _wait_for(lambda: len(ages) == 3, "насос жив: новая тишина после сбоев")
    assert ages[2] is not None


@pytest.mark.parametrize("how", ["returns_false", "raises"])
def test_never_empty_mailbox_unshown_frames_still_report_silence(make_pump, how) -> None:
    """Ящик всегда полон, ``sink`` кадр не показывает: тишина всё равно сообщается, ``None`` нет."""

    class _AlwaysFull(_Mailbox):
        def take(self, key: str) -> tuple[Any, float] | None:
            return {"key": key}, 0.0

    sinks: list[str] = []
    ages: list[float | None] = []

    def sink(key: str, item: Any) -> bool:  # noqa: ARG001
        sinks.append(key)
        if how == "raises":
            raise ValueError("кадр не показан")
        return False

    pump = make_pump(_AlwaysFull(), sink, on_silence=lambda key, age: ages.append(age), silence_s=0.3)
    pump.set_keys({"a": 30})
    _wait_for(lambda: len(ages) >= 2, "две записи о тишине при полном ящике")

    assert None not in ages, ages
    assert [int(age) for age in ages] == [0, 1], ages
    assert len(sinks) >= 10, "предпосылка: кадры действительно шли в sink"


def test_dropped_key_forgets_silence(make_pump) -> None:
    """Ключ снят с объявленной тишиной и заведён заново: его первый кадр не даёт ``None``."""
    mailbox = _Mailbox()
    ages: list[float | None] = []
    shown: list[str] = []
    pump = make_pump(
        mailbox, lambda key, item: shown.append(key), on_silence=lambda key, age: ages.append(age), silence_s=0.3
    )
    pump.set_keys({"a": 60})
    _wait_for(lambda: len(ages) == 1, "тишина")
    pump.set_keys({})
    assert len(ages) == 1, "снятие ключа позвало колбэк"
    pump.set_keys({"a": 60})
    mailbox.put("a", {"n": 1})
    _wait_for(lambda: shown == ["a"], "кадр нового ключа")

    assert None not in ages, ages
