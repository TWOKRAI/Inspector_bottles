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
    """Конфигурация одного процессора обработки кадров.

    camera_id — привязка к конкретной камере. Определяет process_name
    (processor_0, processor_1, ...) и SHM-слот маски (processor_0_mask, ...).
    """

    process_name: str = "processor_0"
    process_class: str = (
        "multiprocess_prototype_v3.backend.processes.processor.process.ProcessorProcess"
    )
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH

    # --- Привязка к камере ---
    camera_id: int = 0

    resolution_width: int = 640
    resolution_height: int = 480
    color_lower: list[int] = Field(default_factory=lambda: [0, 0, 150])
    color_upper: list[int] = Field(default_factory=lambda: [100, 100, 255])
    min_area: int = 500
    max_area: int = 50000

    def model_post_init(self, __context: object) -> None:
        """process_name всегда соответствует camera_id."""
        object.__setattr__(self, "process_name", f"processor_{self.camera_id}")

    @property
    def memory(self) -> dict:
        """SHM layout: маска привязана к camera_id процессора."""
        return {
            f"processor_{self.camera_id}_mask": (self.resolution_height, self.resolution_width, 3),
            "coll": 2,
        }
