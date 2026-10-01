# -*- coding: utf-8 -*-
"""Стек фона `layer_render` (Task 1.1): разбор конфига, свёртка стека, рисование в кадр.

Три функции:

- `background_layers_from_config(items, load_image)` — YAML-список -> `[SolidFill | ScrollingTile]`
  (снизу вверх). Схему проверяет целиком ДО загрузки картинок.
- `fold_background(layers)` — свёртка стека ради скорости: `SolidFill` прячет всё под собой,
  первый тайл над подложкой запекается с её цветом в непрозрачный RGB-тайл. Результат рисуется
  тем же `render_background`, что и несвёрнутый стек, пиксель в пиксель.
- `render_background(frame, layers, *, scroll_px, origin_xy, center_y)` — рисует стек в `frame`
  (HxWx3 RGB uint8) на месте.

Пакет ничего не знает про энкодер, ленту и движок сцены: вызывающий отдаёт готовый сдвиг
`scroll_px` числом.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from Services.layer_render.interfaces import ScrollingTile, SolidFill

_BLACK = SolidFill(color_rgb=(0, 0, 0))


def background_layers_from_config(
    items: object, load_image: Callable[[str], np.ndarray | None]
) -> list[SolidFill | ScrollingTile]:
    """Разобрать `background_layers` из конфига: слои снизу вверх.

    Элемент — словарь ровно с одним ключом: `solid: [R, G, B]` (три целых 0..255, bool/float/str
    не принимаются) или `tile: <путь>` (путь отдаётся в `load_image` как есть). Любое нарушение схемы
    — `ValueError("background_layers[<i>]: <причина>: <repr элемента>")`; пустой список — тоже
    `ValueError`. Схема проверяется целиком ДО первого вызова `load_image`.

    `load_image(path)` вернул `None` — «нечитаема, об ошибке уже доложено»: слой выбрасывается,
    порядок остальных сохраняется. Все слои выброшены -> пустой список (вызывающий рисует чёрный кадр).
    """
    if not isinstance(items, list) or not items:
        raise ValueError(f"background_layers: ожидался непустой список слоёв, получено {items!r}")
    for i, item in enumerate(items):
        _validate_item(i, item)

    layers: list[SolidFill | ScrollingTile] = []
    for item in items:
        if "solid" in item:
            layers.append(SolidFill(color_rgb=item["solid"]))
            continue
        image = load_image(item["tile"])
        if image is not None:
            layers.append(ScrollingTile(image=image))
    return layers


def _validate_item(i: int, item: object) -> None:
    """Проверить один элемент списка слоёв; нарушение -> `ValueError` с индексом и repr элемента."""

    def bad(reason: str) -> ValueError:
        return ValueError(f"background_layers[{i}]: {reason}: {item!r}")

    if not isinstance(item, dict):
        raise bad("элемент должен быть словарём {solid: [R, G, B]} или {tile: путь}")
    if len(item) != 1 or next(iter(item)) not in ("solid", "tile"):
        raise bad("ожидался ровно один ключ: 'solid' или 'tile'")
    if "tile" in item:
        if not isinstance(item["tile"], str) or not item["tile"]:
            raise bad("значение 'tile' должно быть непустой строкой-путём")
        return
    # Единственное место правил цвета — `SolidFill.__post_init__`; здесь его ошибка дополняется индексом и repr.
    try:
        SolidFill(color_rgb=item["solid"])
    except ValueError as exc:
        raise bad(str(exc)) from exc


def _fill(frame: np.ndarray, color_rgb: tuple[int, int, int]) -> None:
    """Залить кадр цветом. Присваивание кортежа целиком (`frame[...] = (r, g, b)`) в разы медленнее
    (бродкаст по последней оси на каждый пиксель) — заливаем по каналам, серый — одним `fill`."""
    r, g, b = color_rgb
    if r == g == b:
        frame.fill(r)
        return
    frame[:, :, 0] = r
    frame[:, :, 1] = g
    frame[:, :, 2] = b


def _over(rgba: np.ndarray, base: np.ndarray) -> np.ndarray:
    """RGBA-тайл «over» подложка `base` (uint16, бродкаст до `(h, w, 3)`) -> uint8 `(h, w, 3)`.

    `out = (a*t + (255-a)*base + 127) // 255`: при альфе 255 даёт тайл, при 0 — подложку, ровно.
    Одна формула и для свёртки, и для общего пути — их совпадение пиксель в пиксель держится на ней.
    """
    alpha = rgba[:, :, 3:4].astype(np.uint16)
    out = (alpha * rgba[:, :, :3].astype(np.uint16) + (255 - alpha) * base + 127) // 255
    return out.astype(np.uint8)


def fold_background(layers: Sequence[SolidFill | ScrollingTile]) -> list[SolidFill | ScrollingTile]:
    """Свернуть стек: `[SolidFill, (ScrollingTile непрозрачный RGB)?, *остальные тайлы]`.

    `SolidFill` прячет всё под собой — отсчёт идёт от последнего. Подложка без заливки — чёрный.
    Первый тайл над подложкой запекается с её цветом в непрозрачный RGB-тайл (RGB-тайл берётся
    как есть, приватную копию делает `ScrollingTile`); тайлы выше первого остаются RGBA-слоями для общего
    пути. Входные массивы не меняются.
    """
    base = _BLACK
    tiles: list[ScrollingTile] = []
    for layer in layers:
        if isinstance(layer, SolidFill):
            base, tiles = layer, []
        else:
            tiles.append(layer)
    if not tiles:
        return [base]

    first, rest = tiles[0].image, tiles[1:]
    if first.shape[2] == 3:
        baked = first  # `ScrollingTile(...)` ниже сам берёт приватную копию — отдельный `.copy()` не нужен
    else:
        baked = _over(first, np.array(base.color_rgb, dtype=np.uint16))
    return [base, ScrollingTile(image=baked), *rest]


def render_background(
    frame: np.ndarray,
    layers: Sequence[SolidFill | ScrollingTile],
    *,
    scroll_px: int,
    origin_xy: tuple[int, int],
    center_y: float,
) -> None:
    """Нарисовать стек в `frame` (HxWx3 RGB uint8) на месте: чёрный, затем слои снизу вверх.

    `scroll_px` — сдвиг тайлов по X в пикселях (положительный — тайл едет вправо), `origin_xy` — левый
    верхний угол окна камеры в координатах сцены, `center_y` — Y центра полосы тайла в тех же
    координатах. Тайл индексируется циклически по ширине (`% tw`); по высоте кладётся симметрично
    `center_y`, строки кадра вне полосы тайла не трогаются (виден слой ниже).
    """
    h, w = frame.shape[:2]
    if not layers or not isinstance(layers[0], SolidFill):
        _fill(frame, (0, 0, 0))
    origin_x, origin_y = origin_xy
    for layer in layers:
        if isinstance(layer, SolidFill):
            _fill(frame, layer.color_rgb)
            continue
        tile = layer.image
        th, tw = tile.shape[:2]
        top = int(round(center_y - th / 2))
        # Видимые строки кадра — непрерывный отрезок [r0, r1): строка кадра y берёт строку тайла y+origin_y-top.
        r0 = max(0, top - origin_y)
        r1 = min(h, top + th - origin_y)
        if r0 >= r1:
            continue
        cols = (np.arange(w) + origin_x - scroll_px) % tw
        rows = np.arange(r0, r1) + origin_y - top
        part = tile.take(rows, axis=0).take(cols, axis=1)
        if tile.shape[2] == 3:
            frame[r0:r1] = part
        else:
            frame[r0:r1] = _over(part, frame[r0:r1].astype(np.uint16))
