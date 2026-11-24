# -*- coding: utf-8 -*-
"""Решения ADR кольца кадров (Tasks T9a и T9b): тесты автора для строк, которые слепой tester не закрепил.

Purpose: закрепить решения developer-а, записанные в DECISIONS.md пакета: повторный pin = самый
«молодой» пин, `seq == last_seq` = рестарт, порядок важнее размера при отказе, `unpin` не вытесняет
сразу, бюджет пинов в `append` (сценарии A и B), диапазон i64 и тип `capture_ts`, `export` с t0 > t1,
счётчик закреплённых байт против наивного пересчёта, формат записи индекса.

Ожидаемые значения — литералы. Единственное обращение к закрытым полям — тест счётчика закреплённых
байт: ему нужно сравнить счётчик с пересчётом, наблюдаемого аналога у счётчика нет.
"""

from __future__ import annotations

import random

import pytest

from Services.frame_buffer.segment import RECORD, read_segment
from Services.frame_buffer.time_ring import TimeRing

__all__ = []

STEP = 100_000_000  # 10 Гц: кадр i имеет capture_ns == i * STEP
PREV = "prev"


def _ring(buffer_seconds: float = 1, max_bytes: int = 1_000_000, pin_max_bytes: int = 1_000_000) -> TimeRing:
    return TimeRing(buffer_seconds=buffer_seconds, max_bytes=max_bytes, pin_max_bytes=pin_max_bytes)


def _frame(ring: TimeRing, i: int, size: int = 1000) -> None:
    """Кадр i: capture_ns == i * STEP, seq == i + 1."""
    ring.append(capture_ns=i * STEP, capture_ts=1.5, payload=bytes([(i + 1) % 256]) * size, seq=i + 1)


def _stream(ring: TimeRing, first: int, last: int) -> None:
    for i in range(first, last + 1):
        _frame(ring, i)


def _ns_at(ring: TimeRing, t_ns: int, mode: str) -> int | None:
    found = ring.at(t_ns, mode)
    return None if found is None else found["capture_ns"]


# ---------------------------------------------------------------------------------------------
# Решения порядка и разрывов
# ---------------------------------------------------------------------------------------------


def test_repin_same_tag_becomes_the_youngest_pin():
    """pin a, pin b, pin a: самый старый теперь b; превышение бюджета освобождает b, а не a."""
    ring = _ring(pin_max_bytes=3_000)
    _stream(ring, 0, 9)
    ring.pin(0, 0, "a")  # кадр 0: 1000
    ring.pin(STEP, STEP, "b")  # кадр 100 мс: 1000
    ring.pin(0, 0, "a")  # повторный вызов: a становится самым молодым
    ring.pin(2 * STEP, 3 * STEP, "c")  # +2000 -> 4000 > 3000: освобождается самый старый, то есть b
    assert ring.stats()["pins_released"] == 1
    _stream(ring, 10, 30)
    assert _ns_at(ring, 0, PREV) == 0  # кадр a остался
    assert _ns_at(ring, STEP, PREV) == 0  # кадра 100 мс (бывшего b) нет
    assert ring.range()["frames"] == 14  # окно i 20..30 (11) + кадр a + два кадра c


def test_seq_equal_to_last_seq_is_a_restart():
    ring = _ring()
    ring.append(capture_ns=100, capture_ts=1.0, payload=b"a", seq=5)
    ring.append(capture_ns=200, capture_ts=2.0, payload=b"b", seq=5)
    assert ring.range()["gaps"] == [{"after_seq": 5, "before_seq": 5, "missed": 0, "capture_ns": 200, "restart": True}]
    assert ring.stats()["frames"] == 2


def test_order_violation_wins_over_oversize():
    """Кадр нарушает и порядок, и размер: считается rejected_order, не rejected_oversize."""
    ring = _ring(max_bytes=1000, pin_max_bytes=500)
    ring.append(capture_ns=200, capture_ts=2.0, payload=b"a" * 100, seq=2)
    ring.append(capture_ns=100, capture_ts=1.0, payload=b"b" * 2000, seq=1)
    stats = ring.stats()
    assert stats["rejected_order"] == 1
    assert stats["rejected_oversize"] == 0
    assert stats["frames"] == 1


