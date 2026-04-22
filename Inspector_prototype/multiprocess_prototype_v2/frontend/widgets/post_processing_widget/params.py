# multiprocess_prototype/frontend/widgets/post_processing_widget/params.py
"""Payload: camera_id → упорядоченный список регионов постобработки (x1,y1,x2,y2 + флаги)."""

from __future__ import annotations

from multiprocess_prototype_v2.registers.gui_payload.post_processing_payload import (
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
