# -*- coding: utf-8 -*-
"""Превью пресета — сетка объектов по сидам в PNG, и ограда путей картинок клиента.

Чистый модуль (numpy/opencv, без процесса и плагина): хост превью — отдельный процесс
`layers` (плагин `Plugins.sim.layer_preview`), чтобы рендер не держал поток команд
процесса сцены (ревью 1.2a S1: 8x160 на реальном пресете — ~87 мс, почти всё — `make()`).

- `validate_preview_request(seeds, tile_px)` — пределы запроса, `PreviewLimitError`
  (хост отвечает `bad_request`): 1..16 сидов >= 0, `tile_px` 16..256 и бюджет
  `len(seeds) * tile_px**2 <= 8 * 160**2`.
- `render_preview_grid(preset, seeds, tile_px)` — `(png_bytes, tiles)`; объект —
  `make(f"preview-{seed}", 0.0, default_rng(seed))`, вписан в квадрат `tile_px` на сером
  (90,90,90) с сохранением пропорций, тайлы в одну строку. `ObjectFactory` кэшируется на
  одну запись по каноническому JSON пресета (картинки на диске кэш не версирует).
- `render_layout(preset, seed)` — каждый слой пресета отдельной RGBA-картинкой в номинале
  (Task 1.3h-a): `{class_name, canvas_px, layers[{name, png_b64, center_px, size_px, origin_px}]}`.
- `confine_preset_paths(preset, allowed_roots)` — каждый путь картинки (`catalog_dir`,
  `sprite_source` кроме `class://`) после `resolve()` лежит в одном из корней, иначе
  `ValueError(OUTSIDE_ROOTS_MESSAGE)` — ОДИН текст, не зависящий от существования файла.
  Файловую систему картинок не читает (только `Path.resolve()`).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

import cv2
import numpy as np

from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.layered_object import canvas_size
from Services.line_sim.core.preset import CLASS_SPRITE_SOURCE, ScenePreset

PREVIEW_MAX_SEEDS = 16
PREVIEW_DEFAULT_SEEDS: tuple[int, ...] = tuple(range(1, 9))
PREVIEW_DEFAULT_TILE_PX = 160
PREVIEW_MIN_TILE_PX = 16
PREVIEW_MAX_TILE_PX = 256
#: Ревью 1.2a S1: бюджет — не больше дефолтной сетки 8x160 (16 сидов — только при tile_px <= 113).
PREVIEW_PIXEL_BUDGET = 8 * 160**2
PREVIEW_BG_RGB = (90, 90, 90)

OUTSIDE_ROOTS_MESSAGE = "preset: путь изображения вне разрешённых каталогов (корень репозитория, каталог пресета)"

__all__ = [
    "OUTSIDE_ROOTS_MESSAGE",
    "PREVIEW_DEFAULT_SEEDS",
    "PREVIEW_DEFAULT_TILE_PX",
    "PREVIEW_MAX_SEEDS",
    "PREVIEW_MAX_TILE_PX",
    "PREVIEW_MIN_TILE_PX",
    "PREVIEW_PIXEL_BUDGET",
    "PreviewLimitError",
    "confine_preset_paths",
    "render_layout",
    "render_preview_grid",
    "validate_preview_request",
]


class PreviewLimitError(ValueError):
    """Запрос превью вне пределов (сиды, `tile_px`, бюджет пикселей) — `bad_request` у хоста."""


#: Одна запись (канонический JSON пресета, фабрика). Замена кортежа целиком; фабрика превью
#: своя — `force_defect_next()` на ней не зовётся никогда, `make()` другого состояния не держит.
_factory_cache: tuple[str, ObjectFactory] | None = None


def validate_preview_request(seeds: object, tile_px: object) -> None:
    """Pre-проверка запроса; нарушение — `PreviewLimitError` с текстом для клиента."""
    if (
        not isinstance(seeds, list)
        or not 1 <= len(seeds) <= PREVIEW_MAX_SEEDS
        or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in seeds)
    ):
        raise PreviewLimitError(f"preset.preview: seeds — список 1..{PREVIEW_MAX_SEEDS} целых >= 0")
    if (
        not isinstance(tile_px, int)
        or isinstance(tile_px, bool)
        or not PREVIEW_MIN_TILE_PX <= tile_px <= PREVIEW_MAX_TILE_PX
    ):
        raise PreviewLimitError(f"preset.preview: tile_px — целое {PREVIEW_MIN_TILE_PX}..{PREVIEW_MAX_TILE_PX}")
    pixels = len(seeds) * tile_px**2
    if pixels > PREVIEW_PIXEL_BUDGET:
        raise PreviewLimitError(
            f"preset.preview: len(seeds) * tile_px**2 = {pixels} > {PREVIEW_PIXEL_BUDGET} "
            "(бюджет 8 тайлов по 160 px) — меньше сидов или мельче tile_px"
        )


def render_preview_grid(preset: ScenePreset, seeds: Sequence[int], tile_px: int) -> tuple[bytes, list[dict]]:
    """Сетка объектов пресета -> (PNG-байты, `[{seed, class_name, layer_params}]` в порядке seeds).

    Pre: `validate_preview_request(seeds, tile_px)` (вызывается здесь же). Ошибки сборки
    фабрики/объекта пробрасываются как есть (хост отвечает `invalid`)."""
    validate_preview_request(list(seeds), tile_px)
    factory = _cached_factory(preset)
    tiles_rgb: list[np.ndarray] = []
    tiles: list[dict] = []
    for seed in seeds:
        obj = factory.make(f"preview-{seed}", 0.0, np.random.default_rng(seed))
        tiles_rgb.append(_fit_tile(obj.render(), tile_px))
        passport = obj.passport.to_dict()
        tiles.append({"seed": seed, "class_name": passport["class_name"], "layer_params": passport["layer_params"]})
    ok, png = cv2.imencode(".png", cv2.cvtColor(np.hstack(tiles_rgb), cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("cv2.imencode(.png) вернул False")
    return png.tobytes(), tiles


def render_layout(preset: ScenePreset, seed: int) -> dict:
    """Слои пресета по отдельности (номинал, угол объекта 0) -> `{class_name, canvas_px, layers}`.

    Тот же `np.random.default_rng(seed)`, что у плиток `render_preview_grid`, поэтому `class_name`
    для seed совпадает с плиткой. `layers[i]` — `{name, png_b64 (RGBA PNG), center_px [ox, oy]
    (смещение центра слоя от центра объекта, Y вниз), size_px [w, h]}` в порядке пресета;
    `origin_px [x, y]` — целый левый верхний угол слоя на канве `canvas_px`, ровно как его ставит
    лента (без пересчёта из `center_px`); `canvas_px = [w, h]` — размер канвы объекта из тех же
    слоёв (`layered_object.canvas_size`, без рендера). Ошибки
    сборки фабрики/слоёв пробрасываются как есть (хост отвечает `invalid`)."""
    class_name, placed = _cached_factory(preset).nominal_layers(np.random.default_rng(seed))
    canvas_w, canvas_h = canvas_size([(rgba, ox, oy) for _, rgba, ox, oy in placed])
    layers = []
    for name, rgba, ox, oy in placed:
        ok, png = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
        if not ok:
            raise ValueError(f"cv2.imencode(.png) вернул False (слой '{name}')")
        h, w = rgba.shape[:2]
        # Угол, куда лента кладёт слой: `composite` берёт `int(round(cx - sw / 2))` с
        # cx = w_канвы / 2 + ox (банкирское округление Python, не JS Math.round).
        origin = [int(round(canvas_w / 2.0 + ox - w / 2.0)), int(round(canvas_h / 2.0 + oy - h / 2.0))]
        layers.append(
            {
                "name": name,
                "png_b64": base64.b64encode(png.tobytes()).decode("ascii"),
                "center_px": [ox, oy],
                "size_px": [w, h],
                "origin_px": origin,
            }
        )
    return {"class_name": class_name, "canvas_px": [canvas_w, canvas_h], "layers": layers}


def confine_preset_paths(preset: ScenePreset, allowed_roots: Iterable[str | Path]) -> None:
    """Все пути картинок пресета — внутри `allowed_roots` (после `resolve()` с обеих сторон),
    иначе `ValueError(OUTSIDE_ROOTS_MESSAGE)`; петля симлинков — тот же отказ."""
    roots = [Path(root).resolve() for root in allowed_roots]
    values = [preset.catalog_dir] if preset.catalog_dir is not None else []
    values += [layer.sprite_source for layer in preset.layers if layer.sprite_source != CLASS_SPRITE_SOURCE]
    for value in values:
        try:
            resolved = Path(preset.resolve_path(value)).resolve()
        except (OSError, RuntimeError):
            raise ValueError(OUTSIDE_ROOTS_MESSAGE) from None
        if not any(resolved.is_relative_to(root) for root in roots):
            raise ValueError(OUTSIDE_ROOTS_MESSAGE)


def _cached_factory(preset: ScenePreset) -> ObjectFactory:
    global _factory_cache
    key = json.dumps(preset.to_dict(), sort_keys=True, ensure_ascii=False)
    cached = _factory_cache
    if cached is not None and cached[0] == key:
        return cached[1]
    factory = ObjectFactory(preset)
    _factory_cache = (key, factory)
    return factory


def _fit_tile(rgba: np.ndarray, tile_px: int) -> np.ndarray:
    """RGBA объекта -> RGB-квадрат `tile_px` на сером: пропорции сохранены (INTER_AREA),
    объект по центру, наложение по альфе."""
    tile = np.full((tile_px, tile_px, 3), PREVIEW_BG_RGB, dtype=np.uint8)
    h, w = rgba.shape[:2]
    if h == 0 or w == 0:
        return tile
    scale = tile_px / max(h, w)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    small = cv2.resize(rgba, (new_w, new_h), interpolation=cv2.INTER_AREA)
    alpha = small[:, :, 3:4].astype(np.float32) / 255.0
    y0, x0 = (tile_px - new_h) // 2, (tile_px - new_w) // 2
    region = tile[y0 : y0 + new_h, x0 : x0 + new_w].astype(np.float32)
    tile[y0 : y0 + new_h, x0 : x0 + new_w] = (small[:, :, :3] * alpha + region * (1.0 - alpha)).astype(np.uint8)
    return tile
