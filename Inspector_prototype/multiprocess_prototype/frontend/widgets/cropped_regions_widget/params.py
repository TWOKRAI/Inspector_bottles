# multiprocess_prototype/frontend/widgets/cropped_regions_widget/params.py
"""ROI: x, y, width, height; вложенный payload camera → region → [x,y,w,h]."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Mapping, Optional

from multiprocess_prototype.registers.schemas.processing_tab.crop_regions_payload import (
    coords_list_from_params,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_from_coords_list,
    params_to_rect,
    parse_int_coordinate,
    rect_to_params,
    regions_to_table_rows,
)


class CroppedParamKey(StrEnum):
    X = "x"
    Y = "y"
    WIDTH = "width"
    HEIGHT = "height"


CROPPED_PARAM_KEYS: tuple[str, ...] = tuple(k.value for k in CroppedParamKey)

DEFAULT_CROPPED_PARAMS: Dict[str, Any] = {
    CroppedParamKey.X.value: 0,
    CroppedParamKey.Y.value: 0,
    CroppedParamKey.WIDTH.value: 0,
    CroppedParamKey.HEIGHT.value: 0,
}


def region_entry_from_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    """Совместимость: {params, rect} из словаря контролов x,y,width,height."""
    merged = {**DEFAULT_CROPPED_PARAMS}
    for k in CROPPED_PARAM_KEYS:
        if k in params:
            merged[k] = params[k]
    return {"params": merged, "rect": params_to_rect(merged)}
