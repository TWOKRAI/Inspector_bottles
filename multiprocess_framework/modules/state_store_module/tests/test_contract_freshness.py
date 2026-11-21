# -*- coding: utf-8 -*-
"""Контракт I2 «свежесть» (Task 0.2, слепой tester): остановленный писатель не выдаётся за живого.

Контракт читают два читателя фреймворка: ``tree`` (``handle_state_merge`` -> ``get_subtree``
-> ``read_value``) и ``read_model`` (``TelemetryReadModel.ingest`` -> ``read``). Читатель
``telemetry_snapshot`` проверяется в ``backend_ctl/tests/test_contract_freshness_reader.py``.

Запись писателя — одно слияние на корень процесса, метка ``_fresh`` последней:
``processes.cam`` -> ``{"state": {...}, "workers": {...}, "_fresh": S}``.
Часы читателя подставные: ``now`` — изменяемое значение теста; ``time.time`` не патчится.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import STATE_ENVELOPE_MARKER
from multiprocess_framework.modules.state_store_module.core.freshness import read_value, stamp
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

P = "processes.cam"
S_ARGS = (1, 100.0, "a", 5.0)  # stamp(seq, src_ts, incarnation, tick_sec)


def _sub() -> dict[str, Any]:
    """Запись процесса; метка последней, как кладёт писатель (строится в теле теста: stamp — часть контракта)."""
    return {
        "state": {"fps": 0, "lat": 25.0},
        "workers": {"w": {"effective_hz": 5.0}},
        "_fresh": stamp(*S_ARGS),
    }

# (key, alive_incarnation) -> {"class", "value", "age_s"}
type Reader = Callable[..., dict[str, Any]]


def _build_reader(reader: str, now: list[float]) -> Reader:
    """Создать читателя, записать ``(P, _sub())``, вернуть функцию чтения ``(key, alive)``.

    Вызывается ВНУТРИ тела теста: отсутствие API читателя должно читаться в traceback теста.
    """
    if reader == "tree":
        mgr = StateStoreManager(router=None, auto_register_ipc=False)
        resp = mgr.handle_state_merge(
            {"path": P, "data": _sub(), "source": "w", STATE_ENVELOPE_MARKER: True}
        )
        assert resp["status"] == "ok"

        def read_tree(key: str, alive: str | None = None) -> dict[str, Any]:
            return read_value(mgr.store.get_subtree(P), key, now[0], alive)

        return read_tree

    if reader == "read_model":
        rm = TelemetryReadModel(clock=lambda: now[0])
        rm.ingest(P, _sub())

        def read_rm(key: str, alive: str | None = None) -> dict[str, Any]:
            return rm.read(P, key, alive_incarnation=alive)

        return read_rm

    raise AssertionError(f"неизвестный читатель: {reader}")


@pytest.mark.parametrize("reader", ["tree", "read_model"])
def test_stopped_writer_is_stale(reader: str) -> None:
    """Писатель встал: до двух тактов (10 с) значение ``fresh``, после — ``stale`` с последним значением."""
    now = [109.9]
    read = _build_reader(reader, now)

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


@pytest.mark.parametrize("reader", ["tree", "read_model"])
def test_four_answers_distinct(reader: str) -> None:
    """Четыре ответа D1 — попарно разные пары (класс, значение): ноль не равен «нет данных»."""
    now = [101.0]
    read = _build_reader(reader, now)

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

    now[0] = 101.0
    gone = read("state.lat", "b")
    assert gone["class"] == "writer_gone"
    assert gone["value"] == 25.0
    assert gone["age_s"] == pytest.approx(1.0)

    pairs = [
        (zero["class"], zero["value"]),
        (absent["class"], absent["value"]),
        (stale["class"], stale["value"]),
        (gone["class"], gone["value"]),
    ]
    assert len(set(pairs)) == 4
