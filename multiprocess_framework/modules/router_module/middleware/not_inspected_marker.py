# -*- coding: utf-8 -*-
"""Контракт маркера ``not_inspected`` (Task 4.7d-1).

Чистый модуль: ничего не импортирует из process_module. Маркер — лёгкий dict без кадра,
которым узел заменяет выброшенный при переполнении кадр под политикой ``overflow: every``
(поведение — Task 4.7d-2; здесь только форма и предикат).
"""

from __future__ import annotations

from typing import Any

NOT_INSPECTED = "not_inspected"

# Допустимые причины, по которым кадр не был проинспектирован.
MARKER_REASONS = ("lag", "stale_restore", "stale_exec", "door")


def build_marker(meta: dict[str, Any], *, reason: str, source: str) -> dict[str, Any]:
    """Собрать маркер по метаданным выброшенного кадра.

    Кадр и служебные SHM-ключи в маркер НЕ попадают. ``frame_id`` / ``camera_id`` копируются,
    только если ключ есть в ``meta`` (значение 0 сохраняется).
    """
    if reason not in MARKER_REASONS:
        raise ValueError(f"reason={reason!r} — expected one of {MARKER_REASONS}")
    marker: dict[str, Any] = {
        "inspection_status": NOT_INSPECTED,
        "overflow_marker": True,
        "reason": reason,
        "source": source,
        "trace_id": meta.get("trace_id") or "",
        "capture_ts": meta.get("capture_ts"),
    }
    for key in ("frame_id", "camera_id"):
        if key in meta:
            marker[key] = meta[key]
    return marker


def meta_from_msg(msg: dict[str, Any]) -> dict[str, Any]:
    """Метаданные для ``build_marker`` из IPC-сообщения — по правилам ``DataReceiver._build_item``.

    ``trace_id`` / ``capture_ts`` — из ``msg["data"]``; ``frame_id`` / ``camera_id`` — из ``data``,
    иначе из ``msg``. Ключ копируется по наличию, не по истинности (значение 0 сохраняется).
    """
    data = msg.get("data") or {}
    meta: dict[str, Any] = {}
    for key in ("trace_id", "capture_ts"):
        if key in data:
            meta[key] = data[key]
    for key in ("frame_id", "camera_id"):
        if key in data:
            meta[key] = data[key]
        elif key in msg:
            meta[key] = msg[key]
    return meta


def is_marker(item: dict[str, Any]) -> bool:
    """Маркер переполнения — не любой кадр с тегом ``not_inspected`` (тег сбоя плагина идёт с кадром)."""
    return item.get("overflow_marker") is True and item.get("inspection_status") == NOT_INSPECTED
