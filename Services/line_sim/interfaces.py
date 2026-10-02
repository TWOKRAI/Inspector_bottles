"""Публичный контракт line_sim: паспорт объекта, Protocol сцены; слой и аугментация слоя — реэкспорт.

Слой (`LayerSpec`, `LayerAugment`, `LayerMode`, `RangeF`, `SpriteSource`, `AUGMENT_FIELDS`) живёт в
`Services.layer_render.layers` (Task 2.3) и реэкспортируется отсюда тем же объектом. Конвенция поворота
(угол CCW, ось Y вниз, пример-литерал) и единицы — в докстринге `Services.layer_render.layers`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from Services.layer_render.layers import (
    AUGMENT_FIELDS,
    LayerAugment,
    LayerMode,
    LayerSpec,
    RangeF,
    SpriteSource,
)

__all__ = [
    "AUGMENT_FIELDS",
    "LayerAugment",
    "LayerMode",
    "LayerSpec",
    "ObjectPassport",
    "RangeF",
    "SceneCompositorProtocol",
    "SpriteSource",
]


@dataclass(frozen=True)
class ObjectPassport:
    """Паспорт объекта на ленте: что это, как повёрнут, есть ли дефект.

    `layer_params` — фактически выбранные при создании объекта значения:
    ключ — имя слоя; для `augmented` — пять полей `LayerAugment` (числа),
    для `defect` — `{"active": bool}`. Слой с `color_rgb` добавляет ключ
    `"color_rgb": [r, g, b]` (после сдвига тона слоя, если он был) — у `static`-слоя
    с заливкой это единственный ключ записи. Заполняет `LayeredObject`.

    `lateral_px` — смещение объекта поперёк хода ленты в пикселях кадра (знаковое,
    `+` = вниз по кадру, `0.0` = по центру полосы `belt_y_px`). Проставляет `ObjectSpawner`
    при спавне (`lateral_offset_px`); кадр и истина робота (`object_robot_xy`) читают его.
    """

    object_id: str
    class_name: str
    angle_deg: float
    defect: str | None
    spawn_encoder: float
    layer_params: dict[str, dict[str, Any]] = field(default_factory=dict)
    lateral_px: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация на границе (Dict at Boundary, Task 3.4): только JSON-совместимые
        типы — numpy-скаляры внутри `layer_params` приводятся к нативным `float`/`bool`/`int`
        через `.item()`, остальное копируется как есть."""
        return {
            "object_id": self.object_id,
            "class_name": self.class_name,
            "angle_deg": float(self.angle_deg),
            "defect": self.defect,
            "spawn_encoder": float(self.spawn_encoder),
            "layer_params": _json_safe(self.layer_params),
            "lateral_px": float(self.lateral_px),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObjectPassport:
        """Обратное к `to_dict()`. Post: `from_dict(p.to_dict()) == p`."""
        return cls(
            object_id=data["object_id"],
            class_name=data["class_name"],
            angle_deg=float(data["angle_deg"]),
            defect=data["defect"],
            spawn_encoder=float(data["spawn_encoder"]),
            layer_params=dict(data.get("layer_params") or {}),
            lateral_px=float(data.get("lateral_px", 0.0)),
        )


def _json_safe(value: Any) -> Any:
    """Рекурсивно привести numpy-скаляры (`np.float32`/`np.bool_`/…) к нативным типам
    через `.item()` — контейнеры (`dict`/`list`) обходятся, остальное не трогается."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class SceneCompositorProtocol(Protocol):
    """Контракт сцены «лента с объектами». Реализация — `Services.line_sim.core.
    scene_compositor.SceneCompositor` (Task 3.4); имя Protocol переименовано из
    `SceneCompositor` в `SceneCompositorProtocol` при подключении конкретного класса
    (LS-009), чтобы оба символа сосуществовали в публичном API без коллизии имён.

    Координаты `camera_rect` и единицы уточняет Task 3.4; здесь фиксирована форма.
    """

    def spawn(self, obj: Any, spawn_encoder: float) -> None:
        """Положить готовый объект (`LayeredObject`) на ленту в позицию энкодера."""
        ...

    def despawn_stale(self, now_encoder: float) -> int:
        """Убрать объекты, уехавшие за зону видимости; вернуть число убранных."""
        ...

    def render(
        self, now_encoder: float, camera_rect: tuple[float, float, float, float]
    ) -> tuple[np.ndarray, list[ObjectPassport]]:
        """Кадр сцены + паспорта объектов, попавших в кадр."""
        ...
