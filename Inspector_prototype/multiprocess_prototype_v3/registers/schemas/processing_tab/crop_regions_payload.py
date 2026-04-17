"""Redirect: registers.schemas.processing_tab.crop_regions_payload → registers.gui_payload.crop_regions_payload."""

from multiprocess_prototype_v3.registers.gui_payload.crop_regions_payload import *  # noqa: F401,F403
from multiprocess_prototype_v3.registers.gui_payload.crop_regions_payload import (
    coords_list_from_params,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_from_coords_list,
    regions_to_table_rows,
)

__all__ = [
    "coords_list_from_params",
    "merge_crop_regions_payload",
    "normalize_crop_regions_payload",
    "params_from_coords_list",
    "regions_to_table_rows",
]
