"""PortSchema — описание порта для визуализации в NodeItem.

Используется для передачи информации о портах плагина в NodeItem.
Не зависит от Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortSchema:
    """Описание одного порта плагина для визуализации.

    Атрибуты:
        name: имя порта ("frame", "mask", "stats")
        direction: направление порта ("input" | "output")
        dtype: тип данных в MIME-подобном формате ("image/bgr", "any", "image/*")
        optional: если True — порт может быть не подключен
    """

    name: str
    direction: str  # "input" | "output"
    dtype: str = "any"
    optional: bool = False