@pytest.mark.parametrize("t0_ns, t1_ns", [(300, 100), (1, 0)])
def test_export_reversed_range_raises_value_error(t0_ns, t1_ns):
    ring = _ring()
    _stream(ring, 0, 3)
    before = ring.stats()
    with pytest.raises(ValueError):
        ring.export(t0_ns, t1_ns)
    assert ring.stats() == before


def test_export_reversed_range_error_text_omits_input_values():
    ring = _ring()
    with pytest.raises(ValueError) as excinfo:
        ring.export(123456789, 987654)
    assert "123456789" not in str(excinfo.value)
    assert "987654" not in str(excinfo.value)


def test_unpin_does_not_evict_until_next_append():
    ring = _ring()
    _stream(ring, 0, 9)
    ring.pin(2 * STEP, 5 * STEP, "p")
    _stream(ring, 10, 30)
    assert ring.range()["frames"] == 15  # окно (11) + кадры 200..500 мс
    ring.unpin("p")
    assert ring.range()["frames"] == 15  # unpin сам не вытесняет
    _frame(ring, 31)
    assert ring.range()["frames"] == 11  # вытеснение случилось при append


# ---------------------------------------------------------------------------------------------
# Бюджет пинов в append: сценарии A и B
# ---------------------------------------------------------------------------------------------


def test_budget_scenario_a_future_frames_exceed_pin_budget_on_second_frame():
    """pin на пустом кольце, два кадра по 2000 внутри интервала: 2000 <= 3000, затем 4000 > 3000."""
    ring = _ring(pin_max_bytes=3_000)
    ring.pin(0, 10**9, "a")
    ring.append(capture_ns=0, capture_ts=0.0, payload=b"x" * 2000, seq=1)
    assert ring.stats()["pins_released"] == 0
    ring.append(capture_ns=STEP, capture_ts=0.1, payload=b"y" * 2000, seq=2)
    assert ring.stats()["pins_released"] == 1


def test_budget_scenario_b_unpinned_new_frame_is_not_counted_against_pin_budget():
    """Закреплён один кадр 2000; новый кадр 2000 вне интервала в бюджет пинов не входит."""
    ring = _ring(pin_max_bytes=3_000)
    ring.append(capture_ns=0, capture_ts=0.0, payload=b"x" * 2000, seq=1)
    ring.pin(0, 0, "p")
    assert ring.stats()["pins_released"] == 0
    ring.append(capture_ns=STEP, capture_ts=0.1, payload=b"y" * 2000, seq=2)
    assert ring.stats()["pins_released"] == 0
    assert ring.stats()["frames"] == 2


# ---------------------------------------------------------------------------------------------
# Диапазон i64 и тип capture_ts
# ---------------------------------------------------------------------------------------------

I64_MAX, I64_MIN = 2**63 - 1, -(2**63)


def _append_with(ring: TimeRing, **override) -> None:
    fields = {"capture_ns": 100, "capture_ts": 1.0, "payload": b"p", "seq": 1}
    fields.update(override)
    ring.append(**fields)


@pytest.mark.parametrize("field", ["capture_ns", "seq", "device_frame_num", "group_id"])
@pytest.mark.parametrize("value", [2**63, -(2**63) - 1, 2**80])
def test_append_rejects_i64_overflow_without_touching_the_ring(field, value):
    ring = _ring()
    _frame(ring, 0)
    before = ring.stats()
    with pytest.raises(ValueError):
        _append_with(ring, **{field: value})
    assert ring.stats() == before
    assert ring.range()["gaps"] == []


@pytest.mark.parametrize("field", ["capture_ns", "seq", "device_frame_num", "group_id"])
def test_append_i64_error_text_omits_the_input_value(field):
    ring = _ring()
    with pytest.raises(ValueError) as excinfo:
        _append_with(ring, **{field: 2**63 + 12345})
    assert "9223372036854788153" not in str(excinfo.value)
    assert "12345" not in str(excinfo.value)


