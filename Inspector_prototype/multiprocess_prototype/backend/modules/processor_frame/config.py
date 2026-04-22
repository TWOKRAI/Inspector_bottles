# multiprocess_prototype/backend/modules/processor_frame/config.py
"""
Конфигурация процесса обработки кадров.

Поля, совпадающие с регистром GUI, берутся из registers/schemas/processing_tab/boot.py
и метаданных ProcessorRegisters (один источник правды).
"""

from typing import Annotated, List

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)
from multiprocess_framework.modules.process_module import ProcessPriorityLevel

from multiprocess_prototype.backend.configs.base_config import ProcessConfigBase
from multiprocess_prototype.registers.schemas.processing_tab import (
    ProcessorRegisters,
    processor_process_boot_values,
)

_BOOT = processor_process_boot_values()

_PROCESSOR_CLASS_PATH = (
    "multiprocess_prototype.backend.processes.processor.process.ProcessorProcess"
)


def _pm(field: str):
    return ProcessorRegisters.get_field_meta(field)


_m_min = _pm("min_area")
_m_max = _pm("max_area")
_m_cl = _pm("color_lower")
_m_cu = _pm("color_upper")


@register_schema("ProcessorConfig")
class ProcessorConfig(ProcessConfigBase):
    """Конфигурация процесса обработки кадров."""

    process_name: str = "processor"
    class_path: str = _PROCESSOR_CLASS_PATH
    priority: ProcessPriorityLevel = ProcessPriorityLevel.HIGH
    resolution_width: int = 640
    resolution_height: int = 480

    min_area: Annotated[
        int,
        FieldMeta(
            _m_min.description if _m_min else "Мин. площадь",
            min=_m_min.min if _m_min else 10,
            max=_m_min.max if _m_min else 5000,
            unit=(_m_min.unit if _m_min else "") or "",
            info=_m_min.info if _m_min else "",
        ),
    ] = _BOOT["min_area"]

    max_area: Annotated[
        int,
        FieldMeta(
            _m_max.description if _m_max else "Макс. площадь",
            min=_m_max.min if _m_max else 0,
            max=_m_max.max if _m_max else 50000,
            unit=(_m_max.unit if _m_max else "") or "",
            info=_m_max.info if _m_max else "",
        ),
    ] = _BOOT["max_area"]

    color_lower: Annotated[
        List[int],
        FieldMeta(
            _m_cl.description if _m_cl else "BGR Lower",
            info=_m_cl.info if _m_cl else "",
        ),
    ] = _BOOT["color_lower"]

    color_upper: Annotated[
        List[int],
        FieldMeta(
            _m_cu.description if _m_cu else "BGR Upper",
            info=_m_cu.info if _m_cu else "",
        ),
    ] = _BOOT["color_upper"]

    @property
    def memory(self) -> dict:
        return {"processor_mask": (self.resolution_height, self.resolution_width, 3), "coll": 2}
