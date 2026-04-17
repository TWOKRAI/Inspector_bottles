# -*- coding: utf-8 -*-
"""Связь плоского регистра processor (vision_pipeline) с виджетами ROI / постобработки."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from multiprocess_prototype_v3.registers.camera import BaseCameraRegisters
from multiprocess_prototype_v3.registers.gui_payload.post_processing_payload import normalize_region_entry
from multiprocess_prototype_v3.registers.pipeline import CameraNode, Pipeline, RegionNode
from multiprocess_prototype_v3.registers.processings.base_processing import BaseProcessingBlock
from multiprocess_prototype_v3.registers.processings.color_detection import ColorDetectionParams
from multiprocess_prototype_v3.registers.rect import Rect


def pipeline_config_from_register(reg: Any) -> Pipeline:
    raw = getattr(reg, "vision_pipeline", None)
    if isinstance(raw, dict) and raw:
        try:
            return Pipeline.model_validate(raw)
        except Exception:
            pass
    return Pipeline()


def crop_nested_from_pipeline(pipeline: Pipeline) -> Dict[str, Dict[str, List[int]]]:
    out: Dict[str, Dict[str, List[int]]] = {}
    for cam_id, node in (pipeline.cameras or {}).items():
        inner: Dict[str, List[int]] = {}
        for reg_name, reg_node in (getattr(node, "regions", None) or {}).items():
            rect = getattr(reg_node, "rect", None)
            if rect is None:
                continue
            if hasattr(rect, "to_coords_list"):
                inner[str(reg_name)] = rect.to_coords_list()
            elif isinstance(rect, dict):
                inner[str(reg_name)] = Rect.model_validate(rect).to_coords_list()
        out[str(cam_id)] = inner
    return out


def _clamp_bgr(seq: Sequence[int], default: Sequence[int]) -> List[int]:
    s = list(seq) if seq is not None else []
    if len(s) < 3:
        return [int(default[i]) for i in range(3)]
    return [max(0, min(255, int(s[i]))) for i in range(3)]


def _region_node_with_detection(
    coords: Sequence[int],
    *,
    color_lower: Sequence[int],
    color_upper: Sequence[int],
    min_area: int,
    max_area: int,
) -> RegionNode:
    c = list(coords) + [0, 0, 0, 0]
    rect = Rect.from_coords_list(c[:4])
    params = ColorDetectionParams(
        color_lower=_clamp_bgr(color_lower, [0, 0, 150]),
        color_upper=_clamp_bgr(color_upper, [100, 100, 255]),
        min_area=max(10, int(min_area)),
        max_area=int(max_area),
    )
    blk = BaseProcessingBlock(params=params)
    return RegionNode(rect=rect, processing_blocks={"main": blk})


def apply_crop_nested_to_pipeline(
    pipeline: Pipeline,
    nested: Mapping[str, Mapping[str, Sequence[int]]],
    *,
    color_lower: Sequence[int],
    color_upper: Sequence[int],
    min_area: int,
    max_area: int,
) -> Pipeline:
    p = pipeline.model_copy(deep=True)
    cams = dict(p.cameras)
    for cam_id, regions_map in (nested or {}).items():
        key = str(cam_id)
        node = cams.get(key)
        if node is None:
            node = CameraNode(registers=BaseCameraRegisters(), regions={})
        regs = dict(node.regions)
        for rname, coords in (regions_map or {}).items():
            rc = list(coords) if isinstance(coords, (list, tuple)) else []
            regs[str(rname)] = _region_node_with_detection(
                rc,
                color_lower=color_lower,
                color_upper=color_upper,
                min_area=min_area,
                max_area=max_area,
            )
        cams[key] = node.model_copy(update={"regions": regs})
    return p.model_copy(update={"cameras": cams})


def post_list_from_pipeline(pipeline: Pipeline) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cam_id, node in (pipeline.cameras or {}).items():
        pairs = list((getattr(node, "regions", None) or {}).items())
        pairs.sort(key=lambda kv: int(getattr(kv[1], "sort_order", 0)))
        rows: List[Dict[str, Any]] = []
        for reg_name, reg_node in pairs:
            rect = getattr(reg_node, "rect", None)
            if rect is not None and hasattr(rect, "x"):
                x1, y1 = int(rect.x), int(rect.y)
                x2, y2 = x1 + int(rect.width), y1 + int(rect.height)
            else:
                x1 = y1 = x2 = y2 = 0
            rows.append(
                normalize_region_entry(
                    {
                        "name": str(reg_name),
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "enabled": bool(getattr(reg_node, "enabled", True)),
                        "is_main": bool(getattr(reg_node, "is_main", False)),
                        "processing_enabled": bool(getattr(reg_node, "processing_enabled", True)),
                    }
                )
            )
        out[str(cam_id)] = rows
    return out


def apply_post_list_to_pipeline(
    pipeline: Pipeline,
    post_by_camera: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Pipeline:
    p = pipeline.model_copy(deep=True)
    cams = dict(p.cameras)
    for cam_id, rows in (post_by_camera or {}).items():
        key = str(cam_id)
        node = cams.get(key)
        if node is None:
            node = CameraNode(registers=BaseCameraRegisters(), regions={})
        regs: Dict[str, RegionNode] = {}
        for i, raw in enumerate(rows or []):
            row = normalize_region_entry(raw if isinstance(raw, dict) else {})
            name = str(row.get("name") or f"region_{i}")
            x1, y1 = int(row.get("x1", 0)), int(row.get("y1", 0))
            x2, y2 = int(row.get("x2", 0)), int(row.get("y2", 0))
            w, h = max(0, x2 - x1), max(0, y2 - y1)
            rn = RegionNode(
                rect=Rect(x=x1, y=y1, width=w, height=h),
                enabled=bool(row.get("enabled", True)),
                is_main=bool(row.get("is_main", False)),
                processing_enabled=bool(row.get("processing_enabled", True)),
                sort_order=i,
            )
            regs[name] = rn
        cams[key] = node.model_copy(update={"regions": regs})
    return p.model_copy(update={"cameras": cams})
