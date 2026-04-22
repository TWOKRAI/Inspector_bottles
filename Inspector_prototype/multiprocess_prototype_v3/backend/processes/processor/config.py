"""Processor service configuration."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module import (
    ProcessLaunchConfig,
    ProcessPriorityLevel,
)
from pydantic import Field


@register_schema("ProcessorConfigV3")
class ProcessorConfig(ProcessLaunchConfig):
    process_name: str = "processor"
    process_class: str = "multiprocess_prototype_v3.backend.processes.processor.process.ProcessorProcess"
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    resolution_width: int = 640
    resolution_height: int = 480
    color_lower: list[int] = Field(default_factory=lambda: [0, 0, 150])
    color_upper: list[int] = Field(default_factory=lambda: [100, 100, 255])
    min_area: int = 500
    max_area: int = 50000

    @property
    def memory(self) -> dict:
        return {
            "processor_mask": (self.resolution_height, self.resolution_width, 3),
            "coll": 2,
        }
