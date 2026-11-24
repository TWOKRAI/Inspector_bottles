# -*- coding: utf-8 -*-
"""Формат сегмента: блок независимых JPEG + индекс фиксированной длины; сборка и читатель.

Purpose: единственное место, где описана запись индекса (56 байт, little-endian без выравнивания)
и где блок с индексом собирается и читается. `TimeRing.export` и запись на диск (T12) используют
этот модуль, поэтому на диск идут те же байты и тот же индекс без перекодирования.

Запись индекса — `struct.Struct("<QIqdqqqI")`: смещение u64, длина u32, capture_ns i64, capture_ts f64,
seq i64, device_frame_num i64, group_id i64, flags u32. Бит 0 flags — `has_device_frame_num`,
бит 1 — `has_group_id`; при отсутствии значения поле равно 0. Пользовательские флаги — биты 2..31.
Модуль не импортирует кольцо и не декодирует payload.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable

__all__ = ["RECORD", "RECORD_SIZE", "build_segment", "read_segment"]

RECORD = struct.Struct("<QIqdqqqI")
RECORD_SIZE = RECORD.size  # 56

HAS_DEVICE_FRAME_NUM = 0b01
HAS_GROUP_ID = 0b10
_RESERVED_BITS = HAS_DEVICE_FRAME_NUM | HAS_GROUP_ID


def build_segment(frames: Iterable[dict]) -> tuple[bytes, bytes]:
    """Собрать `(blob, index)` из кадров с ключами `at()`: payload склеиваются с нуля вплотную,
    запись индекса — по одной на кадр в порядке подачи.

    Raises:
        ValueError: в `flags` кадра стоят зарезервированные биты 0/1 (текст без значения входа).
    """
    payloads: list[bytes] = []
    records: list[bytes] = []
    offset = 0
    for frame in frames:
        flags = frame["flags"]
        if flags & _RESERVED_BITS:
            raise ValueError("flags: биты 0 и 1 зарезервированы под признаки наличия полей")
        payload = frame["payload"]
        device_frame_num = frame["device_frame_num"]
        group_id = frame["group_id"]
        if device_frame_num is not None:
            flags |= HAS_DEVICE_FRAME_NUM
        if group_id is not None:
            flags |= HAS_GROUP_ID
        records.append(
            RECORD.pack(
                offset,
                len(payload),
                frame["capture_ns"],
                frame["capture_ts"],
                frame["seq"],
                0 if device_frame_num is None else device_frame_num,
                0 if group_id is None else group_id,
                flags,
            )
        )
        payloads.append(payload)
        offset += len(payload)
    return b"".join(payloads), b"".join(records)


def read_segment(blob: bytes, index: bytes) -> list[dict]:
    """Прочитать сегмент: список dict с ключами `at()` в порядке индекса.

    Устойчив к обрезке: запись, у которой `смещение + длина > len(blob)`, отбрасывается (отрезанный
    хвост блока теряет только последнюю запись); неполная запись в хвосте индекса
    (`len(index) % 56 != 0`) игнорируется, `struct.error` не поднимается.
    `device_frame_num` / `group_id` равны `None`, если бит наличия не стоит; `flags` — без битов 0 и 1.
    """
    blob_size = len(blob)
    frames: list[dict] = []
    for position in range(0, len(index) - RECORD_SIZE + 1, RECORD_SIZE):
        offset, length, capture_ns, capture_ts, seq, device_frame_num, group_id, flags = RECORD.unpack_from(
            index, position
        )
        if offset + length > blob_size:
            continue
        frames.append(
            {
                "payload": bytes(blob[offset : offset + length]),
                "capture_ns": capture_ns,
                "capture_ts": capture_ts,
                "seq": seq,
                "device_frame_num": device_frame_num if flags & HAS_DEVICE_FRAME_NUM else None,
                "group_id": group_id if flags & HAS_GROUP_ID else None,
                "flags": flags & ~_RESERVED_BITS,
            }
        )
    return frames
