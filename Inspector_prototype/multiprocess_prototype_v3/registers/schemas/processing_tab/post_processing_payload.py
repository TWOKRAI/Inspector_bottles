"""Redirect: registers.schemas.processing_tab.post_processing_payload → registers.gui_payload.post_processing_payload."""

from multiprocess_prototype_v3.registers.gui_payload.post_processing_payload import *  # noqa: F401,F403
from multiprocess_prototype_v3.registers.gui_payload.post_processing_payload import (
    PostProcessingRegionEntry,
    default_new_region,
    merge_post_processing_payload,
    normalize_post_processing_payload,
    normalize_region_entry,
    regions_to_table_rows,
)

__all__ = [
    "PostProcessingRegionEntry",
    "default_new_region",
    "merge_post_processing_payload",
    "normalize_post_processing_payload",
    "normalize_region_entry",
    "regions_to_table_rows",
]
