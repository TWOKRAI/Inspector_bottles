"""DEPRECATED: use registers.payloads.post_processing directly."""

from multiprocess_prototype.registers.payloads.post_processing import (
    PostProcessingRegionEntry,
    coords_label,
    default_new_region,
    merge_post_processing_payload,
    normalize_post_processing_payload,
    normalize_region_entry,
    regions_to_table_rows,
)

__all__ = [
    "PostProcessingRegionEntry",
    "coords_label",
    "default_new_region",
    "merge_post_processing_payload",
    "normalize_post_processing_payload",
    "normalize_region_entry",
    "regions_to_table_rows",
]
