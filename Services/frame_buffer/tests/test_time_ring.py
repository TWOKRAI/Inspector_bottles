# -*- coding: utf-8 -*-
"""Кольцо кадров по времени TimeRing (Task T9a), слепые приёмочные тесты.

Purpose: проверить публичный контракт TimeRing (вытеснение по времени и по байтам, доступ at(),
range(), разрывы seq, отказы append, счётчики stats()) по критериям приёмки, до реализации.

Ожидаемые значения — литералы из ACCEPTANCE, не вычисляются из кода под тестом. Число кадров и
счётчики читаются через stats(). Тесты, которые могут зависнуть, идут в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import functools
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from Services.frame_buffer.time_ring import TimeRing

__all__ = []

MS = 1_000_000  # одна миллисекунда в наносекундах
NEAREST, PREV, NEXT = "nearest", "prev", "next"
AT_KEYS = {"payload", "capture_ns", "capture_ts", "seq", "device_frame_num", "group_id", "flags"}


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
                pytest.fail(f"{fn.__name__} завис дольше {seconds} с (вероятно, бесконечный цикл вытеснения)")
            if "exc" in box:
                raise box["exc"]

        return wrapper

    return decorate


def _ring(buffer_seconds: float = 10, max_bytes: int = 1_000_000, pin_max_bytes: int = 500_000) -> TimeRing:
    return TimeRing(buffer_seconds=buffer_seconds, max_bytes=max_bytes, pin_max_bytes=pin_max_bytes)


def _add(ring: TimeRing, ns: int, seq: int, size: int = 100, **kw) -> None:
    ring.append(capture_ns=ns, capture_ts=1700000000.0, payload=bytes([seq % 256]) * size, seq=seq, **kw)


def _at(ring: TimeRing, t_ns: int, mode: str) -> dict | None:
    return ring.at(t_ns, mode)


def _seq_at(ring: TimeRing, t_ns: int, mode: str) -> int | None:
    found = ring.at(t_ns, mode)
    return None if found is None else found["seq"]


def _ns_at(ring: TimeRing, t_ns: int, mode: str) -> int | None:
    found = ring.at(t_ns, mode)
    return None if found is None else found["capture_ns"]


def _fill_pairs(ring: TimeRing, pairs: list[tuple[int, int]]) -> None:
    for ns, seq in pairs:
        _add(ring, ns, seq)


# Вход из ACCEPTANCE: (150, 3) отвергается (пара меньше (200, 2)), (200, 4) принимается.
PAIRS_WITH_REJECT = [(100, 1), (200, 2), (150, 3), (200, 4), (300, 5)]


# ---------------------------------------------------------------------------------------------
# Вытеснение по времени
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("start_ns", [0, 1, 7_000_000_000_123, 10**17])
@_deadline()
def test_evicts_older_than_buffer_seconds(start_ns):
    """25 Гц, 400 кадров, буфер 10 с: осталось 251 при любом start (кадры i 149..399)."""
    ring = _ring(buffer_seconds=10, max_bytes=1_000_000, pin_max_bytes=500_000)
    for i in range(400):
        _add(ring, start_ns + i * 40_000_000, i + 1)
    assert ring.stats()["frames"] == 251


@_deadline()
def test_time_eviction_keeps_frame_exactly_at_buffer_boundary():
    """Граница ВКЛЮЧАЮЩАЯ: самый старый оставшийся кадр лежит ровно на newest - 10 с."""
    ring = _ring()
    for i in range(400):
        _add(ring, i * 40_000_000, i + 1)
    rng = ring.range()
    assert rng["t_min_ns"] == 5_960_000_000  # кадр i=149
    assert rng["t_max_ns"] == 15_960_000_000  # кадр i=399


@_deadline()
def test_time_eviction_counts_only_time_evictions():
    ring = _ring()
    for i in range(400):
        _add(ring, i * 40_000_000, i + 1)
    stats = ring.stats()
    assert stats["evicted_by_time"] == 149
    assert stats["evicted_by_bytes"] == 0
    assert stats["bytes_held"] == 25_100


@pytest.mark.parametrize(
    ("newest_ns", "expected_frames"),
    [
        (1_000_000_000, 2),  # newest - buffer == 0: кадр 0 остаётся
        (1_000_000_001, 1),  # на 1 нс старше границы: кадр 0 вытеснен
    ],
)
def test_time_eviction_one_nanosecond_boundary(newest_ns, expected_frames):
    ring = _ring(buffer_seconds=1)
    _add(ring, 0, 1)
    _add(ring, newest_ns, 2)
    assert ring.stats()["frames"] == expected_frames


@pytest.mark.parametrize("start_ns", [0, 123_456_789])
@_deadline()
def test_low_fps_keeps_same_seconds(start_ns):
    """11,7 Гц (период 85470085 нс), 400 кадров, буфер 10 с: осталось 118, не 251."""
    ring = _ring(buffer_seconds=10, max_bytes=1_000_000, pin_max_bytes=500_000)
    for i in range(400):
        _add(ring, start_ns + i * 85_470_085, i + 1)
    assert ring.stats()["frames"] == 118


# ---------------------------------------------------------------------------------------------
# Вытеснение по байтам
# ---------------------------------------------------------------------------------------------


def _bytes_cap_ring() -> TimeRing:
    ring = _ring(buffer_seconds=100, max_bytes=10_000, pin_max_bytes=5_000)
    for i in range(25):
        _add(ring, i * 100_000_000, i + 1, size=1000)
    return ring


def test_bytes_cap_evicts_oldest_and_span_reported():
    """25 кадров по 1000 байт, max_bytes 10000: frames 10, span_s 0.9 (float)."""
    stats = _bytes_cap_ring().stats()
    assert stats["frames"] == 10
    assert isinstance(stats["span_s"], float)
    assert stats["span_s"] == pytest.approx(0.9, abs=1e-12)


def test_bytes_cap_evicts_the_oldest_frames():
    rng = _bytes_cap_ring().range()
    assert rng["t_min_ns"] == 1_500_000_000  # кадр i=15
    assert rng["t_max_ns"] == 2_400_000_000  # кадр i=24


def test_bytes_cap_counters():
    stats = _bytes_cap_ring().stats()
    assert stats["evicted_by_bytes"] == 15
    assert stats["evicted_by_time"] == 0
    assert stats["bytes_held"] == 10_000


def test_big_frame_evicts_several_oldest():
    ring = _ring(buffer_seconds=100, max_bytes=1000, pin_max_bytes=500)
    for i in range(3):
        _add(ring, i * 10, i + 1, size=300)
    _add(ring, 30, 4, size=900)
    stats = ring.stats()
    assert stats["frames"] == 1
    assert stats["bytes_held"] == 900
    assert stats["evicted_by_bytes"] == 3


def test_byte_eviction_takes_oldest_not_newest():
    ring = _ring(buffer_seconds=100, max_bytes=1000, pin_max_bytes=500)
    for i in range(3):
        _add(ring, (i + 1) * 100, i + 1, size=400)
    # 3 * 400 = 1200 > 1000: ушёл самый старый, остались (200, 2) и (300, 3)
    assert ring.stats()["frames"] == 2
    assert _seq_at(ring, 100, PREV) is None
    assert _seq_at(ring, 200, PREV) == 2
    assert _seq_at(ring, 300, PREV) == 3


@_deadline()
def test_time_eviction_runs_before_bytes_attribution():
    """Кадры, вышедшие за буфер, считаются вытесненными по времени, даже если места тоже нет."""
    ring = _ring(buffer_seconds=1, max_bytes=300, pin_max_bytes=100)
    for i in range(3):
        _add(ring, i * 100 * MS, i + 1, size=100)
    _add(ring, 2_000 * MS, 4, size=100)
    stats = ring.stats()
    assert stats["evicted_by_time"] == 3
    assert stats["evicted_by_bytes"] == 0
    assert stats["frames"] == 1


@_deadline()
def test_bytes_held_never_exceeds_max_bytes():
    """max_bytes 10000, 50 кадров по 3000: bytes_held и пик равны 9000 (равенство)."""
    ring = _ring(buffer_seconds=100, max_bytes=10_000, pin_max_bytes=5_000)
    for i in range(50):
        _add(ring, i * MS, i + 1, size=3000)
    stats = ring.stats()
    assert stats["bytes_held"] == 9_000
    assert stats["bytes_held_peak"] == 9_000


def test_bytes_held_peak_is_maximum_not_current():
    """Пик помнит максимум: 11 кадров (1100 байт), затем скачок времени вытесняет почти всё."""
    ring = _ring(buffer_seconds=1, max_bytes=100_000, pin_max_bytes=50_000)
    for i in range(11):
        _add(ring, i * 100 * MS, i + 1, size=100)
    _add(ring, 100_000 * MS, 12, size=100)
    stats = ring.stats()
    assert stats["bytes_held"] == 100
    assert stats["bytes_held_peak"] == 1_100


# ---------------------------------------------------------------------------------------------
# at(): nearest / prev / next
# ---------------------------------------------------------------------------------------------


def _ring_100_200_300() -> TimeRing:
    ring = _ring()
    _fill_pairs(ring, [(100, 1), (200, 2), (300, 3)])
    return ring


def test_at_nearest_prev_next():
    ring = _ring_100_200_300()
    assert _ns_at(ring, 250, NEAREST) == 200  # равное расстояние: prev
    assert _ns_at(ring, 200, PREV) == 200
    assert _ns_at(ring, 200, NEXT) == 200
    assert _at(ring, 50, PREV) is None
    assert _at(ring, 350, NEXT) is None


@pytest.mark.parametrize(
    ("t_ns", "mode", "expected_ns"),
    [
        (240, NEAREST, 200),
        (260, NEAREST, 300),
        (250, PREV, 200),
        (250, NEXT, 300),
        (50, NEAREST, 100),
        (350, NEAREST, 300),
        (50, NEXT, 100),
        (350, PREV, 300),
        (100, PREV, 100),
        (100, NEXT, 100),
        (300, PREV, 300),
        (300, NEXT, 300),
        (100, NEAREST, 100),
        (300, NEAREST, 300),
    ],
)
def test_at_modes_literal_table(t_ns, mode, expected_ns):
    assert _ns_at(_ring_100_200_300(), t_ns, mode) == expected_ns


@pytest.mark.parametrize("mode", [NEAREST, PREV, NEXT])
def test_at_on_empty_ring_returns_none(mode):
    assert _at(_ring(), 100, mode) is None


@pytest.mark.parametrize(
    ("t_ns", "mode", "expected_seq"),
    [
        (200, PREV, 4),  # prev берёт больший seq
        (200, NEXT, 2),  # next берёт меньший seq
        (200, NEAREST, 4),
        (150, PREV, 1),
        (150, NEXT, 2),
        (150, NEAREST, 1),  # |150-100| == |200-150|: prev
        (250, NEAREST, 4),  # prev(250) = (200, 4), равное расстояние: prev
    ],
)
def test_at_nearest_prev_next_with_equal_capture_ns(t_ns, mode, expected_seq):
    """Кольцо (100,1), (200,2), (200,4), (300,5): кадр (150,3) отвергнут при append."""
    ring = _ring()
    _fill_pairs(ring, PAIRS_WITH_REJECT)
    assert _seq_at(ring, t_ns, mode) == expected_seq


def test_at_returns_all_fields_as_appended():
    ring = _ring()
    ring.append(
        capture_ns=1_000,
        capture_ts=1700000123.25,
        payload=b"\xff\xd8not-a-jpeg\x00\xff",
        seq=7,
        device_frame_num=55,
        group_id=9,
        flags=0b1100,
    )
    found = ring.at(1_000, NEAREST)
    assert set(found) == AT_KEYS
    assert found["payload"] == b"\xff\xd8not-a-jpeg\x00\xff"
    assert isinstance(found["payload"], bytes)
    assert found["capture_ns"] == 1_000
    assert found["capture_ts"] == 1700000123.25
    assert found["seq"] == 7
    assert found["device_frame_num"] == 55
    assert found["group_id"] == 9
    assert found["flags"] == 0b1100  # служебные биты 0 и 1 наружу не просачиваются


def test_at_absent_device_frame_num_and_group_id_are_none():
    ring = _ring()
    _add(ring, 1_000, 1)
    found = ring.at(1_000, NEAREST)
    assert found["device_frame_num"] is None
    assert found["group_id"] is None
    assert found["flags"] == 0


def test_zero_device_frame_num_and_group_id_are_not_none():
    ring = _ring()
    _add(ring, 1_000, 1, device_frame_num=0, group_id=0)
    found = ring.at(1_000, NEAREST)
    assert found["device_frame_num"] == 0
    assert found["group_id"] == 0
    assert found["flags"] == 0


def test_at_flags_returned_as_accepted_all_user_bits():
    ring = _ring()
    _add(ring, 1_000, 1, flags=0xFFFFFFFC)
    assert ring.at(1_000, NEAREST)["flags"] == 0xFFFFFFFC


def test_at_returns_the_matching_frames_payload():
    ring = _ring_100_200_300()
    assert ring.at(200, NEAREST)["payload"] == b"\x02" * 100
    assert ring.at(300, PREV)["payload"] == b"\x03" * 100


# ---------------------------------------------------------------------------------------------
# flags: зарезервированные биты 0 и 1
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("flags", [1, 2, 3, 5, 0xFFFFFFFF, 0x12345677])
def test_append_reserved_flag_bits_raise_value_error(flags):
    ring = _ring()
    with pytest.raises(ValueError):
        _add(ring, 1_000, 1, flags=flags)
    assert ring.stats()["frames"] == 0


def test_append_reserved_flag_error_message_omits_the_input_value():
    ring = _ring()
    with pytest.raises(ValueError) as excinfo:
        _add(ring, 1_000, 1, flags=0x12345677)  # десятичное 305419895
    text = str(excinfo.value)
    assert "305419895" not in text
    assert "12345677" not in text.lower()


@pytest.mark.parametrize("flags", [0, 4, 0xFFFFFFFC])
def test_append_user_flag_bits_are_accepted(flags):
    ring = _ring()
    _add(ring, 1_000, 1, flags=flags)
    assert ring.stats()["frames"] == 1


# ---------------------------------------------------------------------------------------------
# Разрывы seq
# ---------------------------------------------------------------------------------------------


def test_seq_gap_recorded():
    ring = _ring()
    _fill_pairs(ring, [(100, 1), (200, 2), (300, 3), (400, 7), (500, 8)])
    assert ring.range()["gaps"] == [{"after_seq": 3, "before_seq": 7, "missed": 3, "capture_ns": 400, "restart": False}]


def test_seq_gap_after_rejected_frame_uses_last_accepted_seq():
    """Отвергнутый кадр (150, 3) last_seq не двигает: разрыв 2 -> 4, пропущен один."""
    ring = _ring()
    _fill_pairs(ring, PAIRS_WITH_REJECT)
    assert ring.range()["gaps"] == [{"after_seq": 2, "before_seq": 4, "missed": 1, "capture_ns": 200, "restart": False}]


def test_seq_restart_recorded_with_restart_flag():
    """seq 5, 6, 1, 2 при растущем capture_ns: новая эпоха, missed 0, restart True."""
    ring = _ring()
    _fill_pairs(ring, [(100, 5), (200, 6), (300, 1), (400, 2)])
    assert ring.range()["gaps"] == [{"after_seq": 6, "before_seq": 1, "missed": 0, "capture_ns": 300, "restart": True}]


def test_contiguous_seq_has_no_gaps():
    ring = _ring()
    _fill_pairs(ring, [(100, 1), (200, 2), (300, 3)])
    assert ring.range()["gaps"] == []


@_deadline()
def test_gap_kept_while_its_frame_is_still_the_oldest_remaining():
    """Разрыв отбрасывается только когда его capture_ns СТРОГО меньше самого старого кадра."""
    ring = _ring(buffer_seconds=1)
    _add(ring, 0, 1)
    _add(ring, 100 * MS, 2)
    _add(ring, 200 * MS, 5)  # разрыв 2 -> 5 со штампом 200 мс
    for i in range(3, 13):  # seq 6..15, штампы 300..1200 мс
        _add(ring, i * 100 * MS, i + 3)
    # newest = 1200 мс, граница 200 мс: кадр seq 5 остаётся самым старым, его штамп == штамп разрыва
    assert ring.range()["t_min_ns"] == 200 * MS
    assert len(ring.range()["gaps"]) == 1


@_deadline()
def test_gap_dropped_when_older_than_oldest_remaining_frame():
    ring = _ring(buffer_seconds=1)
    _add(ring, 0, 1)
    _add(ring, 100 * MS, 2)
    _add(ring, 200 * MS, 5)
    for i in range(3, 14):  # до штампа 1300 мс
        _add(ring, i * 100 * MS, i + 3)
    # newest = 1300 мс, граница 300 мс: самый старый кадр 300 мс > штамп разрыва 200 мс
    assert ring.range()["t_min_ns"] == 300 * MS
    assert ring.range()["gaps"] == []


# ---------------------------------------------------------------------------------------------
# range()
# ---------------------------------------------------------------------------------------------


def test_range_empty():
    assert _ring().range() == {"t_min_ns": None, "t_max_ns": None, "frames": 0, "gaps": []}


def test_range_nonempty_literal():
    assert _ring_100_200_300().range() == {"t_min_ns": 100, "t_max_ns": 300, "frames": 3, "gaps": []}


def test_range_frames_equals_stats_frames():
    ring = _ring(buffer_seconds=100, max_bytes=10_000, pin_max_bytes=5_000)
    for i in range(25):
        _add(ring, i * 100_000_000, i + 1, size=1000)
    assert ring.range()["frames"] == ring.stats()["frames"] == 10


# ---------------------------------------------------------------------------------------------
# Отказы append: порядок и размер
# ---------------------------------------------------------------------------------------------


def test_rejected_order():
    ring = _ring()
    _fill_pairs(ring, PAIRS_WITH_REJECT)
    stats = ring.stats()
    assert stats["frames"] == 4
    assert stats["rejected_order"] == 1
    _add(ring, 200, 2)  # повтор пары (200, 2): она меньше последней принятой (300, 5)
    stats = ring.stats()
    assert stats["rejected_order"] == 2
    assert stats["frames"] == 4


def test_rejected_duplicate_of_last_pair():
    ring = _ring()
    _fill_pairs(ring, [(100, 1), (200, 2)])
    _add(ring, 200, 2)  # пара не БОЛЬШЕ последней: отвергается
    stats = ring.stats()
    assert stats["rejected_order"] == 1
    assert stats["frames"] == 2


def test_equal_capture_ns_lower_seq_rejected_higher_seq_accepted():
    ring = _ring()
    _add(ring, 200, 5)
    _add(ring, 200, 4)  # та же метка, seq меньше
    assert ring.stats()["rejected_order"] == 1
    _add(ring, 200, 6)  # та же метка, seq больше
    stats = ring.stats()
    assert stats["rejected_order"] == 1
    assert stats["frames"] == 2


def test_rejected_frame_is_not_inserted():
    ring = _ring()
    _fill_pairs(ring, PAIRS_WITH_REJECT)
    assert ring.range()["t_min_ns"] == 100
    assert ring.range()["t_max_ns"] == 300
    assert _seq_at(ring, 150, NEXT) == 2  # кадра (150, 3) в кольце нет


def test_rejected_oversize():
    ring = _ring(buffer_seconds=10, max_bytes=1000, pin_max_bytes=500)
    ring.append(capture_ns=100, capture_ts=1.0, payload=b"x" * 1001, seq=1)
    stats = ring.stats()
    assert stats["rejected_oversize"] == 1
    assert stats["frames"] == 0
    assert stats["bytes_held"] == 0
    ring.append(capture_ns=200, capture_ts=2.0, payload=b"y" * 1000, seq=2)
    stats = ring.stats()
    assert stats["rejected_oversize"] == 1
    assert stats["frames"] == 1
    assert stats["bytes_held"] == 1000


def test_oversize_leaves_ring_untouched():
    ring = _ring(buffer_seconds=10, max_bytes=1000, pin_max_bytes=500)
    for i in range(3):
        _add(ring, (i + 1) * 100, i + 1, size=100)
    ring.append(capture_ns=400, capture_ts=4.0, payload=b"x" * 1001, seq=4)
    stats = ring.stats()
    assert stats["frames"] == 3
    assert stats["bytes_held"] == 300
    assert stats["evicted_by_bytes"] == 0
    assert stats["rejected_order"] == 0


# ---------------------------------------------------------------------------------------------
# Конструктор, stats(), экспорт пакета
# ---------------------------------------------------------------------------------------------


def test_constructor_rejects_pin_max_bytes_above_max_bytes():
    with pytest.raises(Exception):  # noqa: B017 - тип в контракте не назван ("исключение при создании")
        TimeRing(buffer_seconds=10, max_bytes=1000, pin_max_bytes=1001)


def test_constructor_accepts_pin_max_bytes_equal_to_max_bytes():
    ring = TimeRing(buffer_seconds=10, max_bytes=1000, pin_max_bytes=1000)
    assert ring.stats()["frames"] == 0


def test_stats_documented_keys_and_zero_start():
    stats = _ring().stats()
    for key in (
        "frames",
        "bytes_held",
        "bytes_held_peak",
        "evicted_by_time",
        "evicted_by_bytes",
        "rejected_order",
        "rejected_oversize",
        "pins_released",
    ):
        assert stats[key] == 0, key
    assert "span_s" in stats


def test_package_exports_time_ring_and_reader():
    from Services import frame_buffer
    from Services.frame_buffer import segment

    assert frame_buffer.TimeRing is TimeRing
    assert frame_buffer.read_segment is segment.read_segment


# ---------------------------------------------------------------------------------------------
# Свойство: кольцо без пинов совпадает с наивной моделью
# ---------------------------------------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(
    steps=st.lists(
        st.tuples(st.integers(min_value=0, max_value=600_000_000), st.integers(min_value=1, max_value=3000)),
        min_size=1,
        max_size=60,
    )
)
@_deadline(60.0)
def test_matches_naive_model_without_pins(steps):
    """Оракул: список кадров, сначала вытеснение по времени (< newest - 1 с), затем по байтам."""
    max_bytes = 5000
    ring = _ring(buffer_seconds=1, max_bytes=max_bytes, pin_max_bytes=2500)
    model: list[tuple[int, int]] = []  # (capture_ns, size)
    by_time = by_bytes = 0
    now = 0
    for seq, (dt, size) in enumerate(steps, start=1):
        now += dt
        _add(ring, now, seq, size=size)
        model.append((now, size))
        kept = [f for f in model if f[0] >= now - 1_000_000_000]
        by_time += len(model) - len(kept)
        model = kept
        while sum(s for _, s in model) > max_bytes:
            model.pop(0)
            by_bytes += 1
        stats = ring.stats()
        assert stats["bytes_held"] <= max_bytes
    stats = ring.stats()
    assert stats["frames"] == len(model)
    assert stats["bytes_held"] == sum(s for _, s in model)
    assert stats["evicted_by_time"] == by_time
    assert stats["evicted_by_bytes"] == by_bytes
    rng = ring.range()
    assert rng["t_min_ns"] == model[0][0]
    assert rng["t_max_ns"] == model[-1][0]
