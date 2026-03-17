"""
Конфигурация процесса обработки кадров (ProcessorProcess).

ProcessConfigBase + FieldMeta для валидации параметров.
build() — HasBuild для process() / add_process().
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase


@register_schema("ProcessorConfig")
class ProcessorConfig(ProcessConfigBase):
    """Конфигурация процесса обработки кадров."""

    process_name: str = "processor"
    resolution_width: int = 640
    resolution_height: int = 480
    min_area: Annotated[
        int, FieldMeta("Мин. площадь пятна", min=10, max=10000)
    ] = 500
    color_lower: list = [0, 0, 150]  # нижняя граница BGR для красного
    color_upper: list = [100, 100, 255]  # верхняя граница BGR для красного

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(ProcessorConfig()))."""
        memory = {"processor_mask": (self.resolution_height, self.resolution_width, 3), "coll": 2}
        proc_dict = self._build_proc_dict(
            "multiprocess_prototype.processes.processor_process.ProcessorProcess",
            priority="high",
            memory=memory,
        )
        return (self.process_name, proc_dict)
