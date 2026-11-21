# -*- coding: utf-8 -*-
"""Контракт I2 «свежесть» (Task 0.2, слепой tester): читатель ``telemetry_snapshot``.

Остальные читатели (``tree``, ``read_model``) — в
``multiprocess_framework/modules/state_store_module/tests/test_contract_freshness.py``.
Запись писателя приходит дельтой ``state.changed`` на корень ``processes.cam``; метка
``_fresh`` последней. Часы читателя подставные (``clock=`` драйвера); ``time.time`` не патчится.
Пары ``writer_gone`` здесь нет: у драйвера нет входа «воплощение живо» (0.13).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.conftest import wire_line
from multiprocess_framework.modules.state_store_module.core.freshness import stamp

P = "processes.cam"
S_ARGS = (1, 100.0, "a", 5.0)  # stamp(seq, src_ts, incarnation, tick_sec)


def _sub() -> dict[str, Any]:
    """Запись процесса; метка последней, как кладёт писатель (строится в теле теста: stamp — часть контракта)."""
    return {
        "state": {"fps": 0, "lat": 25.0},
        "workers": {"w": {"effective_hz": 5.0}},
        "_fresh": stamp(*S_ARGS),
    }


NO_DATA = {"class": "no_data", "value": None, "age_s": None}


def _delta(path: str, new_value: Any, old_value: Any = None) -> dict[str, Any]:
    return {
        "path": path,
        "old_value": old_value,
        "new_value": new_value,
        "source": "test",
        "timestamp": 0.0,
        "transaction_id": "t",
        "revision": 0,
    }


def _state_changed(*deltas: dict[str, Any]) -> bytes:
    return wire_line({"command": "state.changed", "data": {"deltas": list(deltas)}})


def _build_reader(now: list[float]):
    """Создать драйвер с подставными часами, записать ``(P, _sub())``, вернуть функцию чтения ``(key)``.

    Вызывается ВНУТРИ тела теста: отсутствие ``clock=`` у драйвера должно читаться в traceback.
    """
    d = BackendDriver(clock=lambda: now[0])
    d.dispatch_raw(_state_changed(_delta(P, _sub())))

    def read(key: str) -> dict[str, Any]:
        m = d.telemetry_snapshot(process="cam", metric=key)["metrics"]
        return m.get(f"{P}.{key}", NO_DATA)

    return read


@pytest.mark.parametrize("reader", ["telemetry_snapshot"])
def test_stopped_writer_is_stale(reader: str) -> None:
    """Писатель встал: до двух тактов (10 с) значение ``fresh``, после — ``stale`` с последним значением."""
    now = [109.9]
    read = _build_reader(now)

    now[0] = 109.9
    assert read("state.lat")["class"] == "fresh"

    now[0] = 110.1
    lat = read("state.lat")
    assert lat["class"] == "stale"
    assert lat["value"] == 25.0
    assert lat["age_s"] == pytest.approx(10.1)

    hz = read("workers.w.effective_hz")
    assert hz["class"] == "stale"
    assert hz["value"] == 5.0


@pytest.mark.parametrize("reader", ["telemetry_snapshot"])
def test_four_answers_distinct(reader: str) -> None:
    """Три пары (класс, значение) попарно разные: ноль не равен «нет данных», устаревшее не равно свежему."""
    now = [101.0]
    read = _build_reader(now)

    zero = read("state.fps")
    assert zero["class"] == "fresh"
    assert zero["value"] == 0
    assert zero["age_s"] == pytest.approx(1.0)

    absent = read("state.absent")
    assert absent == {"class": "no_data", "value": None, "age_s": None}

    now[0] = 110.1
    stale = read("state.lat")
    assert stale["class"] == "stale"
    assert stale["value"] == 25.0

    pairs = [
        (zero["class"], zero["value"]),
        (absent["class"], absent["value"]),
        (stale["class"], stale["value"]),
    ]
    assert len(set(pairs)) == 3
