# multiprocess_prototype_v3/frontend/widgets/cropped_regions_tab/
"""
Вкладка «Регионы обрезки»: только оболочка.

Фиче-виджет: cropped_regions_widget.
"""

from ...processing.cropped_regions_widget import (
    CROPPED_PARAM_KEYS,
    CROPPED_ROI_PANEL_REGISTER,
    CroppedParamKey,
    CroppedAreaControls,
    CroppedRegionsPanelWidget,
    CroppedRegionsTabUiConfig,
    CroppedRoiPanelRegisters,
    DEFAULT_CROPPED_PARAMS,
    NUMERIC_ROI_FIELD_NAMES,
    default_tab_item,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_to_rect,
    rect_to_params,
    region_entry_from_params,
    regions_to_table_rows,
)
from .widget import CroppedRegionsTabWidget

__all__ = [
    "CROPPED_ROI_PANEL_REGISTER",
    "CROPPED_PARAM_KEYS",
    "CroppedParamKey",
    "CroppedAreaControls",
    "CroppedRegionsPanelWidget",
    "CroppedRegionsTabUiConfig",
    "CroppedRegionsTabWidget",
    "CroppedRoiPanelRegisters",
    "DEFAULT_CROPPED_PARAMS",
    "NUMERIC_ROI_FIELD_NAMES",
    "default_tab_item",
    "merge_crop_regions_payload",
    "normalize_crop_regions_payload",
    "params_to_rect",
    "rect_to_params",
    "region_entry_from_params",
    "regions_to_table_rows",
]
