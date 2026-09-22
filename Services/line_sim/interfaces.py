"""Публичный контракт line_sim: слой, аугментация слоя, паспорт объекта, Protocol сцены.

Единицы — пиксели (`offset_px`); миллиметры придут вместе с редактором Ф7.

Конвенция поворота (одна на весь модуль): угол в градусах, положительный —
против часовой стрелки (CCW) на экране, ось Y направлена вниз, как в OpenCV
(`cv2.getRotationMatrix2D`, `Services.dataset_gen.core.compose.rotate_expand`).
Пример-литерал: метка справа от центра (+5, 0) при повороте объекта на +90°
оказывается сверху (0, -5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

LayerMode = Literal["static", "augmented", "defect"]
RangeF = tuple[float, float]

# Источник спрайта: сырой RGBA-массив, callable без аргументов (зовётся один раз
# на объект) или строка-идентификатор (форма на dict-границе; загрузка по id — Task 3.2).
SpriteSource = str | np.ndarray | Callable[[], np.ndarray]

AUGMENT_FIELDS: tuple[str, ...] = ("offset_x_px", "offset_y_px", "angle_deg", "scale", "hue_shift_deg")


class LayerAugment(BaseModel):
    """Диапазоны вариации слоя `(lo, hi)`; дефолт каждого — «нет вариации».

    Значения добавляются к базовому трансформу слоя, `scale` — умножается.
    Порядок `lo <= hi` проверяет `LayerSpec` (там известно имя слоя для текста ошибки).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    offset_x_px: RangeF = (0.0, 0.0)
    offset_y_px: RangeF = (0.0, 0.0)
    angle_deg: RangeF = (0.0, 0.0)
    scale: RangeF = (1.0, 1.0)
    hue_shift_deg: RangeF = (0.0, 0.0)


class LayerSpec(BaseModel):
    """Слой объекта: спрайт + трансформ относительно центра объекта.

    Режимы: `static` — всегда рисуется как есть; `augmented` — трансформ
    варьируется по `augment` (выборка один раз при создании объекта);
    `defect` — рисуется с вероятностью `defect_probability`.

    Трансформ: `offset_px` — от центра объекта до центра холста спрайта;
    `angle_deg` — поворот слоя относительно объекта, CCW, ось Y вниз
    (конвенция `rotate_expand`, см. докстринг модуля); `scale` — множитель.

    Pre:
      - `augment` задан только при `mode == "augmented"`
      - в каждом диапазоне `augment` lo <= hi; scale > 0 (и нижняя граница диапазона scale)
      - `defect_probability` в [0, 1]
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    mode: LayerMode
    sprite_source: SpriteSource
    offset_px: RangeF = (0.0, 0.0)
    angle_deg: float = 0.0
    scale: float = Field(default=1.0, gt=0.0)
    augment: LayerAugment | None = None
    defect_probability: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_augment(self) -> LayerSpec:
        if self.augment is None:
            return self
        if self.mode != "augmented":
            raise ValueError(
                f"слой '{self.name}': augment задан при mode='{self.mode}' — "
                "диапазоны допустимы только у слоя mode='augmented'"
            )
        for fname in AUGMENT_FIELDS:
            lo, hi = getattr(self.augment, fname)
            if lo > hi:
                raise ValueError(f"слой '{self.name}': augment.{fname}: lo={lo} > hi={hi}")
        if self.augment.scale[0] <= 0:
            raise ValueError(f"слой '{self.name}': augment.scale: нижняя граница должна быть > 0")
        return self


@dataclass(frozen=True)
class ObjectPassport:
    """Паспорт объекта на ленте: что это, как повёрнут, есть ли дефект.

    `layer_params` — фактически выбранные при создании объекта значения:
    ключ — имя слоя; для `augmented` — пять полей `LayerAugment` (числа),
    для `defect` — `{"active": bool}`. Заполняет `LayeredObject`.
    """

    object_id: str
    class_name: str
    angle_deg: float
    defect: str | None
    spawn_encoder: float
    layer_params: dict[str, dict[str, Any]] = field(default_factory=dict)


class SceneCompositor(Protocol):
    """Контракт сцены «лента с объектами» (реализация — Task 3.3).

    Координаты `camera_rect` и единицы уточняет Task 3.3; здесь фиксирована форма.
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
