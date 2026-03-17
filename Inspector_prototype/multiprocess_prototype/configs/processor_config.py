# multiprocess_prototype\configs\processor_config.py
"""
Конфигурация процесса обработки кадров (ProcessorProcess).

ProcessConfigBase + FieldMeta. class_path_from_type, ProcessPriorityLevel, memory.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)
from multiprocess_framework.refactored.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype.configs.base_config import ProcessConfigBase, class_path_from_type
from multiprocess_prototype.processes.processor_process import ProcessorProcess


@register_schema("ProcessorConfig")
class ProcessorConfig(ProcessConfigBase):
    """Конфигурация процесса обработки кадров."""

    process_name: str = "processor"
    class_path: str = class_path_from_type(ProcessorProcess)
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    resolution_width: int = 640
    resolution_height: int = 480
    min_area: Annotated[
        int, FieldMeta("Мин. площадь пятна", min=10, max=10000)
    ] = 500
    color_lower: list = [0, 0, 150]  # нижняя граница BGR для красного
    color_upper: list = [100, 100, 255]  # верхняя граница BGR для красного

    @property
    def memory(self) -> dict:
        return {"processor_mask": (self.resolution_height, self.resolution_width, 3), "coll": 2}
