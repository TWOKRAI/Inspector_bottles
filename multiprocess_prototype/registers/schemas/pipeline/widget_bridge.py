"""DEPRECATED: use registers.pipeline.widget_bridge directly."""

from multiprocess_prototype.registers.pipeline.widget_bridge import (
    apply_crop_nested_to_pipeline,
    apply_post_list_to_pipeline,
    crop_nested_from_pipeline,
    pipeline_config_from_register,
    post_list_from_pipeline,
)

__all__ = [
    "apply_crop_nested_to_pipeline",
    "apply_post_list_to_pipeline",
    "crop_nested_from_pipeline",
    "pipeline_config_from_register",
    "post_list_from_pipeline",
]
