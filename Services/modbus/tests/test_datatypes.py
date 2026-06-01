"""Тесты кодирования/декодирования регистров (чистый stdlib, без pymodbus)."""

from __future__ import annotations

import pytest

from Services.modbus.sdk import datatypes as dt


def test_uint16_roundtrip() -> None:
    assert dt.decode_uint16(dt.encode_uint16(40000)[0]) == 40000


def test_int16_negative() -> None:
    reg = dt.encode_int16(-5)[0]
    assert dt.decode_int16(reg) == -5


def test_int16_positive() -> None:
    assert dt.decode_int16(dt.encode_int16(1234)[0]) == 1234


def test_uint32_roundtrip_big() -> None:
    regs = dt.encode_uint32(0x12345678, "big")
    assert regs == [0x1234, 0x5678]
    assert dt.decode_uint32(regs, "big") == 0x12345678


def test_uint32_word_order_little() -> None:
    regs = dt.encode_uint32(0x12345678, "little")
    assert regs == [0x5678, 0x1234]
    assert dt.decode_uint32(regs, "little") == 0x12345678


def test_int32_negative_roundtrip() -> None:
    regs = dt.encode_int32(-123456, "big")
    assert dt.decode_int32(regs, "big") == -123456


def test_float32_roundtrip() -> None:
    regs = dt.encode_float32(3.14159, "big")
    assert dt.decode_float32(regs, "big") == pytest.approx(3.14159, rel=1e-6)


def test_float32_word_order_independent_roundtrip() -> None:
    for order in ("big", "little"):
        regs = dt.encode_float32(-2.5, order)  # type: ignore[arg-type]
        assert dt.decode_float32(regs, order) == pytest.approx(-2.5)  # type: ignore[arg-type]
