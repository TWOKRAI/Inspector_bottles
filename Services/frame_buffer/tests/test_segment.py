# -*- coding: utf-8 -*-
"""Запись индекса и читатель сегмента read_segment (Task T9b), слепые приёмочные тесты.

Purpose: проверить публичный контракт формата сегмента (запись индекса 56 байт, читатель
read_segment(blob, index), устойчивость к обрезанному блоку и индексу) по критериям приёмки,
до реализации.

Ожидаемые значения — литералы из ACCEPTANCE и ручной упаковки struct "<QIqdqqqI", не вычисляются
из кода под тестом.
"""

from __future__ import annotations

import struct

import pytest

from Services.frame_buffer.segment import read_segment
from Services.frame_buffer.time_ring import TimeRing

__all__ = []

RECORD = "<QIqdqqqI"
RECORD_SIZE = 56
READ_KEYS = {"payload", "capture_ns", "capture_ts", "seq", "device_frame_num", "group_id", "flags"}
FRAME_COUNT = 40
PAYLOAD_SIZE = 1500


def _export_40() -> tuple[bytes, bytes]:
    """40 кадров по 1500 байт. Кадр k: seq k+1, штамп 2e9 + k*4e7 нс, ts 1.7e9 + k*0.5.

    device_frame_num = 100 + k для чётных k, иначе None; group_id = k // 10; пользовательские
    флаги 4 у k кратных 5, иначе 0.
    """
    ring = TimeRing(buffer_seconds=100, max_bytes=100_000, pin_max_bytes=50_000)
    for k in range(FRAME_COUNT):
        ring.append(
            capture_ns=2_000_000_000 + k * 40_000_000,
            capture_ts=1_700_000_000.0 + k * 0.5,
            payload=bytes([k + 1]) * PAYLOAD_SIZE,
            seq=k + 1,
            device_frame_num=100 + k if k % 2 == 0 else None,
            group_id=k // 10,
            flags=4 if k % 5 == 0 else 0,
        )
    exported = ring.export(0, 10**12)
    return exported["blob"], exported["index"]


# ---------------------------------------------------------------------------------------------
# Формат записи индекса: 56 байт фиксированной длины
# ---------------------------------------------------------------------------------------------


def test_record_struct_is_56_bytes():
    assert struct.calcsize(RECORD) == 56 == RECORD_SIZE


def test_fixed_record_length():
    _, index = _export_40()
    assert len(index) == 56 * 40


# Поле записи k по смещению 56*k: (offset, length, capture_ns, capture_ts, seq, dfn, group_id, flags).
# Флаги в записи: бит 0 (есть device_frame_num) + бит 1 (есть group_id) + пользовательские биты.
EXPECTED_RECORDS = {
    0: (0, 1500, 2_000_000_000, 1_700_000_000.0, 1, 100, 0, 7),
    1: (1500, 1500, 2_040_000_000, 1_700_000_000.5, 2, 0, 0, 2),
    17: (25_500, 1500, 2_680_000_000, 1_700_000_008.5, 18, 0, 1, 2),
    20: (30_000, 1500, 2_800_000_000, 1_700_000_010.0, 21, 120, 2, 7),
    39: (58_500, 1500, 3_560_000_000, 1_700_000_019.5, 40, 0, 3, 2),
}


@pytest.mark.parametrize("k", sorted(EXPECTED_RECORDS))
def test_record_fields_at_fixed_offset(k):
    _, index = _export_40()
    assert struct.unpack_from(RECORD, index, 56 * k) == EXPECTED_RECORDS[k]


def test_record_flags_encode_presence_bits_and_user_bits():
    ring = TimeRing(buffer_seconds=100, max_bytes=10_000, pin_max_bytes=5_000)
    ring.append(capture_ns=10, capture_ts=1.0, payload=b"a", seq=1)
    ring.append(capture_ns=20, capture_ts=2.0, payload=b"b", seq=2, device_frame_num=9, flags=4)
    ring.append(capture_ns=30, capture_ts=3.0, payload=b"c", seq=3, group_id=5, flags=8)
    ring.append(capture_ns=40, capture_ts=4.0, payload=b"d", seq=4, device_frame_num=0, group_id=0)
    index = ring.export(0, 100)["index"]
    assert len(index) == 4 * 56
    records = [struct.unpack_from(RECORD, index, 56 * k) for k in range(4)]
    assert records[0] == (0, 1, 10, 1.0, 1, 0, 0, 0)
    assert records[1] == (1, 1, 20, 2.0, 2, 9, 0, 0b101)
    assert records[2] == (2, 1, 30, 3.0, 3, 0, 5, 0b1010)
    assert records[3] == (3, 1, 40, 4.0, 4, 0, 0, 0b11)


# ---------------------------------------------------------------------------------------------
# Читатель: границы блока
# ---------------------------------------------------------------------------------------------


def test_reader_keeps_all_when_not_truncated():
    blob, index = _export_40()
    assert len(read_segment(blob, index)) == 40


def test_reader_drops_only_last_record_on_truncated_tail():
    blob, index = _export_40()
    assert len(read_segment(blob[:-1000], index)) == 39


