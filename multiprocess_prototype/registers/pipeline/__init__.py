"""Pipeline domain: hierarchical vision pipeline schemas and widget bridge."""

from .rect import Rect
from .region import Region
from .schemas import CameraNode, CameraRegistersUnion, Pipeline, RegionNode
from .widget_bridge import (
    apply_crop_nested_to_pipeline,
    apply_post_list_to_pipeline,
    crop_nested_from_pipeline,
    pipeline_config_from_register,
    post_list_from_pipeline,
)

__all__ = [
    "Rect",
    "Region",
    "CameraRegistersUnion",
    "RegionNode",
    "CameraNode",
    "Pipeline",
    "pipeline_config_from_register",
    "crop_nested_from_pipeline",
    "apply_crop_nested_to_pipeline",
    "post_list_from_pipeline",
    "apply_post_list_to_pipeline",
]
