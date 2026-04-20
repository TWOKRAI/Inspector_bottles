"""DEPRECATED: use registers.payloads.crop_regions directly."""

from multiprocess_prototype_v3.registers.payloads.crop_regions import (
    coords_list_from_params,
    merge_crop_regions_payload,
    normalize_crop_regions_payload,
    params_from_coords_list,
    params_to_rect,
    parse_int_coordinate,
    rect_to_params,
    regions_to_table_rows,
)

__all__ = [
    "coords_list_from_params",
    "merge_crop_regions_payload",
    "normalize_crop_regions_payload",
    "params_from_coords_list",
    "params_to_rect",
    "parse_int_coordinate",
    "rect_to_params",
    "regions_to_table_rows",
]
