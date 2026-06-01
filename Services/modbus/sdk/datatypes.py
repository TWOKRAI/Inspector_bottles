"""Кодирование/декодирование значений Modbus-регистров.

Регистр Modbus — 16-битное слово (0..65535). Прикладные типы (int32, float32)
занимают по два регистра, поэтому важен порядок слов (word order):

- ``big``    — старшее слово первым (Modbus-стандарт, "ABCD"). Дефолт.
- ``little`` — младшее слово первым ("CDAB"), частый вариант у ряда PLC.

Модуль на чистом stdlib (struct), без зависимости от pymodbus — поэтому полностью
тестируется без установленной библиотеки и без железа.
"""

from __future__ import annotations

import struct
from typing import Literal

WordOrder = Literal["big", "little"]

_U16_MASK = 0xFFFF


def _to_words(raw: bytes, word_order: WordOrder) -> list[int]:
    """Разбить байтовую строку (кратную 2) на 16-битные регистры."""
    words = [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]
    if word_order == "little":
        words.reverse()
    return words


def _from_words(words: list[int], word_order: WordOrder) -> bytes:
    """Склеить 16-битные регистры в байтовую строку (big-endian внутри слова)."""
    ordered = list(words)
    if word_order == "little":
        ordered = list(reversed(ordered))
    return b"".join((w & _U16_MASK).to_bytes(2, "big") for w in ordered)


# --------------------------------------------------------------------------- #
# Декодирование (registers -> value)
# --------------------------------------------------------------------------- #


def decode_uint16(reg: int) -> int:
    """Один регистр как беззнаковое 16-битное."""
    return reg & _U16_MASK


def decode_int16(reg: int) -> int:
    """Один регистр как знаковое 16-битное (two's complement)."""
    val = reg & _U16_MASK
    return val - 0x10000 if val >= 0x8000 else val


def decode_uint32(regs: list[int], word_order: WordOrder = "big") -> int:
    """Два регистра как беззнаковое 32-битное."""
    return struct.unpack(">I", _from_words(regs[:2], word_order))[0]


def decode_int32(regs: list[int], word_order: WordOrder = "big") -> int:
    """Два регистра как знаковое 32-битное."""
    return struct.unpack(">i", _from_words(regs[:2], word_order))[0]


def decode_float32(regs: list[int], word_order: WordOrder = "big") -> float:
    """Два регистра как IEEE-754 float32."""
    return struct.unpack(">f", _from_words(regs[:2], word_order))[0]


# --------------------------------------------------------------------------- #
# Кодирование (value -> registers)
# --------------------------------------------------------------------------- #


def encode_uint16(value: int) -> list[int]:
    """Беззнаковое 16-битное → один регистр."""
    return [value & _U16_MASK]


def encode_int16(value: int) -> list[int]:
    """Знаковое 16-битное → один регистр."""
    return [value & _U16_MASK]


def encode_uint32(value: int, word_order: WordOrder = "big") -> list[int]:
    """Беззнаковое 32-битное → два регистра."""
    return _to_words(struct.pack(">I", value & 0xFFFFFFFF), word_order)


def encode_int32(value: int, word_order: WordOrder = "big") -> list[int]:
    """Знаковое 32-битное → два регистра."""
    return _to_words(struct.pack(">i", value), word_order)


def encode_float32(value: float, word_order: WordOrder = "big") -> list[int]:
    """IEEE-754 float32 → два регистра."""
    return _to_words(struct.pack(">f", value), word_order)
