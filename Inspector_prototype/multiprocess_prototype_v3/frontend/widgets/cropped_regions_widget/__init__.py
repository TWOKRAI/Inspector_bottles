# multiprocess_prototype_v3/frontend/widgets/cropped_regions_widget/
"""Изолированный виджет: ROI и crop_regions (BaseWidget + MVP)."""

from .panel_widget import CroppedRegionsPanelWidget
from .params import (
    CROPPED_PARAM_KEYS,
    CroppedParamKey,
    DEFAULT_CROPPED_PARAMS,
    coords_list_from_params,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_from_coords_list,
    params_to_rect,
    rect_to_params,
    region_entry_from_params,
    regions_to_table_rows,
)
from .presenter import CroppedRegionsPresenter
from .roi_panel_registers import (
    CROPPED_ROI_PANEL_REGISTER,
    CroppedRoiPanelRegisters,
    NUMERIC_ROI_FIELD_NAMES,
)
from .schemas import CroppedRegionsTabUiConfig, default_tab_item
from .controls import CroppedAreaControls

__all__ = [
    "CROPPED_ROI_PANEL_REGISTER",
    "CROPPED_PARAM_KEYS",
    "CroppedParamKey",
    "CroppedAreaControls",
    "CroppedRegionsPanelWidget",
    "CroppedRegionsTabUiConfig",
    "CroppedRegionsPresenter",
    "CroppedRoiPanelRegisters",
    "DEFAULT_CROPPED_PARAMS",
    "NUMERIC_ROI_FIELD_NAMES",
    "coords_list_from_params",
    "default_tab_item",
    "merge_crop_regions_payload",
    "normalize_crop_regions_payload",
    "params_from_coords_list",
    "params_to_rect",
    "rect_to_params",
    "region_entry_from_params",
    "regions_to_table_rows",
]
