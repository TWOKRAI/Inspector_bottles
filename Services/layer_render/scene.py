# -*- coding: utf-8 -*-
"""Кадр сцены одной функцией (Task 2.5): `render_scene(background, placed, effects, rng)`.

Порядок, один для всех потребителей (сим через `SceneCompositor`, превью редактора, генератор обучения):
фон (`render_background`) -> объекты по порядку `placed` (`composite`) -> эффекты кадра (`apply_effects`, только
при непустом `effects`). Выход — новый RGB uint8 `(h, w, 3)`.

Чего функция НЕ делает (граница LR-003):

- Не отсекает объекты по видимости и не сообщает, какие попали в кадр: объект вне кадра ничего не рисует (так ведёт
  себя `composite`). Отсечение и паспорта — понятие ленты, их держит `SceneCompositor`.
- Не сворачивает фон: стек рисуется как дан (`render_background` даёт один кадр для свёрнутого и несвёрнутого).
- Не создаёт `rng`: поток эффектов принадлежит вызывающему (контракт rng, LR-001).

Модуль импортирует только `background`, `compose`, `effects`, `interfaces` пакета и `numpy`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from Services.layer_render.background import render_background
from Services.layer_render.compose import composite
from Services.layer_render.effects import EffectSpec, apply_effects
from Services.layer_render.interfaces import ScrollingTile, SolidFill


def _as_python_int(value: object) -> int | None:
    """`int`/`np.integer` -> Python `int`; `bool` (в том числе `np.bool_`), float и прочее -> `None`."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        return None
    return int(value)


@dataclass(frozen=True, eq=False)
class SceneBackground:
    """Фон кадра: стек слоёв, размер кадра и привязка к сцене.

    Pre: `layers` — последовательность `SolidFill | ScrollingTile` снизу вверх (пусто — чёрный кадр), иначе
    `ValueError` с индексом элемента; `size_wh` — `tuple`/`list` из двух `int`/`np.integer` >= 0 (bool, float, ndarray
    — `ValueError`). `center_y`, `scroll_px`, `origin_xy` НЕ проверяются: числа даёт вызывающий (целый `belt_y_px`
    допустим).
    Post: `layers` хранится tuple (правка списка вызывающего кадр не меняет), `size_wh` — пара Python `int`.
    `scroll_px` — сдвиг тайлов по X как в `render_background`; `origin_xy` — левый верхний угол окна в координатах
    сцены; `center_y` — Y центра полосы тайла в тех же координатах. `eq=False` — сравнение по идентичности.
    """

    layers: Sequence[SolidFill | ScrollingTile]
    size_wh: tuple[int, int]
    center_y: float
    scroll_px: int = 0
    origin_xy: tuple[int, int] = (0, 0)

    def __post_init__(self) -> None:
        size = self.size_wh
        if not isinstance(size, (tuple, list)) or len(size) != 2:
            raise ValueError(f"SceneBackground.size_wh: ожидалась пара (w, h) в tuple/list, получено {size!r}")
        w, h = _as_python_int(size[0]), _as_python_int(size[1])
        if w is None or h is None:
            raise ValueError(f"SceneBackground.size_wh: ожидались целые (не bool/float), получено {size!r}")
        if w < 0 or h < 0:
            raise ValueError(f"SceneBackground.size_wh: размеры должны быть >= 0, получено {size!r}")
        layers = tuple(self.layers)
        for i, layer in enumerate(layers):
            if not isinstance(layer, (SolidFill, ScrollingTile)):
                raise ValueError(
                    f"SceneBackground.layers[{i}]: ожидался SolidFill или ScrollingTile, получено {type(layer)!r}"
                )
        object.__setattr__(self, "size_wh", (w, h))
        object.__setattr__(self, "layers", layers)


@dataclass(frozen=True, eq=False)
class PlacedObject:
    """Объект, поставленный в кадр: RGBA-спрайт и центр в координатах КАДРА (дробный, как у `composite`).

    Pre: `rgba` — `np.ndarray` формы `(h, w, 4)` dtype `uint8`, иначе `ValueError` с shape и dtype.
    Post: массив НЕ копируется и не пишется: read-only спрайт принимается как есть (`LayeredObject.render()` отдаёт
    именно такой). `center_xy` не проверяется. `eq=False` — сравнение по идентичности (поле-ndarray).
    """

    rgba: np.ndarray
    center_xy: tuple[float, float]

    def __post_init__(self) -> None:
        rgba = self.rgba
        if not isinstance(rgba, np.ndarray) or rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
            shape = getattr(rgba, "shape", None)
            dtype = getattr(rgba, "dtype", None)
            raise ValueError(
                f"PlacedObject.rgba: ожидался ndarray (h, w, 4) uint8, получено shape={shape}, dtype={dtype}"
            )


def render_scene(
    background: SceneBackground,
    placed: Sequence[PlacedObject],
    effects: Sequence[EffectSpec],
    rng: np.random.Generator | None,
) -> np.ndarray:
    """Кадр сцены: фон -> объекты в порядке `placed` -> эффекты кадра. Выход — новый RGB uint8 `(h, w, 3)`.

    Pre: порядок проверок, до любого рисования: (1) элемент `placed` не `PlacedObject` — `ValueError` с индексом;
    (2) элемент `effects` не `EffectSpec` — `ValueError` с индексом; (3) непустой `effects` при `rng=None` —
    `ValueError`, в тексте `rng`.
    Post: пустой `effects` — ноль розыгрышей `rng`, `rng` может быть `None`, `apply_effects` не зовётся (она при
    пустом списке только копирует кадр). Непустой — один вызов `apply_effects(frame, effects, rng)` после всех
    объектов. Входы (`rgba`, `image` тайлов) не меняются; два вызова дают разные массивы. Объект за кадром ничего не
    рисует, видимость не сообщается.
    """
    placed_items = tuple(placed)
    effect_items = tuple(effects)
    for i, item in enumerate(placed_items):
        if not isinstance(item, PlacedObject):
            raise ValueError(f"render_scene.placed[{i}]: ожидался PlacedObject, получено {type(item)!r}")
    for i, spec in enumerate(effect_items):
        if not isinstance(spec, EffectSpec):
            raise ValueError(f"render_scene.effects[{i}]: ожидался EffectSpec, получено {type(spec)!r}")
    if effect_items and rng is None:
        raise ValueError("render_scene: для непустого effects нужен rng (np.random.Generator), получено None")

    w, h = background.size_wh
    frame = np.empty((h, w, 3), dtype=np.uint8)
    render_background(
        frame,
        background.layers,
        scroll_px=background.scroll_px,
        origin_xy=background.origin_xy,
        center_y=background.center_y,
    )
    for item in placed_items:
        frame = composite(frame, item.rgba, item.center_xy)
    if effect_items:
        frame = apply_effects(frame, effect_items, rng)
    return frame