@pytest.mark.parametrize("field", ["device_frame_num", "group_id"])
@pytest.mark.parametrize("value", [I64_MAX, I64_MIN, 0, -1])
def test_append_accepts_i64_bounds_for_optional_fields(field, value):
    ring = _ring()
    _append_with(ring, **{field: value})
    assert ring.at(100, "nearest")[field] == value


@pytest.mark.parametrize("value", [I64_MAX, I64_MIN, 0])
def test_append_accepts_i64_bounds_for_capture_ns_and_seq(value):
    ring = _ring(buffer_seconds=1e18 / 1e9)
    _append_with(ring, capture_ns=value, seq=value)
    found = ring.at(value, "nearest")
    assert (found["capture_ns"], found["seq"]) == (value, value)


@pytest.mark.parametrize("field", ["capture_ns", "seq", "device_frame_num", "group_id"])
@pytest.mark.parametrize("value", [1.5, "7", True])
def test_append_rejects_non_integer_ids(field, value):
    ring = _ring()
    with pytest.raises(ValueError):
        _append_with(ring, **{field: value})
    assert ring.stats()["frames"] == 0


@pytest.mark.parametrize("value", [None, "1.0", b"1.0", [1.0], True])
def test_append_rejects_non_number_capture_ts(value):
    ring = _ring()
    with pytest.raises(ValueError):
        _append_with(ring, capture_ts=value)
    assert ring.stats()["frames"] == 0


def test_append_capture_ts_int_is_stored_as_float():
    ring = _ring()
    _append_with(ring, capture_ts=7)
    found = ring.at(100, "nearest")
    assert found["capture_ts"] == 7.0
    assert isinstance(found["capture_ts"], float)


def test_append_capture_ts_error_text_omits_the_input_value():
    ring = _ring()
    with pytest.raises(ValueError) as excinfo:
        _append_with(ring, capture_ts="secret-value-42")
    assert "secret-value-42" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ or excinfo.value.__context__ is None


# ---------------------------------------------------------------------------------------------
# Счётчик закреплённых байт против наивного пересчёта
# ---------------------------------------------------------------------------------------------


def _naive_pinned_bytes(ring: TimeRing) -> int:
    exported = ring.export(I64_MIN, I64_MAX)
    pins = list(ring._pins.values())  # noqa: SLF001 - см. docstring модуля
    return sum(
        len(frame["payload"])
        for frame in read_segment(exported["blob"], exported["index"])
        if any(t0 <= frame["capture_ns"] <= t1 for t0, t1 in pins)
    )


@pytest.mark.parametrize("seed", range(25))
def test_pinned_bytes_counter_matches_naive_recount(seed):
    """Случайная последовательность append / pin / unpin / вытеснение: счётчик == наивный пересчёт."""
    rng = random.Random(seed)
    ring = _ring(buffer_seconds=1, max_bytes=6_000, pin_max_bytes=3_000)
    i = 0
    for _ in range(150):
        action = rng.random()
        if action < 0.6:
            size = rng.choice([100, 500, 900, 1500, 2000])
            ring.append(capture_ns=i * STEP, capture_ts=0.0, payload=b"z" * size, seq=i + 1)
            i += 1
        elif action < 0.85:
            start = rng.randint(max(i - 20, 0), i + 3)
            ring.pin(start * STEP, (start + rng.randint(0, 6)) * STEP, f"t{rng.randint(0, 3)}")
        else:
            ring.unpin(f"t{rng.randint(0, 3)}")
        assert ring._pinned_held == _naive_pinned_bytes(ring), (seed, i)  # noqa: SLF001
        assert ring.stats()["bytes_held"] <= 6_000


# ---------------------------------------------------------------------------------------------
# Формат записи индекса
# ---------------------------------------------------------------------------------------------


def test_record_struct_format_and_size_are_the_documented_ones():
    assert RECORD.size == 56
    assert RECORD.format == "<QIqdqqqI"
