# -*- coding: utf-8 -*-
"""
domain/protocols/display_catalog.py — Protocol для реестра дисплеев (read+write).

DisplayCatalog — контракт read+write store, который domain ждёт от DisplayRegistry.
Phase C создал адаптер DisplayCatalogFromRegistry; Phase F расширил до writable store.
Phase 5: render-поля добавлены в DisplaySpec; recipe-scoped persist.

Sidecar-dataclasses:
  DisplaySpec — описание дисплея (id, имя, конфигурация SHM + render-параметры, метаданные).

Маппинг DisplaySpec ↔ DisplayDefinition:
  DisplaySpec (frozen dataclass, domain protocol) содержит ВСЕ поля определения дисплея
  (SHM + render). Render-поля зеркалят DisplayDefinition (domain entity).
  Helper-функции spec_to_definition() / definition_to_spec() обеспечивают round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DisplaySpec:
    """Описание дисплея из реестра (SHM + render-параметры).

    Первые два поля обязательны, остальные — конфигурационные дефолты.
    metadata оставлен для расширяемости (пользовательские ключи).

    Render-поля (position, fit, scale, rotate, flip, crop) влияют только
    на отображение в окне превью GUI — SHM-кадр не трансформируется.
    Render-поля живут в DisplaySpec (domain protocol) и DisplayDefinition
    (domain entity), НЕ в DisplayEntry (framework, ADR-130 generic).
    """

    display_id: str
    display_name: str
    width: int = 1280
    height: int = 720
    format: str = "BGR"
    fps_limit: float = 30.0
    ring_buffer_blocks: int = 3

    # --- Render-параметры (зеркало DisplayDefinition) ---
    position: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0})
    fit: str = "contain"
    scale: int = 100
    rotate: int = 0
    flip: str = "none"
    crop: dict[str, int] | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


class DisplayCatalog(Protocol):
    """Контракт read+write store для реестра дисплеев.

    Read-методы (Phase C): list_displays, resolve.
    Write-методы (Phase F): register, unregister, has, persist.

    Реализации: DisplayCatalogFromRegistry (adapter), FakeDisplayCatalog (тесты).
    """

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        """Вернуть все доступные дисплеи."""
        ...

    def resolve(self, display_id: str) -> DisplaySpec | None:
        """Найти дисплей по id. Возвращает None если не найден."""
        ...

    def register(self, spec: DisplaySpec) -> None:
        """Зарегистрировать дисплей. Бросает ValueError при дубликате id."""
        ...

    def unregister(self, display_id: str) -> bool:
        """Удалить дисплей по id. Возвращает True если удалён, False если не найден."""
        ...

    def has(self, display_id: str) -> bool:
        """Проверить наличие дисплея по id."""
        ...

    def persist(self) -> None:
        """Сохранить текущее состояние в YAML (путь знает adapter)."""
        ...


# ======================================================================
# Маппинг DisplaySpec ↔ DisplayDefinition (round-trip render-полей)
# ======================================================================


def definition_to_spec(defn: Any) -> DisplaySpec:
    """Конвертировать DisplayDefinition (domain entity) в DisplaySpec.

    Принимает объект с полями DisplayDefinition (SchemaBase).
    Render-поля (position/fit/scale/rotate/flip/crop) мапятся в DisplaySpec.

    Args:
        defn: DisplayDefinition инстанс (или duck-type с такими же атрибутами).

    Returns:
        Frozen DisplaySpec со всеми SHM + render полями.
    """
    # position: DisplayPosition (frozen model) → dict {x, y}
    pos = defn.position
    position_dict: dict[str, int] = {"x": pos.x, "y": pos.y} if pos is not None else {"x": 0, "y": 0}

    # crop: DisplayCrop | None → dict | None
    crop_dict: dict[str, int] | None = None
    if defn.crop is not None:
        crop_dict = {"x": defn.crop.x, "y": defn.crop.y, "w": defn.crop.w, "h": defn.crop.h}

    return DisplaySpec(
        display_id=defn.id,
        display_name=defn.name,
        width=defn.width,
        height=defn.height,
        format=defn.format,
        fps_limit=defn.fps_limit,
        ring_buffer_blocks=defn.ring_buffer_blocks,
        position=position_dict,
        fit=defn.fit,
        scale=defn.scale,
        rotate=defn.rotate,
        flip=defn.flip,
        crop=crop_dict,
    )


def spec_to_definition_dict(spec: DisplaySpec) -> dict[str, Any]:
    """Конвертировать DisplaySpec в dict, пригодный для DisplayDefinition.from_dict().

    Используется при записи в рецепт: DisplaySpec → dict → Recipe.displays.

    Args:
        spec: DisplaySpec инстанс.

    Returns:
        dict с полями, принимаемыми DisplayDefinition.from_dict().
    """
    result: dict[str, Any] = {
        "id": spec.display_id,
        "name": spec.display_name,
        "width": spec.width,
        "height": spec.height,
        "format": spec.format,
        "fps_limit": spec.fps_limit,
        "ring_buffer_blocks": spec.ring_buffer_blocks,
        "position": dict(spec.position) if spec.position else {"x": 0, "y": 0},
        "fit": spec.fit,
        "scale": spec.scale,
        "rotate": spec.rotate,
        "flip": spec.flip,
        "crop": dict(spec.crop) if spec.crop else None,
    }
    return result


__all__ = [
    "DisplaySpec",
    "DisplayCatalog",
    "definition_to_spec",
    "spec_to_definition_dict",
]
