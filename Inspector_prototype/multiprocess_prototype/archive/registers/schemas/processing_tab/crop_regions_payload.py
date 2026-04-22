# -*- coding: utf-8 -*-
"""
Канон формата processor.crop_regions (ADR-091): camera_id → region_name → [x,y,w,h].

Используется регистрами, RecipeManager и виджетом ROI — без импорта из frontend.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# Ключи контролов (совпадают с CroppedParamKey во frontend)
_X = "x"
_Y = "y"
_W = "width"
_H = "height"
CROPPED_PARAM_KEYS: tuple[str, ...] = (_X, _Y, _W, _H)


def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def parse_int_coordinate(value: Any) -> int:
    """Парсинг числа из ячейки таблицы ROI (неотрицательное int)."""
    try:
        return max(0, int(round(float(str(value).strip()))))
    except (TypeError, ValueError):
        return 0


def coords_list_from_params(params: Mapping[str, Any]) -> List[int]:
    """[x, y, width, height] из словаря контролов."""
    return [
        max(0, _coerce_int(params.get(_X))),
        max(0, _coerce_int(params.get(_Y))),
        max(0, _coerce_int(params.get(_W))),
        max(0, _coerce_int(params.get(_H))),
    ]


def params_from_coords_list(coords: List[int]) -> Dict[str, Any]:
    """Словарь контролов из списка из четырёх int."""
    c = coords + [0, 0, 0, 0]
    return {
        _X: max(0, int(c[0])),
        _Y: max(0, int(c[1])),
        _W: max(0, int(c[2])),
        _H: max(0, int(c[3])),
    }


def params_to_rect(params: Mapping[str, Any]) -> Dict[str, int]:
    """Прямоугольник для подписи и отладки."""
    return {
        "x": max(0, _coerce_int(params.get(_X))),
        "y": max(0, _coerce_int(params.get(_Y))),
        "width": max(0, _coerce_int(params.get(_W))),
        "height": max(0, _coerce_int(params.get(_H))),
    }


def rect_to_params(rect: Mapping[str, Any], _base: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Словарь контролов из rect (ключи x, y, width, height)."""
    return {
        _X: max(0, _coerce_int(rect.get("x"))),
        _Y: max(0, _coerce_int(rect.get("y"))),
        _W: max(0, _coerce_int(rect.get("width"))),
        _H: max(0, _coerce_int(rect.get("height"))),
    }


def _legacy_entry_to_coords(entry: Mapping[str, Any]) -> List[int]:
    """Старый формат {params, rect} → [x,y,w,h]."""
    rect = entry.get("rect")
    if isinstance(rect, dict) and rect:
        return coords_list_from_params(
            {
                _X: rect.get("x", 0),
                _Y: rect.get("y", 0),
                _W: rect.get("width", 0),
                _H: rect.get("height", 0),
            }
        )
    params = entry.get("params") or {}
    x_min = _coerce_int(params.get("x_min"))
    x_max = _coerce_int(params.get("x_max"))
    return [
        max(0, x_min),
        max(0, _coerce_int(params.get("y_delta"))),
        max(0, x_max - x_min),
        max(0, _coerce_int(params.get("height"))),
    ]


def _is_nested_crop_regions(raw: Mapping[str, Any]) -> bool:
    """Формат: camera_id → { region_name → [x,y,w,h] }."""
    if not raw:
        return False
    first = next(iter(raw.values()))
    if not isinstance(first, dict) or not first:
        return False
    inner = next(iter(first.values()))
    return isinstance(inner, list)


def _is_legacy_flat_crop_regions(raw: Mapping[str, Any]) -> bool:
    """Плоский формат: region_name → {params, rect}."""
    if not raw:
        return False
    first = next(iter(raw.values()))
    if not isinstance(first, dict):
        return False
    return "params" in first or isinstance(first.get("rect"), dict)


def normalize_crop_regions_payload(
    raw: Any,
    *,
    default_camera: str,
) -> Dict[str, Dict[str, List[int]]]:
    """
    Привести processor.crop_regions к виду camera → region → [x,y,w,h].

    Поддерживает:
    - плоский legacy: {region: {params, rect}} → под default_camera;
    - вложенный: {camera: {region: [x,y,w,h]}}.
    """
    if not isinstance(raw, dict) or not raw:
        return {}
    if _is_nested_crop_regions(raw):
        result: Dict[str, Dict[str, List[int]]] = {}
        for cam, rmap in raw.items():
            if not isinstance(rmap, dict):
                continue
            inner: Dict[str, List[int]] = {}
            for rn, coords in rmap.items():
                if isinstance(coords, list) and len(coords) == 4:
                    inner[str(rn)] = [max(0, _coerce_int(coords[i])) for i in range(4)]
            if inner:
                result[str(cam)] = inner
        return result
    if _is_legacy_flat_crop_regions(raw):
        out_flat: Dict[str, List[int]] = {}
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            out_flat[str(name)] = _legacy_entry_to_coords(entry)
        return {default_camera: out_flat} if out_flat else {}
    return {}


def merge_crop_regions_payload(regions_by_camera: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Снимок для processor.crop_regions: camera → region → [x, y, width, height].

    Значения регионов — списки из четырёх int или dict контролов (через coords_list_from_params).
    """
    out: Dict[str, Any] = {}
    for cam, rmap in regions_by_camera.items():
        if not isinstance(rmap, dict):
            continue
        inner: Dict[str, Any] = {}
        for rn, val in rmap.items():
            if isinstance(val, list) and len(val) == 4:
                inner[str(rn)] = [max(0, int(val[i])) for i in range(4)]
            elif isinstance(val, dict):
                inner[str(rn)] = coords_list_from_params(val)
        if inner:
            out[str(cam)] = inner
    return out


def regions_to_table_rows(regions: Mapping[str, List[int]]) -> List[Dict[str, Any]]:
    """Строки таблицы для текущей камеры: region_name → coords."""
    rows: List[Dict[str, Any]] = []
    for name in sorted(regions.keys()):
        coords = regions[name]
        if not isinstance(coords, list) or len(coords) != 4:
            continue
        x, y, w, h = (max(0, int(coords[i])) for i in range(4))
        rows.append(
            {
                "region_id": name,
                "name": name,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
            }
        )
    return rows
