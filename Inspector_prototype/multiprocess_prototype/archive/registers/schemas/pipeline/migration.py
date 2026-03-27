# -*- coding: utf-8 -*-
"""Миграция legacy crop_regions / post_processing_regions → vision_pipeline / PipelineConfig."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from ..processing_tab.crop_regions_payload import normalize_crop_regions_payload
from ..processing_tab.nested_payload import DEFAULT_CROP_CAMERA_ID
from ..processing_tab.post_processing_payload import normalize_post_processing_payload
from .processing_params import ColorDetectionParams


def _default_color_processing() -> Dict[str, Any]:
    return {
        "enabled": True,
        "params": ColorDetectionParams().model_dump(mode="python"),
    }


def _region_from_crop_coords(coords: List[int]) -> Dict[str, Any]:
    if not isinstance(coords, list) or len(coords) != 4:
        x = y = w = h = 0
    else:
        x, y, w, h = (max(0, int(coords[i])) for i in range(4))
    return {
        "rect": {"x": x, "y": y, "width": w, "height": h},
        "enabled": True,
        "is_main": False,
        "processing_enabled": True,
        "sort_order": 0,
        "processing": {"color_detection": _default_color_processing()},
    }


def migrate_crop_regions_to_pipeline_dict(
    crop_regions: Any,
    *,
    default_camera: str = DEFAULT_CROP_CAMERA_ID,
) -> Dict[str, Any]:
    """
    Нормализованный processor.crop_regions → dict для PipelineConfig.model_validate.

    Каждый ROI получает блок ``color_detection`` с дефолтными ColorDetectionParams.
    """
    if not isinstance(crop_regions, dict) or not crop_regions:
        return {"cameras": {}}
    normalized = normalize_crop_regions_payload(
        crop_regions,
        default_camera=default_camera,
    )
    cameras: Dict[str, Any] = {}
    for cam_id, rmap in normalized.items():
        regions: Dict[str, Any] = {}
        for rname, coords in rmap.items():
            if not isinstance(coords, list) or len(coords) != 4:
                continue
            regions[str(rname)] = _region_from_crop_coords(coords)
        cameras[str(cam_id)] = {"enabled": True, "regions": regions}
    return {"cameras": cameras}


def _rect_dict_from_post_entry(entry: Dict[str, Any]) -> Dict[str, int]:
    x1 = max(0, int(entry.get("x1", 0)))
    y1 = max(0, int(entry.get("y1", 0)))
    x2 = max(0, int(entry.get("x2", 0)))
    y2 = max(0, int(entry.get("y2", 0)))
    x = min(x1, x2)
    y = min(y1, y2)
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    return {"x": x, "y": y, "width": w, "height": h}


def _merge_post_into_cameras(cameras: Dict[str, Any], post_by_cam: Dict[str, List[Dict[str, Any]]]) -> None:
    for cam_id, lst in post_by_cam.items():
        cid = str(cam_id)
        cam = cameras.setdefault(cid, {"enabled": True, "regions": {}})
        if not isinstance(cam, dict):
            continue
        regions = cam.setdefault("regions", {})
        cam["enabled"] = cam.get("enabled", True)
        for order, entry in enumerate(lst):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "region")).strip() or "region"
            rect = _rect_dict_from_post_entry(entry)
            r = regions.get(name)
            if isinstance(r, dict):
                r["rect"] = rect
                r["enabled"] = bool(entry.get("enabled", True))
                r["is_main"] = bool(entry.get("is_main", False))
                r["processing_enabled"] = bool(entry.get("processing_enabled", True))
                r["sort_order"] = int(entry.get("sort_order", order))
                if not r.get("processing"):
                    r["processing"] = {"color_detection": _default_color_processing()}
            else:
                regions[name] = {
                    "rect": rect,
                    "enabled": bool(entry.get("enabled", True)),
                    "is_main": bool(entry.get("is_main", False)),
                    "processing_enabled": bool(entry.get("processing_enabled", True)),
                    "sort_order": int(entry.get("sort_order", order)),
                    "processing": {"color_detection": _default_color_processing()},
                }


def _merge_crop_cameras_into(cameras: Dict[str, Any], from_crop: Dict[str, Any]) -> None:
    for cam_id, cam_data in from_crop.items():
        cid = str(cam_id)
        regions_new = cam_data.get("regions", {}) if isinstance(cam_data, dict) else {}
        if cid not in cameras:
            cameras[cid] = deepcopy(cam_data) if isinstance(cam_data, dict) else {"enabled": True, "regions": {}}
            continue
        existing = cameras[cid]
        if not isinstance(existing, dict):
            cameras[cid] = deepcopy(cam_data) if isinstance(cam_data, dict) else {"enabled": True, "regions": {}}
            continue
        reg = existing.setdefault("regions", {})
        existing["enabled"] = existing.get("enabled", True)
        if not isinstance(regions_new, dict):
            continue
        for rn, rv in regions_new.items():
            if rn in reg and isinstance(reg[rn], dict):
                ex = reg[rn]
                if isinstance(rv, dict) and "rect" in rv:
                    ex["rect"] = deepcopy(rv["rect"])
                if not ex.get("processing"):
                    ex["processing"] = deepcopy(rv.get("processing", {}))
            else:
                reg[rn] = deepcopy(rv) if isinstance(rv, dict) else rv


def merge_legacy_into_vision_pipeline_dict(
    vision_pipeline: Any,
    crop_regions: Any,
    post_processing_regions: Any,
    *,
    default_camera: str = DEFAULT_CROP_CAMERA_ID,
) -> Dict[str, Any]:
    """
    Слить legacy crop/post в дерево камер.

    ``vision_pipeline`` — существующий dict (ключ ``cameras``) или пусто.
    """
    vp_in = vision_pipeline if isinstance(vision_pipeline, dict) else {}
    cams_src = vp_in.get("cameras")
    cameras: Dict[str, Any] = deepcopy(cams_src) if isinstance(cams_src, dict) else {}

    if crop_regions is not None:
        from_crop = migrate_crop_regions_to_pipeline_dict(
            crop_regions,
            default_camera=default_camera,
        ).get("cameras", {})
        if isinstance(from_crop, dict):
            _merge_crop_cameras_into(cameras, from_crop)

    if post_processing_regions is not None:
        post = normalize_post_processing_payload(post_processing_regions)
        if post:
            _merge_post_into_cameras(cameras, post)

    return {"cameras": cameras}


def normalize_processor_register_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Убрать legacy ``crop_regions`` / ``post_processing_regions`` и влить в ``vision_pipeline``.

    Если оба ключа отсутствуют (pop → None), ``vision_pipeline`` не трогаем.
    """
    out = dict(data)
    crop = out.pop("crop_regions", None)
    post = out.pop("post_processing_regions", None)
    if crop is None and post is None:
        return out
    existing_vp = out.get("vision_pipeline")
    if not isinstance(existing_vp, dict):
        existing_vp = {}
    merged = merge_legacy_into_vision_pipeline_dict(existing_vp, crop, post)
    out["vision_pipeline"] = merged
    return out


def migrate_legacy_pipeline_root(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Если заданы ``cameras`` — убрать служебный ``crop_regions`` с корня PipelineConfig.

    Если ``cameras`` пусто, а ``crop_regions`` есть — собрать дерево камер (legacy YAML).
    """
    out = dict(data)
    cr = out.pop("crop_regions", None)
    if out.get("cameras"):
        return out
    if cr is not None:
        merged = migrate_crop_regions_to_pipeline_dict(cr)
        out["cameras"] = merged.get("cameras", {})
    return out
