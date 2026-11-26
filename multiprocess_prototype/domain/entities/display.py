# -*- coding: utf-8 -*-
"""
Entities дисплеев: привязка (DisplayInstance) и определение (DisplayDefinition).

DisplayInstance — привязка узла-источника (node_id) к дисплею (display_id).
DisplayDefinition — определение дисплея: SHM-параметры (размер, формат, ring buffer)
  и render-параметры (position, fit, scale, rotate, flip, crop).

Различие:
  - DisplayInstance = «какой выход ноды отправляет кадры в какой дисплей» (привязка).
  - DisplayDefinition = «что такое этот дисплей: его размеры, формат, параметры
    отображения» (определение). Живёт в top-level секции ``displays`` рецепта.

Контракт DisplayDefinition (module-contract: new-lite):
  - Назначение: описание физического дисплея (SHM-сегмент) и его render-параметров.
  - Инвариант (Task 1.2): id уникален в пределах рецепта; scale 10..1000;
    rotate in {0,90,180,270}; flip/fit/format — enum. НЕ enforce'ится здесь,
    а добавляется в Task 1.2 (field_validator'ы).
  - Dict at Boundary: на границе процесса передаётся как list[dict],
    НЕ как Pydantic-объект.
  - extra="forbid" — лишние поля вызовут ValidationError.

Формат display_bindings (v3):
    YAML-рецепты используют ключи «node_id»/«display_id».
    Устаревший формат «source»/«display» больше НЕ принимается
    (extra='forbid' бросит ValidationError).
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, field_validator
from typing_extensions import Annotated, Self

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase

# Допустимые значения enum-полей DisplayDefinition
_VALID_ROTATE = frozenset({0, 90, 180, 270})
_VALID_FLIP = frozenset({"none", "horizontal", "vertical", "both"})
_VALID_FIT = frozenset({"contain", "cover", "stretch", "none"})
_VALID_FORMAT = frozenset({"BGR", "RGB", "GRAY", "RGBA"})
_VALID_PLATE_MODE = frozenset({"hold", "silence", "trigger"})
_PLATE_AFTER_S_RANGE = (1, 600)


# ======================================================================
# DisplayInstance — привязка node_id → display_id
# ======================================================================


class DisplayInstance(SchemaBase):
    """Привязка узла топологии к дисплею вывода."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    node_id: Annotated[str, FieldMeta("Идентификатор узла-источника (process.plugin.port или process.plugin)")]
    display_id: Annotated[str, FieldMeta("Идентификатор дисплея из DisplayRegistry")]

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать DisplayInstance из словаря (ожидает ключи node_id/display_id)."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return self.model_dump(mode="json")


# ======================================================================
# Вспомогательные frozen-модели для вложенных полей DisplayDefinition
# ======================================================================


class DisplayPosition(SchemaBase):
    """Позиция окна дисплея на экране (пиксели)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: Annotated[int, FieldMeta("Позиция X (пиксели)")] = 0
    y: Annotated[int, FieldMeta("Позиция Y (пиксели)")] = 0


class DisplayCrop(SchemaBase):
    """Прямоугольник обрезки в пикселях SHM-кадра."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: Annotated[int, FieldMeta("Левый край обрезки (пиксели)")] = 0
    y: Annotated[int, FieldMeta("Верхний край обрезки (пиксели)")] = 0
    w: Annotated[int, FieldMeta("Ширина области обрезки (пиксели)")] = 0
    h: Annotated[int, FieldMeta("Высота области обрезки (пиксели)")] = 0


# ======================================================================
# DisplayDefinition — определение дисплея (SHM + render)
# ======================================================================


