"""Тесты потокового жадного матчера WordAssembler."""

from __future__ import annotations

from Plugins.processing.word_layout.assembler import WordAssembler


def _kot() -> WordAssembler:
    return WordAssembler.from_word("КОТ", (0.0, 0.0), (100.0, 0.0))


def test_build_slots() -> None:
    a = _kot()
    assert a.total == 3
    assert [s.char for s in a.slots] == ["К", "О", "Т"]
    assert a.next_letter == "К"
    assert not a.done


def test_offer_fills_slot_and_returns_job() -> None:
    a = _kot()
    job = a.offer("К", 30.0, True)
    assert job is not None
    assert job["slot"] == 0
    assert job["char"] == "К"
    assert job["x_mm"] == 0.0
    assert job["angle_deg"] == -30.0  # доворот до прямой
    assert job["raw_angle_deg"] == 30.0
    assert a.filled_count == 1


def test_offer_unneeded_letter_returns_none() -> None:
    a = _kot()
    assert a.offer("Я", 0.0, True) is None
    assert a.filled_count == 0


def test_offer_lowercase_matches() -> None:
    a = _kot()
    assert a.offer("к", 0.0, True) is not None


def test_offer_out_of_order() -> None:
    a = _kot()
    assert a.offer("Т", 0.0, True)["slot"] == 2
    assert a.offer("К", 0.0, True)["slot"] == 0
    assert a.offer("О", 0.0, True)["slot"] == 1
    assert a.done


def test_duplicate_letters() -> None:
    a = WordAssembler.from_word("ОКО", (0.0, 0.0), (100.0, 0.0))
    assert a.offer("О", 0.0, True)["slot"] == 0
    assert a.offer("О", 0.0, True)["slot"] == 2
    assert a.offer("О", 0.0, True) is None  # оба слота «О» заняты
    assert not a.done  # «К» ещё пуст


def test_symmetry_letter_zero_angle() -> None:
    a = _kot()
    job = a.offer("О", 99.0, False)  # симметрия — доворот не нужен
    assert job["angle_deg"] == 0.0


def test_done_after_all() -> None:
    a = _kot()
    for ch in "КОТ":
        a.offer(ch, 0.0, True)
    assert a.done
    assert a.remaining == 0
    assert a.next_letter == ""


def test_reset() -> None:
    a = _kot()
    a.offer("К", 0.0, True)
    a.reset()
    assert a.filled_count == 0
    assert a.next_letter == "К"


def test_empty_word_not_done() -> None:
    a = WordAssembler.from_word("   ", (0.0, 0.0), (100.0, 0.0))
    assert a.total == 0
    assert not a.done


def test_calibration_passthrough() -> None:
    a = _kot()
    job = a.offer("К", 30.0, True, sign=-1.0, zero_deg=10.0)
    assert job["angle_deg"] == 40.0  # wrap180(10 + 30)
