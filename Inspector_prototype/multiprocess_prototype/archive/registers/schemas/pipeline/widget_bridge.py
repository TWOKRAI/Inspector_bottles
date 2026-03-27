# -*- coding: utf-8 -*-
"""Мост PipelineConfig ↔ виджеты ROI / постобработки (без Qt)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Union

from ..processing_tab.post_processing_payload import normalize_region_entry
from .camera import Camera
from .pipeline_config import PipelineConfig
from .processing_block import ProcessingBlock
from .processing_params import ColorDetectionParams
from .rect import Rect
from .region import Region


def _as_pipeline_config(vp: Union[PipelineConfig, Dict[str, Any], None]) -> PipelineConfig:
    if isinstance(vp, PipelineConfig):
        return vp
    if isinstance(vp, dict):
        return PipelineConfig.model_validate(vp)
    return PipelineConfig()


def pipeline_config_from_register(reg: Any) -> PipelineConfig:
    """Собрать PipelineConfig из атрибута ``vision_pipeline`` регистра."""
    vp = getattr(reg, "vision_pipeline", None)
    return _as_pipeline_config(vp)


def crop_nested_from_pipeline(vp: Union[PipelineConfig, Dict[str, Any], None]) -> Dict[str, Dict[str, List[int]]]:
    """camera_id → region_name → [x, y, width, height]."""
    cfg = _as_pipeline_config(vp)
    out: Dict[str, Dict[str, List[int]]] = {}
    for cam_id, cam in cfg.cameras.items():
        inner: Dict[str, List[int]] = {}
        for rname, region in cam.regions.items():
            inner[rname] = region.rect.to_coords_list()
        if inner:
            out[cam_id] = inner
    return out


def apply_crop_nested_to_pipeline(
    vp: Union[PipelineConfig, Dict[str, Any], None],
    nested: Mapping[str, Mapping[str, Any]],
    *,
    color_lower: List[int],
    color_upper: List[int],
    min_area: int,
    max_area: int,
) -> PipelineConfig:
    """
    Обновить/создать ROI из вложенного dict координат.

    Новые регионы получают блок ``color_detection`` с параметрами из уровня processor.
    """
    cfg = _as_pipeline_config(vp)
    params = ColorDetectionParams(
        color_lower=list(color_lower[:3]),
        color_upper=list(color_upper[:3]),
        min_area=int(min_area),
        max_area=int(max_area),
    )
    for cam_id, rmap in nested.items():
        cid = str(cam_id)
        cam = cfg.cameras.setdefault(cid, Camera())
        if not isinstance(rmap, Mapping):
            continue
        keep: set[str] = set()
        for rname, coords in rmap.items():
            rn = str(rname)
            keep.add(rn)
            rect = Rect.from_coords_list(list(coords) if isinstance(coords, list) else [])
            if rn in cam.regions:
                cam.regions[rn].rect = rect
            else:
                cam.regions[rn] = Region(
                    rect=rect,
                    processing={
                        "color_detection": ProcessingBlock(
                            enabled=True,
                            params=params.model_copy(deep=True),
                        )
                    },
                )
        for stale in [k for k in cam.regions if k not in keep]:
            del cam.regions[stale]
    return cfg


def post_list_from_pipeline(
    vp: Union[PipelineConfig, Dict[str, Any], None],
) -> Dict[str, List[Dict[str, Any]]]:
    """camera_id → список dict, совместимых с ``normalize_region_entry`` (+ sort_order)."""
    cfg = _as_pipeline_config(vp)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cam_id, cam in cfg.cameras.items():
        pairs = sorted(
            cam.regions.items(),
            key=lambda it: (it[1].sort_order, it[0]),
        )
        items: List[Dict[str, Any]] = []
        for rname, region in pairs:
            r = region.rect
            d = normalize_region_entry(
                {
                    "name": rname,
                    "x1": r.x,
                    "y1": r.y,
                    "x2": r.x + r.width,
                    "y2": r.y + r.height,
                    "enabled": region.enabled,
                    "is_main": region.is_main,
                    "processing_enabled": region.processing_enabled,
                }
            )
            d["sort_order"] = region.sort_order
            items.append(d)
        if items:
            out[cam_id] = items
    return out


def apply_post_list_to_pipeline(
    vp: Union[PipelineConfig, Dict[str, Any], None],
    post_by_cam: Mapping[str, List[Mapping[str, Any]]],
) -> PipelineConfig:
    """Применить списки постобработки: прямоугольник и флаги по имени региона."""
    cfg = _as_pipeline_config(vp)
    for cam_id, lst in post_by_cam.items():
        cid = str(cam_id)
        cam = cfg.cameras.setdefault(cid, Camera())
        if not isinstance(lst, list):
            continue
        for i, raw in enumerate(lst):
            if not isinstance(raw, dict):
                continue
            e = normalize_region_entry(raw)
            name = str(e["name"])
            x1, y1, x2, y2 = int(e["x1"]), int(e["y1"]), int(e["x2"]), int(e["y2"])
            rect = Rect(
                x=min(x1, x2),
                y=min(y1, y2),
                width=abs(x2 - x1),
                height=abs(y2 - y1),
            )
            if name in cam.regions:
                reg = cam.regions[name]
                reg.rect = rect
                reg.enabled = bool(e["enabled"])
                reg.is_main = bool(e["is_main"])
                reg.processing_enabled = bool(e["processing_enabled"])
                reg.sort_order = i
            else:
                cam.regions[name] = Region(
                    rect=rect,
                    enabled=bool(e["enabled"]),
                    is_main=bool(e["is_main"]),
                    processing_enabled=bool(e["processing_enabled"]),
                    sort_order=i,
                    processing={
                        "color_detection": ProcessingBlock(
                            enabled=True,
                            params=ColorDetectionParams(),
                        )
                    },
                )
    return cfg
