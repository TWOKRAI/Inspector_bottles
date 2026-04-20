"""GUI payload helpers for ROI and post-processing widgets."""

from .crop_regions import (
    coords_list_from_params,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_from_coords_list,
    regions_to_table_rows as crop_regions_to_table_rows,
)
from .post_processing import (
    PostProcessingRegionEntry,
    default_new_region,
    merge_post_processing_payload,
    normalize_post_processing_payload,
    normalize_region_entry,
    regions_to_table_rows as post_regions_to_table_rows,
)

__all__ = [
    "coords_list_from_params",
    "params_from_coords_list",
    "normalize_crop_regions_payload",
    "merge_crop_regions_payload",
    "crop_regions_to_table_rows",
    "PostProcessingRegionEntry",
    "default_new_region",
    "normalize_region_entry",
    "normalize_post_processing_payload",
    "merge_post_processing_payload",
    "post_regions_to_table_rows",
]