@pytest.mark.parametrize(
    ("cut", "expected"),
    [
        (0, 40),
        (1, 39),
        (1000, 39),
        (1500, 39),  # запись 38 заканчивается ровно на размере blob: смещение+длина == размер, остаётся
        (1501, 38),
        (3000, 38),
        (3001, 37),
    ],
)
def test_reader_boundary_offset_plus_length_equal_to_blob_size_is_kept(cut, expected):
    blob, index = _export_40()
    assert len(read_segment(blob[: len(blob) - cut], index)) == expected


def test_reader_truncated_blob_keeps_leading_records_intact():
    blob, index = _export_40()
    records = read_segment(blob[:-1000], index)
    assert [r["seq"] for r in records] == list(range(1, 40))
    assert records[38]["payload"] == bytes([39]) * 1500


def test_reader_empty_blob_drops_everything():
    _, index = _export_40()
    assert read_segment(b"", index) == []


# ---------------------------------------------------------------------------------------------
# Читатель: обрезанный индекс (неполная запись в хвосте)
# ---------------------------------------------------------------------------------------------


def test_reader_ignores_incomplete_record_at_index_tail():
    blob, index = _export_40()
    assert len(read_segment(blob, index + b"\x01" * 10)) == 40


@pytest.mark.parametrize("tail_len", [1, 8, 30, 55])
def test_reader_index_cut_mid_record_does_not_raise_struct_error(tail_len):
    blob, index = _export_40()
    cut_index = index[: 56 * 39 + tail_len]
    assert len(read_segment(blob, cut_index)) == 39


def test_reader_index_shorter_than_one_record_returns_empty():
    blob, index = _export_40()
    assert read_segment(blob, index[:55]) == []


def test_reader_empty_index_and_empty_blob_return_empty_list():
    assert read_segment(b"", b"") == []


# ---------------------------------------------------------------------------------------------
# Читатель: поля записи
# ---------------------------------------------------------------------------------------------


def test_reader_returns_documented_keys_and_literal_values():
    blob, index = _export_40()
    records = read_segment(blob, index)
    assert set(records[17]) == READ_KEYS
    assert records[17] == {
        "payload": bytes([18]) * 1500,
        "capture_ns": 2_680_000_000,
        "capture_ts": 1_700_000_008.5,
        "seq": 18,
        "device_frame_num": None,
        "group_id": 1,
        "flags": 0,
    }


def test_reader_restores_present_fields_and_user_flags_without_reserved_bits():
    blob, index = _export_40()
    records = read_segment(blob, index)
    assert records[20] == {
        "payload": bytes([21]) * 1500,
        "capture_ns": 2_800_000_000,
        "capture_ts": 1_700_000_010.0,
        "seq": 21,
        "device_frame_num": 120,
        "group_id": 2,
        "flags": 4,
    }


def test_reader_returns_bytes_payload():
    blob, index = _export_40()
    assert isinstance(read_segment(blob, index)[0]["payload"], bytes)


def test_reader_decodes_hand_packed_records():
    """Независимо от кольца: запись собрана struct.pack по формату из контракта."""
    blob = b"AAAA" + b"BBBBBB" + b"CC"
    index = (
        struct.pack(RECORD, 0, 4, 1000, 1.5, 11, 77, 0, 0b10101)  # бит 0 + пользовательские биты 2 и 4
        + struct.pack(RECORD, 4, 6, 2000, 2.5, 12, 0, 0, 0b10)  # группа 0 присутствует, номера кадра нет
        + struct.pack(RECORD, 10, 2, 3000, 3.5, 13, 99, 88, 0)  # биты наличия не стоят: поля пустые
    )
    assert read_segment(blob, index) == [
        {
            "payload": b"AAAA",
            "capture_ns": 1000,
            "capture_ts": 1.5,
            "seq": 11,
            "device_frame_num": 77,
            "group_id": None,
            "flags": 0b10100,
        },
        {
            "payload": b"BBBBBB",
            "capture_ns": 2000,
            "capture_ts": 2.5,
            "seq": 12,
            "device_frame_num": None,
            "group_id": 0,
            "flags": 0,
        },
        {
            "payload": b"CC",
            "capture_ns": 3000,
            "capture_ts": 3.5,
            "seq": 13,
            "device_frame_num": None,
            "group_id": None,
            "flags": 0,
        },
    ]


def test_reader_hand_packed_record_ending_exactly_at_blob_end_is_kept():
    blob = b"ABCDE"
    index = struct.pack(RECORD, 2, 3, 1, 0.5, 1, 0, 0, 0)  # 2 + 3 == 5 == len(blob)
    assert [r["payload"] for r in read_segment(blob, index)] == [b"CDE"]


def test_reader_hand_packed_record_one_byte_past_blob_end_is_dropped():
    blob = b"ABCD"
    index = struct.pack(RECORD, 2, 3, 1, 0.5, 1, 0, 0, 0)  # 2 + 3 == 5 > 4
    assert read_segment(blob, index) == []
