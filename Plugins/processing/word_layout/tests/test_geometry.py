"""Тесты чистой геометрии раскладки слова."""

from __future__ import annotations

import math

import pytest

from Plugins.processing.word_layout import geometry as g


@pytest.mark.parametrize(
    "deg, expected",
    [
        (0.0, 0.0),
        (90.0, 90.0),
        (180.0, 180.0),
        (-180.0, 180.0),
        (270.0, -90.0),
        (360.0, 0.0),
        (540.0, 180.0),
        (-90.0, -90.0),
        (450.0, 90.0),
    ],
)
def test_wrap180(deg: float, expected: float) -> None:
    assert g.wrap180(deg) == pytest.approx(expected)


def test_parse_word_single() -> None:
    assert g.parse_word("КОТ") == ["К", "О", "Т"]


def test_parse_word_uppercases() -> None:
    assert g.parse_word("кот") == ["К", "О", "Т"]


def test_parse_word_two_words_gap1() -> None:
    assert g.parse_word("КОТ ПЁС", gap_slots=1) == ["К", "О", "Т", None, "П", "Ё", "С"]


def test_parse_word_gap2() -> None:
    assert g.parse_word("АБ ВГ", gap_slots=2) == ["А", "Б", None, None, "В", "Г"]


def test_parse_word_collapses_whitespace() -> None:
    assert g.parse_word("  а   б  ", gap_slots=1) == ["А", None, "Б"]


def test_parse_word_empty() -> None:
    assert g.parse_word("   ") == []


def test_slot_positions_even() -> None:
    cells = g.parse_word("КОТ")
    pos = g.slot_positions((0.0, 0.0), (100.0, 0.0), cells)
    assert pos == [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]


def test_slot_positions_single_letter_is_first() -> None:
    pos = g.slot_positions((10.0, 20.0), (999.0, 999.0), g.parse_word("Я"))
    assert pos == [(10.0, 20.0)]


def test_slot_positions_two_words_skips_gap() -> None:
    # 5 ячеек: А Б _ В Г → t = 0, .25, (gap), .75, 1 по оси X 0..100.
    cells = g.parse_word("АБ ВГ", gap_slots=1)
    pos = g.slot_positions((0.0, 0.0), (100.0, 0.0), cells)
    xs = [round(x, 3) for x, _ in pos]
    assert xs == [0.0, 25.0, 75.0, 100.0]


def test_slot_positions_2d_diagonal() -> None:
    pos = g.slot_positions((0.0, 0.0), (100.0, 200.0), g.parse_word("АБВ"))
    assert pos[1] == pytest.approx((50.0, 100.0))


def test_correction_angle_basic() -> None:
    # Доворот до 0: глиф под 30° → повернуть на −30°.
    assert g.correction_angle(30.0, True) == pytest.approx(-30.0)


def test_correction_angle_symmetry_zero() -> None:
    # Полная симметрия (angle_valid=False) → доворот не нужен.
    assert g.correction_angle(123.0, False) == 0.0


def test_correction_angle_sign_invert() -> None:
    assert g.correction_angle(30.0, True, sign=-1.0) == pytest.approx(30.0)


def test_correction_angle_zero_offset() -> None:
    assert g.correction_angle(30.0, True, zero_deg=90.0) == pytest.approx(60.0)


def test_correction_angle_wraps() -> None:
    # 200° доворота → нормируется к −160°.
    assert g.correction_angle(-200.0, True) == pytest.approx(-160.0)


def test_min_spacing() -> None:
    assert g.min_spacing([(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]) == pytest.approx(50.0)


def test_min_spacing_few_points() -> None:
    assert g.min_spacing([(0.0, 0.0)]) == math.inf
