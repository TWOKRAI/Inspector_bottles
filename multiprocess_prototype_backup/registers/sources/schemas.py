"""SourceTopology — топология источников (Layer 1).

Описывает ЧТО входит в систему:
- Какие камеры, в каких процессах/потоках
- Какие SHM-слоты нужны
- Какие регионы, привязанные к каким камерам
- Где нарезать регионы (same_process / dedicated_processor)

Потребитель: ProcessManager (создаёт процессы, SHM, очереди, каналы Router).
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Dict, Literal, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from ..camera.schemas import BaseCameraRegisters
from ..pipeline.rect import Rect
from ..pipeline.schemas import CameraRegistersUnion

# Routing: topology → ProcessManager
TOPOLOGY_ROUTING = FieldRouting(
    channel="control_topology",
    process_targets=("ProcessManager",),
)


@register_schema("ShmSlotConfigV3")
class ShmSlotConfig(SchemaBase):
    """Спецификация одного SHM-слота."""

    name: Annotated[
        str,
        FieldMeta("Имя SHM", info="Базовое имя блока (auto: camera_0_frame)."),
    ] = ""

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина кадра.", min=1, max=8192, unit="px"),
    ] = 640

    height: Annotated[
        int,
        FieldMeta("Высота", info="Высота кадра.", min=1, max=8192, unit="px"),
    ] = 480

    channels: Annotated[
        int,
        FieldMeta("Каналы", info="3=RGB, 1=Grayscale.", min=1, max=4),
    ] = 3

    ring_slots: Annotated[
        int,
        FieldMeta("Ring-буфер", info="Количество слотов кольцевого буфера.", min=1, max=16),
    ] = 3

    dtype: Annotated[
        str,
        FieldMeta("Тип данных", info="numpy dtype: uint8, float32, ..."),
    ] = "uint8"

    @property
    def size_bytes(self) -> int:
        """Общий размер SHM в байтах (все слоты)."""
        import numpy as np

        return (
            self.width
            * self.height
            * self.channels
            * self.ring_slots
            * np.dtype(self.dtype).itemsize
        )

    @property
    def shape(self) -> tuple[int, int, int]:
        """Форма одного кадра: (height, width, channels)."""
        return (self.height, self.width, self.channels)


@register_schema("RegionSourceConfigV3")
class RegionSourceConfig(SchemaBase):
    """Один регион — area of interest, привязанный к камере по ключу."""

    camera_ref: Annotated[
        str,
        FieldMeta("Камера", info="Ключ камеры-источника (camera_0, camera_1...)."),
    ] = ""

    rect: Rect = Field(default_factory=Rect)

    enabled: Annotated[
        bool,
        FieldMeta("Активен", info="Пропускать если False."),
    ] = True

    is_main: Annotated[
        bool,
        FieldMeta("Основной", info="main_image = полный кадр камеры."),
    ] = False

    processing_enabled: Annotated[
        bool,
        FieldMeta("Обработка", info="Включить processing chain для этого ROI."),
    ] = True

    sort_order: Annotated[
        int,
        FieldMeta("Порядок", info="Порядок в таблице (меньше = выше)."),
    ] = 0

    # SHM для региона (Phase E, по умолчанию off)
    shm_enabled: Annotated[
        bool,
        FieldMeta("Отдельный SHM", info="True → выделить собственный SHM-слот для региона."),
    ] = False

    shm_config: Optional[ShmSlotConfig] = None


@register_schema("CameraSourceConfigV3")
class CameraSourceConfig(SchemaBase):
    """Один источник (камера) — определяет процесс, SHM, тип захвата."""

    camera_id: Annotated[
        int,
        FieldMeta("ID камеры", info="Уникальный числовой ID.", min=0, max=63),
    ] = 0

    camera_type: Annotated[
        str,
        FieldMeta("Тип", info="simulator / webcam / hikvision."),
    ] = "simulator"

    # Процесс/поток
    process_name: Annotated[
        str,
        FieldMeta("Процесс", info="Имя процесса (auto: camera_{id})."),
    ] = ""

    execution_mode: Annotated[
        Literal["process", "thread"],
        FieldMeta("Режим", info="process = отдельный OS-процесс, thread = воркер в существующем."),
    ] = "process"

    # Параметры камеры (DataSchema типа)
    registers: CameraRegistersUnion = Field(default_factory=BaseCameraRegisters)

    # SHM для полного кадра
    shm_config: ShmSlotConfig = Field(default_factory=ShmSlotConfig)

    # Где нарезать регионы
    region_processing: Annotated[
        Literal["same_process", "dedicated_processor"],
        FieldMeta("Нарезка регионов", info="same_process = в камере, dedicated_processor = отдельный процесс."),
    ] = "dedicated_processor"

    region_processor_name: Annotated[
        str,
        FieldMeta("Процессор регионов", info="Имя процесса-обработчика (auto: processor_{id})."),
    ] = ""

    def model_post_init(self, __context: object) -> None:
        """Авто-заполнение имён если пусто."""
        if not self.process_name:
            object.__setattr__(self, "process_name", f"camera_{self.camera_id}")
        if not self.region_processor_name:
            object.__setattr__(self, "region_processor_name", f"processor_{self.camera_id}")

        # SHM config: имя и размеры из registers
        shm = self.shm_config
        if not shm.name:
            regs = self.registers
            new_shm = shm.model_copy(update={
                "name": f"camera_{self.camera_id}_frame",
                "width": getattr(regs, "resolution_width", 640),
                "height": getattr(regs, "resolution_height", 480),
            })
            object.__setattr__(self, "shm_config", new_shm)


@register_schema("SourceTopologyV3")
class SourceTopology(SchemaBase):
    """Полная топология источников — Layer 1, source of truth для ProcessManager."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("ProcessManager",),
    )

    cameras: Annotated[
        Dict[str, CameraSourceConfig],
        FieldMeta("Камеры", info="Все источники."),
    ] = Field(default_factory=dict)

    regions: Annotated[
        Dict[str, RegionSourceConfig],
        FieldMeta("Регионы", info="Все регионы всех камер."),
    ] = Field(default_factory=dict)

    # --- Helpers ---

    def regions_for_camera(self, camera_key: str) -> Dict[str, RegionSourceConfig]:
        """Все регионы, привязанные к камере."""
        return {k: v for k, v in self.regions.items() if v.camera_ref == camera_key}

    def ensure_main_region(self, camera_key: str) -> None:
        """Гарантировать наличие main_image региона для камеры."""
        cam = self.cameras.get(camera_key)
        if cam is None:
            return
        region_key = f"{camera_key}_main"
        if region_key not in self.regions:
            regs = cam.registers
            w = getattr(regs, "resolution_width", 640)
            h = getattr(regs, "resolution_height", 480)
            self.regions[region_key] = RegionSourceConfig(
                camera_ref=camera_key,
                rect=Rect(x=0, y=0, width=w, height=h),
                enabled=True,
                is_main=True,
                processing_enabled=True,
                sort_order=0,
            )


__all__ = [
    "ShmSlotConfig",
    "RegionSourceConfig",
    "CameraSourceConfig",
    "SourceTopology",
    "TOPOLOGY_ROUTING",
]
