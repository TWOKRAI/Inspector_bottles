# -*- coding: utf-8 -*-
"""
Канон processor.post_processing_regions (ADR-092): camera_id → список регионов.

Типизированная строка списка — PostProcessingRegionEntry; снимок остаётся dict для YAML.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pydantic import BaseModel, Field


def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


class PostProcessingRegionEntry(BaseModel):
    """Один регион постобработки / просмотра (углы и флаги)."""

    name: str = Field(default="region")
    x1: int = Field(default=0, ge=0)
    y1: int = Field(default=0, ge=0)
    x2: int = Field(default=0, ge=0)
    y2: int = Field(default=0, ge=0)
    enabled: bool = True
    is_main: bool = False
    processing_enabled: bool = True

    model_config = {"extra": "ignore"}


def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def normalize_region_entry(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Один регион: имя, углы, флаги (dict для регистра / YAML)."""
    d = dict(raw)
    name = str(d.get("name", "")).strip() or "region"
    d["name"] = name
    for k in ("x1", "y1", "x2", "y2"):
        if k in d:
            d[k] = max(0, _coerce_int(d.get(k), 0))
    for k in ("enabled", "is_main", "processing_enabled"):
        if k in d:
            v = d[k]
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                d[k] = bool(v)
            else:
                d[k] = bool(v)
    return PostProcessingRegionEntry.model_validate(d).model_dump()


def coords_label(x1: int, y1: int, x2: int, y2: int) -> str:
    return f"({x1},{y1})-({x2},{y2})"


def regions_to_table_rows(regions: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Строки для StructuredTableWidget (region_id = name)."""
    rows: List[Dict[str, Any]] = []
    for raw in regions:
        r = normalize_region_entry(raw)
        name = r["name"]
        rows.append(
            {
                "region_id": name,
                "name": name,
                "enabled": r["enabled"],
                "is_main": r["is_main"],
                "processing_enabled": r["processing_enabled"],
                "coords": coords_label(r["x1"], r["y1"], r["x2"], r["y2"]),
            }
        )
    return rows


def normalize_post_processing_payload(raw: Any) -> Dict[str, List[Dict[str, Any]]]:
    """
    Привести к виду camera_id → [ {name, x1, ...}, ... ].
    Неизвестные типы / пусто → {}.
    """
    if not isinstance(raw, dict) or not raw:
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cam, val in raw.items():
        cam_id = str(cam)
        if not isinstance(val, list):
            continue
        lst: List[Dict[str, Any]] = []
        for item in val:
            if isinstance(item, dict):
                lst.append(normalize_region_entry(item))
        out[cam_id] = lst
    return out


def merge_post_processing_payload(
    regions_by_camera: Mapping[str, List[Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Снимок для processor.post_processing_regions (dict JSON-serializable)."""
    out: Dict[str, Any] = {}
    for cam, lst in regions_by_camera.items():
        if not isinstance(lst, list):
            continue
        inner: List[Dict[str, Any]] = []
        for item in lst:
            if isinstance(item, dict):
                inner.append(normalize_region_entry(item))
        out[str(cam)] = inner
    return out


def default_new_region(existing_names: List[str]) -> Dict[str, Any]:
    """Новый регион с уникальным именем region_N."""
    n = len(existing_names) + 1
    name = f"region_{n}"
    while name in existing_names:
        n += 1
        name = f"region_{n}"
    return normalize_region_entry(
        {
            "name": name,
            "x1": 100,
            "y1": 50,
            "x2": 300,
            "y2": 200,
            "enabled": True,
            "is_main": False,
            "processing_enabled": True,
        }
    )
