"""GUI payload helpers for crop ROI regions: camera → region_name → [x, y, width, height]."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence


def parse_int_coordinate(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coords_list_from_params(params: Mapping[str, Any]) -> List[int]:
    return [
        parse_int_coordinate(params.get("x"), 0),
        parse_int_coordinate(params.get("y"), 0),
        parse_int_coordinate(params.get("width"), 0),
        parse_int_coordinate(params.get("height"), 0),
    ]


def params_from_coords_list(coords: Sequence[int]) -> Dict[str, int]:
    c = list(coords) + [0, 0, 0, 0]
    return {"x": int(c[0]), "y": int(c[1]), "width": int(c[2]), "height": int(c[3])}


def params_to_rect(params: Mapping[str, Any]) -> Dict[str, int]:
    return {
        "x": parse_int_coordinate(params.get("x"), 0),
        "y": parse_int_coordinate(params.get("y"), 0),
        "width": parse_int_coordinate(params.get("width"), 0),
        "height": parse_int_coordinate(params.get("height"), 0),
    }


def rect_to_params(rect: Mapping[str, Any]) -> Dict[str, int]:
    return {
        "x": parse_int_coordinate(rect.get("x"), 0),
        "y": parse_int_coordinate(rect.get("y"), 0),
        "width": parse_int_coordinate(rect.get("width"), 0),
        "height": parse_int_coordinate(rect.get("height"), 0),
    }


def normalize_crop_regions_payload(raw: Any) -> Dict[str, Dict[str, List[int]]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, List[int]]] = {}
    for cam, regions in raw.items():
        if not isinstance(regions, dict):
            continue
        inner: Dict[str, List[int]] = {}
        for rname, coords in regions.items():
            if isinstance(coords, (list, tuple)) and len(coords) >= 4:
                inner[str(rname)] = [int(coords[i]) for i in range(4)]
        out[str(cam)] = inner
    return out


def merge_crop_regions_payload(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> Dict[str, Dict[str, List[int]]]:
    a = normalize_crop_regions_payload(base)
    b = normalize_crop_regions_payload(overlay)
    merged: Dict[str, Dict[str, List[int]]] = {}
    for k in set(a) | set(b):
        merged[k] = {**(a.get(k) or {}), **(b.get(k) or {})}
    return merged


def regions_to_table_rows(regions: Mapping[str, Sequence[int]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for name, coords in regions.items():
        c = list(coords) + [0, 0, 0, 0]
        rows.append({
            "region_id": str(name),
            "name": str(name),
            "x": str(int(c[0])),
            "y": str(int(c[1])),
            "width": str(int(c[2])),
            "height": str(int(c[3])),
        })
    return rows


__all__ = [
    "coords_list_from_params",
    "params_from_coords_list",
    "params_to_rect",
    "rect_to_params",
    "normalize_crop_regions_payload",
    "merge_crop_regions_payload",
    "regions_to_table_rows",
]
