"""``robot_driver_v2.tlm`` (T5.3f f2).

Purpose:
    Разбор блока телеметрии робота Delta v2 (``TLM_PROTO_VER`` .. ``TLM_CFG_PENDING``).

Stability: lite
"""

from __future__ import annotations

from typing import Any

from Services.device_hub.drivers.robot_driver_v2.texts import _TLM_BASE, _WIRE_SCALE
from Services.robot_comm.core.protocol_v2 import REG

__all__ = ["_parse_tlm", "_s16", "_w"]


def _s16(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


def _w(tlm: list[int], name: str) -> int:
    """Слово регистра ``name`` из блока TLM, прочитанного от ``TLM_PROTO_VER``."""
    return int(tlm[REG[name] - _TLM_BASE])


def _parse_tlm(tlm: list[int]) -> tuple[dict[str, Any], bool, int]:
    """Блок TLM -> (телеметрия с именами v1, free, encoder). DESIGN п.5."""
    telemetry = {
        "x_mm": _s16(_w(tlm, "TLM_X")) / _WIRE_SCALE,
        "y_mm": _s16(_w(tlm, "TLM_Y")) / _WIRE_SCALE,
        "z_mm": _s16(_w(tlm, "TLM_Z")) / _WIRE_SCALE,
        "rz_deg": _s16(_w(tlm, "TLM_RZ")) / _WIRE_SCALE,
        "moving": _w(tlm, "TLM_MOVING") == 1,
        "spd_pct": _w(tlm, "TLM_SPD_PCT"),
        "belt_mm_s": _s16(_w(tlm, "TLM_BELT_MMS")),
        "heartbeat": _w(tlm, "TLM_HB_ROBOT"),
        "servo": _w(tlm, "TLM_SERVO") == 1,
        "hand": _w(tlm, "TLM_HAND"),
        "miss_count": _w(tlm, "TLM_MISS_COUNT"),
    }
    free = _w(tlm, "TLM_ACTIVITY") == 0
    # TLM_ENC — два слова, младшее первым (порядок слов транспорта не используется), s32
    offset = REG["TLM_ENC"] - _TLM_BASE
    raw = (int(tlm[offset]) & 0xFFFF) | ((int(tlm[offset + 1]) & 0xFFFF) << 16)
    encoder = raw - 0x1_0000_0000 if raw >= 0x8000_0000 else raw
    return telemetry, free, encoder
