"""Тесты автора 4.8a: окно замера = дельта накопительных счётчиков (ревью п.3).

`pacer_late` и `shm.{bytes_written,bytes_read,stale_drops,torn_reads}` копятся с запуска
процесса, а не с t0 — без вычитания снимка на t0 «30-секундное» окно читается как 44 с.
`bytes_mapped` — размер отображения (текущее значение), вычитать его нельзя.
"""

from __future__ import annotations

from scripts.capacity_bench.fields import window


def _snap(pacer_late, written, read, mapped, stale, torn, hz=30.0):
    return {
        "hz": hz,
        "inner_cores": 0.5,
        "plugin_ms": {"p": 1.5},
        "queue_wait_ms": 2.0,
        "transport_ms": 3.0,
        "pacer_late": pacer_late,
        "shm": {
            "bytes_written": written,
            "bytes_read": read,
            "bytes_mapped": mapped,
            "stale_drops": stale,
            "torn_reads": torn,
        },
    }


def test_window_counters_are_deltas_mapped_is_current():
    before = _snap(pacer_late=100, written=1000, read=900, mapped=8192, stale=5, torn=1, hz=10.0)
    after = _snap(pacer_late=460, written=4000, read=3500, mapped=16384, stale=12, torn=1, hz=30.0)
    got = window(before, after)
    assert got["pacer_late"] == 360
    assert got["shm"] == {
        "bytes_written": 3000,
        "bytes_read": 2600,
        "bytes_mapped": 16384,  # текущее значение, не разность (16384 - 8192 было бы ошибкой)
        "stale_drops": 7,
        "torn_reads": 0,
    }
    assert got["hz"] == 30.0  # не счётчик: берётся из after
    assert got["plugin_ms"] == {"p": 1.5}


def test_window_none_on_either_side_gives_none():
    after = _snap(10, 100, 100, 64, 1, 0)
    before = _snap(None, None, 50, 64, 0, 0)
    got = window(before, after)
    assert got["pacer_late"] is None
    assert got["shm"]["bytes_written"] is None
    assert got["shm"]["bytes_read"] == 50


def test_window_shm_missing_on_a_side():
    after = _snap(10, 100, 100, 64, 1, 0)
    # нет базы -> счётчики None (абсолют с запуска процесса не выдаётся за окно), размер отображения жив
    got = window(dict(after, shm=None), after)["shm"]
    assert got == {
        "bytes_written": None,
        "bytes_read": None,
        "bytes_mapped": 64,
        "stale_drops": None,
        "torn_reads": None,
    }
    assert window(after, dict(after, shm=None))["shm"] is None


def test_window_does_not_mutate_inputs():
    before = _snap(1, 10, 10, 64, 0, 0)
    after = _snap(5, 30, 30, 64, 2, 0)
    snap_after = {**after, "shm": dict(after["shm"])}
    window(before, after)
    assert after == snap_after
