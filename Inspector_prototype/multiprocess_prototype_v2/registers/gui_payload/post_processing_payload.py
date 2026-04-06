# -*- coding: utf-8 -*-
"""Структура строк постобработки (камера → список регионов x1..y2 + флаги)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, TypedDict


class PostProcessingRegionEntry(TypedDict, total=False):
    name: str
    x1: int
    y1: int
    x2: int
    y2: int
    enabled: bool
    is_main: bool
    processing_enabled: bool


def coords_label(entry: Mapping[str, Any]) -> str:
    return f"{int(entry.get('x1', 0))},{int(entry.get('y1', 0))}-{int(entry.get('x2', 0))},{int(entry.get('y2', 0))}"


def default_new_region(existing_names: Sequence[str]) -> Dict[str, Any]:
    base = "region"
    if base not in existing_names:
        return normalize_region_entry({"name": base})
    n = 1
    while f"{base}_{n}" in existing_names:
        n += 1
    return normalize_region_entry({"name": f"{base}_{n}"})


def normalize_region_entry(raw: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(raw.get("name", "")),
        "x1": int(raw.get("x1", 0)),
        "y1": int(raw.get("y1", 0)),
        "x2": int(raw.get("x2", 0)),
        "y2": int(raw.get("y2", 0)),
        "enabled": bool(raw.get("enabled", True)),
        "is_main": bool(raw.get("is_main", False)),
        "processing_enabled": bool(raw.get("processing_enabled", True)),
    }


def normalize_post_processing_payload(raw: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cam, rows in raw.items():
        if not isinstance(rows, list):
            continue
        out[str(cam)] = [normalize_region_entry(r) for r in rows if isinstance(r, dict)]
    return out


def merge_post_processing_payload(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    a = normalize_post_processing_payload(base)
    b = normalize_post_processing_payload(overlay)
    merged: Dict[str, List[Dict[str, Any]]] = {**a}
    for k, v in b.items():
        merged[k] = v
    return merged


def regions_to_table_rows(regions: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in regions:
        name = str(r.get("name", ""))
        rows.append(
            {
                "region_id": name,
                "name": name,
                "enabled": bool(r.get("enabled", True)),
                "is_main": bool(r.get("is_main", False)),
                "processing_enabled": bool(r.get("processing_enabled", True)),
                "coords": coords_label(r),
            }
        )
    return rows