class DisplayDefinition(SchemaBase):
    """Определение дисплея: SHM-параметры и render-настройки.

    Живёт в секции ``displays`` рецепта (top-level).
    НЕ путать с DisplayInstance (привязка node_id → display_id,
    секция ``blueprint.displays``).

    SHM-параметры (width/height/format/fps_limit/ring_buffer_blocks) определяют
    физический размер кадра в разделяемой памяти и не зависят от render-параметров.

    Render-параметры (position/fit/scale/rotate/flip/crop) влияют только на
    отображение в окне превью GUI — кадр в SHM не трансформируется.

    Плашка (П6): что экран показывает, когда кадра нет. ``plate_mode`` —
    ``hold`` (держать последний кадр, как раньше), ``silence`` (нет кадров
    ``plate_after_s`` секунд), ``trigger`` (триггер был, а кадр не пришёл в срок).
    ``plate_after_s`` — порог тишины, целое 1..600 с, только для ``silence``.
    ``plate_text`` — шаблон надписи, ``plate_source`` — источник кадров экрана
    (``<процесс>.<плагин>``); пустая строка — не задано.

    Валидация значений (scale 10..1000, rotate enum, и т.д.) добавляется
    в Task 1.2 — здесь только структура + extra="forbid".
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
    )

    # --- SHM-параметры ---
    id: Annotated[str, FieldMeta("Уникальный ID дисплея (ключ ссылки)")]
    name: Annotated[str, FieldMeta("Отображаемое имя дисплея")] = ""
    # Показывать ли дисплей в главной области GUI (toggle вкл/выкл).
    # Бэк-совместимо: отсутствует в YAML → True (показывать).
    enabled: Annotated[bool, FieldMeta("Показывать дисплей в главной области GUI")] = True
    width: Annotated[int, FieldMeta("Ширина SHM-сегмента (пиксели)")] = 1280
    height: Annotated[int, FieldMeta("Высота SHM-сегмента (пиксели)")] = 720
    format: Annotated[str, FieldMeta("Формат пикселей: BGR | RGB | GRAY | RGBA")] = "BGR"
    fps_limit: Annotated[float, FieldMeta("Лимит FPS (0.0 = без лимита)")] = 30.0
    ring_buffer_blocks: Annotated[int, FieldMeta("Количество блоков ring-buffer SHM")] = 3

    # --- Render-параметры (только preview, не влияют на SHM) ---
    position: Annotated[DisplayPosition, FieldMeta("Позиция окна на экране")] = DisplayPosition()
    fit: Annotated[str, FieldMeta("Режим вписывания: contain | cover | stretch | none")] = "contain"
    scale: Annotated[int, FieldMeta("Масштаб preview в % (100 = 1:1)")] = 100
    rotate: Annotated[int, FieldMeta("Поворот preview: 0 | 90 | 180 | 270")] = 0
    flip: Annotated[str, FieldMeta("Отражение: none | horizontal | vertical | both")] = "none"
    crop: Annotated[DisplayCrop | None, FieldMeta("Обрезка {x,y,w,h} или null")] = None

    # --- Плашка (П6): только GUI, на SHM и бэкенд-дисплей не влияет ---
    plate_mode: Annotated[str, FieldMeta("Режим плашки: hold | silence | trigger")] = "hold"
    plate_after_s: Annotated[int, FieldMeta("Порог тишины для режима silence (секунды, 1..600)")] = 2
    plate_text: Annotated[str, FieldMeta("Шаблон надписи плашки")] = ""
    plate_source: Annotated[str, FieldMeta("Источник кадров экрана для плашки")] = ""

    # ------------------------------------------------------------------
    # Валидаторы вложенных моделей (dict → frozen-модель)
    # ------------------------------------------------------------------

    @field_validator("position", mode="before")
    @classmethod
    def _coerce_position(cls, v: Any) -> Any:
        """dict → DisplayPosition."""
        if isinstance(v, dict):
            return DisplayPosition(**v)
        return v

    @field_validator("crop", mode="before")
    @classmethod
    def _coerce_crop(cls, v: Any) -> Any:
        """dict | None → DisplayCrop | None."""
        if v is None:
            return None
        if isinstance(v, dict):
            return DisplayCrop(**v)
        return v

    # ------------------------------------------------------------------
    # Валидаторы инвариантов (Task 1.2)
    # ------------------------------------------------------------------

    @field_validator("scale", mode="after")
    @classmethod
    def _validate_scale(cls, v: int) -> int:
        """Масштаб preview должен быть в диапазоне [10, 1000] %."""
        if not (10 <= v <= 1000):
            raise ValueError(f"scale должен быть в диапазоне 10..1000 %, получено: {v}")
        return v

    @field_validator("rotate", mode="after")
    @classmethod
    def _validate_rotate(cls, v: int) -> int:
        """Угол поворота preview должен быть одним из: 0, 90, 180, 270."""
        if v not in _VALID_ROTATE:
            raise ValueError(f"rotate должен быть одним из {sorted(_VALID_ROTATE)}, получено: {v}")
        return v

    @field_validator("flip", mode="after")
    @classmethod
    def _validate_flip(cls, v: str) -> str:
        """Режим отражения должен быть одним из: none, horizontal, vertical, both."""
        if v not in _VALID_FLIP:
            raise ValueError(f"flip должен быть одним из {sorted(_VALID_FLIP)}, получено: '{v}'")
        return v

    @field_validator("fit", mode="after")
    @classmethod
    def _validate_fit(cls, v: str) -> str:
        """Режим вписывания должен быть одним из: contain, cover, stretch, none."""
        if v not in _VALID_FIT:
            raise ValueError(f"fit должен быть одним из {sorted(_VALID_FIT)}, получено: '{v}'")
        return v

    @field_validator("format", mode="after")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        """Формат пикселей должен быть одним из: BGR, RGB, GRAY, RGBA."""
        if v not in _VALID_FORMAT:
            raise ValueError(f"format должен быть одним из {sorted(_VALID_FORMAT)}, получено: '{v}'")
        return v

    @field_validator("plate_mode", mode="after")
    @classmethod
    def _validate_plate_mode(cls, v: str) -> str:
        """Режим плашки должен быть одним из: hold, silence, trigger."""
        if v not in _VALID_PLATE_MODE:
            # Полученное значение в сообщение не кладём (W2-c2c, приёмка).
            raise ValueError(f"plate_mode должен быть одним из {sorted(_VALID_PLATE_MODE)}")
        return v

    @field_validator("plate_after_s", mode="before")
    @classmethod
    def _validate_plate_after_s(cls, v: Any) -> int:
        """Порог тишины — строго int 1..600: до приведения типов, ``True``/``"5"``/``5.0`` не проходят."""
        low, high = _PLATE_AFTER_S_RANGE
        if type(v) is not int or not low <= v <= high:
            raise ValueError(f"plate_after_s должен быть целым числом {low}..{high}, получено: {v!r}")
        return v

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создать DisplayDefinition из словаря.

        Pre-condition: data содержит обязательный ключ ``id``.
        Post-condition: возвращённый объект frozen и валиден.
        """
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (готов к передаче через Dict-at-Boundary).

        Post-condition: результат — чистый dict (без Pydantic-объектов),
        пригодный для pickle/JSON/YAML.
        """
        return self.model_dump(mode="json")
