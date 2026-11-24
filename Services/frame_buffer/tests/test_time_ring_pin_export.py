# -*- coding: utf-8 -*-
"""Закрепление диапазона, поиск по группе и экспорт TimeRing (Task T9b), слепые приёмочные тесты.

Purpose: проверить pin/unpin (включающие границы, будущие кадры, бюджет закреплённых байт,
жёсткий потолок max_bytes), find_group и export (байты блока совпадают с принятыми) по критериям
приёмки, до реализации.

Ожидаемые значения — литералы из ACCEPTANCE, не вычисляются из кода под тестом. Тесты, которые
могут зависнуть (цикл освобождения пинов), идут в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import functools
import struct
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from Services.frame_buffer.time_ring import TimeRing

__all__ = []

STEP = 100_000_000  # 10 Гц: кадр i имеет capture_ns == i * STEP
RECORD = "<QIqdqqqI"
BIG = 10**13  # конец пина "до бесконечности", вмещается в i64
PREV, NEXT = "prev", "next"


def _deadline(seconds: float = 20.0):
    """Прогнать тело теста в daemon-потоке; зависание = падение теста, а не зависший прогон."""

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            box: dict = {}

            def run() -> None:
                try:
                    fn(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 - пробрасываем в основной поток
                    box["exc"] = exc

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            thread.join(seconds)
            if thread.is_alive():
                pytest.fail(f"{fn.__name__} завис дольше {seconds} с (вероятно, бесконечный цикл освобождения)")
            if "exc" in box:
                raise box["exc"]

        return wrapper

    return decorate


def _ring(buffer_seconds: float = 1, max_bytes: int = 1_000_000, pin_max_bytes: int = 1_000_000) -> TimeRing:
    return TimeRing(buffer_seconds=buffer_seconds, max_bytes=max_bytes, pin_max_bytes=pin_max_bytes)


def _frame(ring: TimeRing, i: int, size: int = 1000, **kw) -> None:
    """Кадр i: capture_ns == i * STEP, seq == i + 1."""
    ring.append(capture_ns=i * STEP, capture_ts=1700000000.0, payload=bytes([(i + 1) % 256]) * size, seq=i + 1, **kw)


def _stream(ring: TimeRing, first: int, last: int, size: int = 1000) -> None:
    for i in range(first, last + 1):
        _frame(ring, i, size)


def _ns_at(ring: TimeRing, t_ns: int, mode: str) -> int | None:
    found = ring.at(t_ns, mode)
    return None if found is None else found["capture_ns"]


def _seq_at(ring: TimeRing, t_ns: int, mode: str) -> int | None:
    found = ring.at(t_ns, mode)
    return None if found is None else found["seq"]


def _records(index: bytes) -> list[tuple]:
    return [struct.unpack_from(RECORD, index, 56 * k) for k in range(len(index) // 56)]


# ---------------------------------------------------------------------------------------------
# pin / unpin
# ---------------------------------------------------------------------------------------------


@_deadline()
def test_pinned_range_survives_eviction():
    """Буфер 1 с, 10 Гц; pin(0, 3e8) при четырёх кадрах i 0..3; потом кадры до i=30."""
    ring = _ring()
    _stream(ring, 0, 3)
    ring.pin(0, 300_000_000, "e1")
    _stream(ring, 4, 30)
    assert ring.range()["frames"] == 15  # окно i 20..30 (11 кадров) + 4 закреплённых
    assert ring.at(0, PREV)["seq"] == 1


@_deadline()
def test_pinned_range_survives_exactly_its_frames():
    ring = _ring()
    _stream(ring, 0, 3)
    ring.pin(0, 300_000_000, "e1")
    _stream(ring, 4, 30)
    assert _ns_at(ring, 300_000_000, PREV) == 300_000_000  # последний закреплённый кадр
    assert _ns_at(ring, 1_900_000_000, PREV) == 300_000_000  # кадров i 4..19 в кольце нет
    assert _ns_at(ring, 300_000_001, NEXT) == 2_000_000_000  # следующий за закреплёнными — окно i=20


@_deadline()
def test_pinned_frames_count_toward_bytes_held():
    ring = _ring()
    _stream(ring, 0, 3)
    ring.pin(0, 300_000_000, "e1")
    _stream(ring, 4, 30)
    assert ring.stats()["bytes_held"] == 15_000


@_deadline()
def test_pin_covers_future_frames():
    """pin(500 мс, 900 мс) поставлен, когда кадров 600 и 700 ещё нет; они приходят после."""
    ring = _ring()
    _stream(ring, 0, 5)  # кадры 0..500 мс
    ring.pin(500_000_000, 900_000_000, "e")
    _stream(ring, 6, 30)  # кадры 600 мс .. 3000 мс
    assert _ns_at(ring, 600_000_000, PREV) == 600_000_000
    assert _ns_at(ring, 700_000_000, PREV) == 700_000_000


@_deadline()
def test_pin_covers_future_frames_and_nothing_outside_the_interval():
    ring = _ring()
    _stream(ring, 0, 5)
    ring.pin(500_000_000, 900_000_000, "e")
    _stream(ring, 6, 30)
    assert ring.range()["frames"] == 16  # окно i 20..30 (11) + закреплённые 500..900 мс (5)
    assert _ns_at(ring, 499_999_999, PREV) is None  # кадры до начала интервала вытеснены
    assert _ns_at(ring, 1_999_999_999, PREV) == 900_000_000  # после 900 мс до окна — пусто


@_deadline()
def test_pin_interval_inclusive_on_both_ends():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(300_000_000, 600_000_000, "p")
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 15  # окно (11) + кадры 300, 400, 500, 600 мс
    assert _ns_at(ring, 299_999_999, PREV) is None  # кадр 200 мс не закреплён
    assert _ns_at(ring, 300_000_000, NEXT) == 300_000_000  # левый конец включён
    assert _ns_at(ring, 600_000_000, PREV) == 600_000_000  # правый конец включён
    assert _ns_at(ring, 1_999_999_999, PREV) == 600_000_000  # кадр 700 мс не закреплён


@_deadline()
def test_pin_single_instant_interval_is_allowed():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(500_000_000, 500_000_000, "one")
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 12  # окно (11) + один кадр 500 мс
    assert _ns_at(ring, 1_999_999_999, PREV) == 500_000_000


def test_pin_reversed_interval_raises_value_error():
    ring = _ring()
    _stream(ring, 0, 3)
    with pytest.raises(ValueError):
        ring.pin(300_000_000, 100_000_000, "bad")


@_deadline()
def test_repin_same_tag_replaces_interval():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(200_000_000, 500_000_000, "a")
    ring.pin(600_000_000, 800_000_000, "a")  # тот же тег: интервал заменён
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 14  # окно (11) + 600, 700, 800 мс
    assert _ns_at(ring, 1_999_999_999, PREV) == 800_000_000
    assert _ns_at(ring, 599_999_999, PREV) is None  # старый интервал 200..500 мс больше не защищён


@_deadline()
def test_unpin_releases_range():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(200_000_000, 500_000_000, "p")
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 15  # окно (11) + кадры 200..500 мс
    ring.unpin("p")
    _frame(ring, 31)  # вытеснение идёт при append
    assert ring.range()["frames"] == 11  # окно i 21..31
    assert _ns_at(ring, 2_099_999_999, PREV) is None


@_deadline()
def test_unpin_unknown_tag_is_noop():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(200_000_000, 500_000_000, "p")
    ring.unpin("no-such-tag")
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 15
    assert ring.stats()["pins_released"] == 0


@_deadline()
def test_two_overlapping_pins_unpin_one_keeps_other():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(200_000_000, 500_000_000, "A")
    ring.pin(400_000_000, 800_000_000, "B")
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 18  # окно (11) + объединение 200..800 мс (7)
    ring.unpin("A")
    _frame(ring, 31)
    assert ring.range()["frames"] == 16  # окно i 21..31 (11) + 400..800 мс (5)
    assert _ns_at(ring, 300_000_000, PREV) is None  # кадры 200 и 300 мс держал только A
    assert _ns_at(ring, 400_000_000, PREV) == 400_000_000  # кадр 400 мс держит B
    assert _ns_at(ring, 500_000_000, PREV) == 500_000_000  # кадр 500 мс был под обоими
    assert _ns_at(ring, 1_999_999_999, PREV) == 800_000_000


@_deadline()
def test_overlapping_pins_counted_once_in_pin_budget():
    """Кадры двух пересекающихся пинов в закреплённых байтах считаются один раз: 7000, не 9000."""
    ring = _ring(max_bytes=100_000, pin_max_bytes=8_000)
    _stream(ring, 0, 9)
    ring.pin(200_000_000, 500_000_000, "A")  # 4 кадра = 4000
    ring.pin(400_000_000, 800_000_000, "B")  # объединение 200..800 мс = 7 кадров = 7000 <= 8000
    _stream(ring, 10, 30)
    assert ring.stats()["pins_released"] == 0
    assert ring.range()["frames"] == 18


# ---------------------------------------------------------------------------------------------
# Бюджет закреплённых байт и потолок max_bytes
# ---------------------------------------------------------------------------------------------


@_deadline()
def test_pin_budget_exceeded_oldest_pin_released_and_counted():
    """pin_max_bytes 3000, два пина по 2000. Самый старый — по порядку вызова pin, не по времени."""
    ring = _ring(max_bytes=100_000, pin_max_bytes=3_000)
    _stream(ring, 0, 9)
    ring.pin(300_000_000, 400_000_000, "first")  # вызван первым, 2 кадра = 2000
    ring.pin(0, 100_000_000, "second")  # вызван вторым (но раньше по времени), итого 4000 > 3000
    _stream(ring, 10, 30)
    assert ring.stats()["pins_released"] == 1
    assert ring.range()["frames"] == 13  # окно (11) + кадры второго пина 0 и 100 мс
    assert _ns_at(ring, 100_000_000, PREV) == 100_000_000
    assert _ns_at(ring, 0, PREV) == 0
    assert _ns_at(ring, 300_000_000, NEXT) == 2_000_000_000  # кадры первого пина освобождены и вытеснены


@_deadline()
def test_pin_budget_exceeded_two_pins_released_counts_only_what_was_needed():
    ring = _ring(max_bytes=100_000, pin_max_bytes=3_000)
    _stream(ring, 0, 9)
    ring.pin(0, 100_000_000, "a")  # 2000
    ring.pin(300_000_000, 400_000_000, "b")  # итого 4000 > 3000: освобождается a, остаётся 2000
    ring.pin(600_000_000, 600_000_000, "c")  # 2000 + 1000 = 3000 <= 3000: освобождать нечего
    assert ring.stats()["pins_released"] == 1


@_deadline()
def test_future_frames_beyond_pin_budget_release_the_pin():
    """Пин на всё будущее: на четвёртом кадре закреплено 4000 > 3000, пин освобождается."""
    ring = _ring(max_bytes=100_000, pin_max_bytes=3_000)
    ring.pin(0, BIG, "big")
    _stream(ring, 0, 30)
    assert ring.stats()["pins_released"] == 1
    assert ring.range()["frames"] == 11  # после освобождения кольцо живёт по времени: окно i 20..30


@_deadline()
def test_full_pinned_ring_releases_oldest_pin_for_new_frame():
    """pin_max_bytes == max_bytes == 3000, всё кольцо закреплено: новому кадру нужно место."""
    ring = _ring(buffer_seconds=100, max_bytes=3_000, pin_max_bytes=3_000)
    ring.pin(0, BIG, "all")
    _stream(ring, 0, 2)  # 3000 байт, всё закреплено, 3000 <= pin_max_bytes
    assert ring.stats()["pins_released"] == 0
    _frame(ring, 3)
    stats = ring.stats()
    assert stats["pins_released"] == 1
    assert stats["bytes_held"] == 3_000
    assert stats["frames"] == 3
    assert ring.range()["t_min_ns"] == 100_000_000  # вытеснен самый старый кадр
    assert ring.range()["t_max_ns"] == 300_000_000


@_deadline()
def test_unpinned_new_frame_on_full_pinned_ring_is_kept_and_oldest_pin_released():
    """Новый кадр вне пина, всё кольцо закреплено и pin_max_bytes == max_bytes: кадр не теряется."""
    ring = _ring(buffer_seconds=100, max_bytes=3_000, pin_max_bytes=3_000)
    _stream(ring, 0, 2)
    ring.pin(0, 200_000_000, "all")  # кадры 0, 100, 200 мс: 3000 байт, всё закреплено
    _frame(ring, 3)  # кадр 300 мс вне интервала пина
    stats = ring.stats()
    assert stats["pins_released"] == 1
    assert stats["bytes_held"] == 3_000
    assert stats["frames"] == 3
    assert ring.at(300_000_000, PREV)["seq"] == 4  # новый кадр на месте
    assert ring.range()["t_min_ns"] == 100_000_000  # вытеснен самый старый кадр бывшего пина


@_deadline()
def test_full_pinned_ring_with_two_pins_releases_only_the_oldest_pin():
    ring = _ring(buffer_seconds=100, max_bytes=3_000, pin_max_bytes=3_000)
    ring.pin(0, 100_000_000, "A")  # первый по порядку вызова
    ring.pin(200_000_000, BIG, "B")
    _stream(ring, 0, 2)  # кадры 0 и 100 мс под A, кадр 200 мс под B: 3000, всё закреплено
    _frame(ring, 3)  # кадр 300 мс под B: места нет, освобождается A
    stats = ring.stats()
    assert stats["pins_released"] == 1
    assert stats["bytes_held"] == 3_000
    assert ring.range()["t_min_ns"] == 100_000_000  # кадр 0 вытеснен, кадр 100 мс (бывший под A) остался
    _frame(ring, 4)  # кадр 400 мс под B: незакреплённый кадр 100 мс уходит, B жив
    assert ring.stats()["pins_released"] == 1
    assert ring.range()["t_min_ns"] == 200_000_000
    assert ring.range()["frames"] == 3


@settings(max_examples=150, deadline=None)
@given(
    ops=st.lists(
        st.one_of(
            st.tuples(st.just("append"), st.integers(min_value=1, max_value=2_000)),
            st.tuples(
                st.just("pin"),
                st.integers(min_value=0, max_value=20),
                st.integers(min_value=0, max_value=12),
                st.integers(min_value=0, max_value=2),
            ),
            st.tuples(st.just("unpin"), st.integers(min_value=0, max_value=2)),
        ),
        min_size=1,
        max_size=80,
    )
)
@_deadline(60.0)
def test_max_bytes_never_exceeded_with_pins(ops):
    """Жёсткий потолок: bytes_held и пик не выше max_bytes при любых пинах; счётчик пинов не убывает."""
    max_bytes = 4_000
    ring = _ring(buffer_seconds=1, max_bytes=max_bytes, pin_max_bytes=3_000)
    i = 0
    released = 0
    for op in ops:
        if op[0] == "append":
            _frame(ring, i, size=op[1])
            i += 1
        elif op[0] == "pin":
            _, start, length, tag = op
            ring.pin(start * STEP, (start + length) * STEP, f"t{tag}")
        else:
            ring.unpin(f"t{op[1]}")
        stats = ring.stats()
        assert stats["bytes_held"] <= max_bytes
        assert stats["bytes_held_peak"] <= max_bytes
        assert stats["pins_released"] >= released
        released = stats["pins_released"]
        assert ring.range()["frames"] == stats["frames"]


# ---------------------------------------------------------------------------------------------
# find_group
# ---------------------------------------------------------------------------------------------


def _group_ring() -> TimeRing:
    ring = _ring(buffer_seconds=100)
    ring.append(capture_ns=100, capture_ts=1.0, payload=b"a", seq=1, group_id=7)
    ring.append(capture_ns=200, capture_ts=2.0, payload=b"b", seq=2, group_id=9)
    ring.append(capture_ns=300, capture_ts=3.0, payload=b"c", seq=3, group_id=7)
    ring.append(capture_ns=400, capture_ts=4.0, payload=b"d", seq=4, group_id=None)
    return ring


def test_find_group_returns_frames_of_group():
    ring = _group_ring()
    found = ring.find_group(7)
    assert [(f["capture_ns"], f["seq"]) for f in found] == [(100, 1), (300, 3)]
    assert ring.find_group(5) == []
    assert ring.find_group(None) == []


def test_find_group_returns_at_style_dicts():
    found = _group_ring().find_group(7)
    assert found[1] == {
        "payload": b"c",
        "capture_ns": 300,
        "capture_ts": 3.0,
        "seq": 3,
        "device_frame_num": None,
        "group_id": 7,
        "flags": 0,
    }


def test_find_group_orders_by_capture_ns_then_seq():
    ring = _ring(buffer_seconds=100)
    ring.append(capture_ns=100, capture_ts=1.0, payload=b"a", seq=1, group_id=7)
    ring.append(capture_ns=300, capture_ts=3.0, payload=b"b", seq=2, group_id=7)
    ring.append(capture_ns=300, capture_ts=3.0, payload=b"c", seq=3, group_id=7)
    ring.append(capture_ns=300, capture_ts=3.0, payload=b"d", seq=4, group_id=7)
    assert [f["seq"] for f in ring.find_group(7)] == [1, 2, 3, 4]


def test_find_group_zero_is_a_real_group_distinct_from_none():
    ring = _ring(buffer_seconds=100)
    ring.append(capture_ns=100, capture_ts=1.0, payload=b"a", seq=1, group_id=0)
    ring.append(capture_ns=200, capture_ts=2.0, payload=b"b", seq=2)
    assert [f["seq"] for f in ring.find_group(0)] == [1]


@_deadline()
def test_find_group_excludes_evicted_frames():
    ring = _ring(buffer_seconds=1)
    ring.append(capture_ns=0, capture_ts=1.0, payload=b"a", seq=1, group_id=7)
    ring.append(capture_ns=5_000_000_000, capture_ts=2.0, payload=b"b", seq=2, group_id=7)
    assert [f["seq"] for f in ring.find_group(7)] == [2]


@_deadline()
def test_find_group_includes_pinned_frames_that_outlive_the_buffer():
    ring = _ring(buffer_seconds=1)
    ring.append(capture_ns=0, capture_ts=1.0, payload=b"a", seq=1, group_id=7)
    ring.pin(0, 0, "keep")
    ring.append(capture_ns=5_000_000_000, capture_ts=2.0, payload=b"b", seq=2, group_id=7)
    assert [f["seq"] for f in ring.find_group(7)] == [1, 2]


# ---------------------------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------------------------

# Литералы: (capture_ns, seq, payload). Разные длины и разные байты.
EXPORT_FRAMES = [
    (100, 1, b"AAAAAAAAAA"),
    (200, 2, b"bbb"),
    (200, 3, b"CCCCCCC"),
    (300, 4, b"dddddddddddd"),
    (400, 5, b"EEEEE"),
]


def _export_ring() -> TimeRing:
    ring = _ring(buffer_seconds=100)
    for ns, seq, payload in EXPORT_FRAMES:
        ring.append(capture_ns=ns, capture_ts=ns / 1.0, payload=payload, seq=seq)
    return ring


def test_export_bytes_identical_to_appended():
    exported = _export_ring().export(0, 1000)
    blob, index = exported["blob"], exported["index"]
    assert len(index) == 5 * 56
    expected = [b"AAAAAAAAAA", b"bbb", b"CCCCCCC", b"dddddddddddd", b"EEEEE"]
    for record, payload in zip(_records(index), expected, strict=True):
        offset, length = record[0], record[1]
        assert blob[offset : offset + length] == payload


def test_export_returns_only_blob_and_index_as_bytes():
    exported = _export_ring().export(0, 1000)
    assert set(exported) == {"blob", "index"}
    assert isinstance(exported["blob"], bytes)
    assert isinstance(exported["index"], bytes)


def test_export_blob_is_payloads_back_to_back_from_zero():
    exported = _export_ring().export(0, 1000)
    assert exported["blob"] == b"AAAAAAAAAAbbbCCCCCCCddddddddddddEEEEE"
    offsets = [(r[0], r[1]) for r in _records(exported["index"])]
    assert offsets == [(0, 10), (10, 3), (13, 7), (20, 12), (32, 5)]


def test_export_index_records_carry_frame_metadata_in_ring_order():
    index = _export_ring().export(0, 1000)["index"]
    assert [(r[2], r[4]) for r in _records(index)] == [(100, 1), (200, 2), (200, 3), (300, 4), (400, 5)]


def test_export_bounds_are_inclusive_on_both_ends():
    ring = _export_ring()
    inner = ring.export(200, 300)
    assert [(r[2], r[4]) for r in _records(inner["index"])] == [(200, 2), (200, 3), (300, 4)]
    assert inner["blob"] == b"bbbCCCCCCCdddddddddddd"
    exact = ring.export(200, 200)
    assert [r[4] for r in _records(exact["index"])] == [2, 3]


def test_export_offsets_restart_from_zero_for_a_subrange():
    index = _export_ring().export(300, 400)["index"]
    assert [(r[0], r[1]) for r in _records(index)] == [(0, 12), (12, 5)]


@pytest.mark.parametrize(("t0", "t1"), [(1000, 2000), (0, 50), (101, 199)])
def test_export_empty_range(t0, t1):
    assert _export_ring().export(t0, t1) == {"blob": b"", "index": b""}


def test_export_of_empty_ring():
    assert _ring().export(0, 1000) == {"blob": b"", "index": b""}


def test_export_does_not_change_the_ring():
    ring = _export_ring()
    before = ring.stats()
    ring.export(0, 1000)
    ring.export(200, 300)
    assert ring.stats() == before
    assert ring.range() == {"t_min_ns": 100, "t_max_ns": 400, "frames": 5, "gaps": []}
    assert ring.at(300, PREV)["payload"] == b"dddddddddddd"


def test_export_roundtrips_through_the_reader():
    from Services.frame_buffer.segment import read_segment

    exported = _export_ring().export(200, 400)
    records = read_segment(exported["blob"], exported["index"])
    assert [(r["capture_ns"], r["seq"], r["payload"]) for r in records] == [
        (200, 2, b"bbb"),
        (200, 3, b"CCCCCCC"),
        (300, 4, b"dddddddddddd"),
        (400, 5, b"EEEEE"),
    ]
