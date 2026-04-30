"""Спецификация SHM-региона: единый источник правды о размерах буфера.

ShmRegionSpec описывает один именованный регион разделяемой памяти.
Размеры (width, height) берутся из CameraConfig / ProcessorConfig / RendererConfig,
а не из глобальных констант — это исключает рассогласование.

Использование:
    spec = camera_config.shm_region()
    # → ShmRegionSpec(name="camera_0_frame", width=640, height=480, channels=3, slots=3)
    spec.shape  # → (480, 640, 3)  — shape в стиле numpy (H, W, C)
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase


class ShmRegionSpec(SchemaBase):
    """Спецификация одного SHM-региона.

    Поля:
        name     — уникальное имя региона (например "camera_0_frame")
        width    — ширина кадра в пикселях
        height   — высота кадра в пикселях
        channels — количество каналов (по умолчанию 3: BGR)
        slots    — количество SHM-слотов (для Ring Buffer = ring_buffer_size)
    """

    name: str
    width: int
    height: int
    channels: int = 3
    slots: int = 1

    @property
    def shape(self) -> tuple[int, int, int]:
        """Shape в стиле numpy: (height, width, channels)."""
        return (self.height, self.width, self.channels)

    def with_size(self, width: int, height: int) -> "ShmRegionSpec":
        """Создать копию спецификации с новыми размерами.

        Используется при динамическом пересоздании SHM под нативное
        разрешение камеры (shm_native_resolution=True).
        """
        return ShmRegionSpec(
            name=self.name,
            width=width,
            height=height,
            channels=self.channels,
            slots=self.slots,
        )
