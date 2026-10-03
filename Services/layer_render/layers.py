"""Стек слоёв объекта: слой, аугментация слоя, розыгрыш и композиция в RGBA (Task 2.3).

Перенесено из `Services.line_sim` дословно: типы — из `line_sim/interfaces.py`, рендер — из
`line_sim/core/layered_object.py`. Модуль не знает паспорта объекта и `line_sim`: `LayeredObject`
(`Services.line_sim.core.layered_object`) собирает паспорт вокруг `compose_layers`.

Единицы — пиксели (`offset_px`); миллиметры придут вместе с редактором Ф7.

Конвенция поворота (одна на весь модуль): угол в градусах, положительный —
против часовой стрелки (CCW) на экране, ось Y направлена вниз, как в OpenCV
(`cv2.getRotationMatrix2D`, `Services.layer_render.compose.rotate_expand`).
Пример-литерал: метка справа от центра (+5, 0) при повороте объекта на +90°
оказывается сверху (0, -5).

Конвенция холста объекта: центр объекта = центр возвращаемого массива
(канва симметрична относительно центра и расширяется под слой, выехавший за
базу; по альфе не обрезается — иначе потерялся бы центр объекта).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Literal, NamedTuple

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from Services.layer_render.compose import composite, rotate_expand

__all__ = [
    "AUGMENT_FIELDS",
    "ComposedLayers",
    "LayerAugment",
    "LayerMode",
    "LayerSpec",
    "RangeF",
    "SpriteSource",
    "canvas_size",
    "compose_layers",
    "json_safe",
    "load_layer_sprite",
    "transform_layer",
]

LayerMode = Literal["static", "augmented", "defect"]
RangeF = tuple[float, float]

# Источник спрайта: сырой RGBA-массив, callable без аргументов (зовётся один раз
# на объект) или строка-идентификатор (форма на dict-границе; загрузку по id делает
# `ObjectFactory`, Services.line_sim.core.factory).
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

    Трансформ применяется в порядке: заливка цветом (`color_rgb`, RGB спрайта := цвет,
    альфа не трогается) -> `scale` -> поворот (`angle_deg`, CCW, ось Y вниз, конвенция
    `rotate_expand`, см. докстринг модуля) -> сдвиг тона (`augment.hue_shift_deg`).
    `offset_px` — от центра объекта до центра холста спрайта.

    Pre:
      - `augment` задан только при `mode == "augmented"`
      - в каждом диапазоне `augment` lo <= hi; scale > 0 (и нижняя граница диапазона scale)
      - `defect_probability` в [0, 1]
      - `color_rgb`, если задан — тройка `int` в диапазоне [0, 255]
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
    color_rgb: tuple[int, int, int] | None = None

    @field_validator("color_rgb", mode="before")
    @classmethod
    def _check_color_rgb(cls, value: Any, info: ValidationInfo) -> Any:
        """До типовой проверки pydantic: длина тройки и диапазон каналов — с именем слоя
        в тексте ошибки (стандартная ошибка pydantic на `tuple[int, int, int]` для
        значения неверной длины имя слоя не несёт)."""
        if value is None:
            return None
        name = info.data.get("name", "?")
        try:
            r, g, b = value
        except (TypeError, ValueError):
            raise ValueError(f"слой '{name}': color_rgb должен быть тройкой (r, g, b), получено {value!r}") from None
        for channel, v in zip("rgb", (r, g, b), strict=True):
            if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 255):
                raise ValueError(f"слой '{name}': color_rgb.{channel}={v!r} — должен быть int в диапазоне [0, 255]")
        return (r, g, b)

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


class ComposedLayers(NamedTuple):
    """Результат `compose_layers`.

    - `rgba` — RGBA uint8 объекта, записываемый (read-only ставит владелец кэша, не эта функция);
    - `layer_params` — выбранные значения по имени слоя (форма — как `ObjectPassport.layer_params`);
    - `active_defects` — имена выпавших/принудительных defect-слоёв в порядке слоёв.
    """

    rgba: np.ndarray
    layer_params: dict[str, dict[str, Any]]
    active_defects: tuple[str, ...]


def load_layer_sprite(layer: LayerSpec) -> np.ndarray:
    """Достать RGBA-спрайт слоя; callable-провайдер зовётся ровно один раз."""
    source = layer.sprite_source
    if isinstance(source, str):
        raise TypeError(
            f"слой '{layer.name}': sprite_source='{source}' — строка-идентификатор; "
            "загрузка спрайта по id — Task 3.2, делает ObjectFactory "
            "(Services.line_sim.core.factory), сюда нужен RGBA-массив или callable"
        )
    sprite = source() if callable(source) else source
    sprite = np.asarray(sprite)
    if sprite.ndim != 3 or sprite.shape[2] != 4 or sprite.dtype != np.uint8:
        raise ValueError(
            f"слой '{layer.name}': ожидался RGBA uint8 HxWx4, получено "
            f"shape={sprite.shape} dtype={sprite.dtype} (нет альфа-канала?)"
        )
    return sprite


def _rotate(sprite: np.ndarray, angle_deg: float) -> np.ndarray:
    """Поворот CCW (ось Y вниз).

    Кратные 90° — `np.rot90` (без интерполяции): `rotate_expand` на 90/180/270 из-за
    sin≈1e-16 в матрице даёт холст на 1 px больше и полупиксельный сдвиг — край
    срезается или размывается (замер: 5x5 на 180° — 36 пикселей альфы, из них 16
    непрозрачных, вместо 25). Прочие углы — `rotate_expand` как есть: замер лида
    (37/45/10° на 5x5, 20x50, 64x64) — площадь альфы в пределах ±2 px от исходной, рамка
    ничего не меняла и снята.
    """
    quarter = angle_deg / 90.0
    if quarter == round(quarter):
        return np.ascontiguousarray(np.rot90(sprite, k=int(round(quarter)) % 4))
    return rotate_expand(sprite, angle_deg)


def _hue_shift(sprite: np.ndarray, deg: float) -> np.ndarray:
    """Сдвиг тона по RGB-каналам через HSV (OpenCV: H = градусы/2); альфа не трогается."""
    hsv = cv2.cvtColor(np.ascontiguousarray(sprite[:, :, :3]), cv2.COLOR_RGB2HSV)
    shift = int(round(deg / 2.0))
    hsv[:, :, 0] = ((hsv[:, :, 0].astype(np.int32) + shift) % 180).astype(np.uint8)
    out = sprite.copy()
    out[:, :, :3] = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return out


def _hue_shift_color(color_rgb: tuple[int, int, int], hue_deg: float) -> tuple[int, int, int]:
    """Заливка слоя `color_rgb`, прогнанная через тот же `_hue_shift`, что и спрайт
    (на 1x1 RGBA-пикселе) — для `layer_params`, где нужно именно применённое значение,
    а не исходный `LayerSpec.color_rgb`. `hue_deg == 0.0` — короткий путь без округления
    HSV-конверсией (нужен static-слою: заливка без вариации должна быть значением как есть)."""
    if hue_deg == 0.0:
        return color_rgb
    pixel = np.zeros((1, 1, 4), dtype=np.uint8)
    pixel[0, 0, 0:3] = color_rgb
    pixel[0, 0, 3] = 255
    shifted = _hue_shift(pixel, hue_deg)
    return (int(shifted[0, 0, 0]), int(shifted[0, 0, 1]), int(shifted[0, 0, 2]))


def _over(canvas_pm: np.ndarray, canvas_a: np.ndarray, sprite: np.ndarray, center_xy: tuple[float, float]):
    """Альфа-«over» спрайта на прозрачную канву через `compose.composite`.

    `composite` умеет только RGB-фон. Канва хранится премультиплицированной
    (rgb*alpha): тогда `composite` даёт ровно премультиплицированный «over»
    (fg*a + bg_pm*(1-a)); альфа считается тем же вызовом с белым спрайтом.
    """
    canvas_pm = composite(canvas_pm, sprite, center_xy)
    white = sprite.copy()
    white[:, :, :3] = 255
    alpha3 = composite(np.repeat(canvas_a[:, :, None], 3, axis=2), white, center_xy)
    return canvas_pm, alpha3[:, :, 0]


def json_safe(value: Any) -> Any:
    """Рекурсивно привести numpy-скаляры (`np.float32`/`np.bool_`/…) к нативным типам
    через `.item()` — контейнеры (`dict`/`list`) обходятся, остальное не трогается."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def canvas_size(placed: list[tuple[np.ndarray, float, float]]) -> tuple[int, int]:
    """Размер симметричной канвы `(w, h)` под слои `[(RGBA, offset_x, offset_y)]` — без рендера.

    Формула та же, что использует `_compose_canvas`: полуразмер = max(|offset| + размер/2),
    вверх до целого, канва чётная (центр объекта в центре). Нужна тем, кому размер канвы
    нужен без самой картинки (`preview.render_layout`)."""
    half_w = max(abs(ox) + s.shape[1] / 2.0 for s, ox, _ in placed)
    half_h = max(abs(oy) + s.shape[0] / 2.0 for s, _, oy in placed)
    return 2 * math.ceil(half_w), 2 * math.ceil(half_h)


def transform_layer(
    sprite: np.ndarray,
    scale: float,
    angle_deg: float,
    hue_deg: float,
    color_rgb: tuple[int, int, int] | None = None,
) -> np.ndarray:
    """Спрайт слоя → заливка цветом (RGB := color_rgb, альфа не трогается) → scale →
    rotate_expand (CCW) → сдвиг тона.

    Без трансформа (`scale == 1.0`, углы и тон 0, `color_rgb is None`) возвращает САМ `sprite`,
    не копию: на этом стоит кэш спрайтов `ObjectFactory` — пишущий в ответ портит кэш."""
    if color_rgb is not None:
        sprite = sprite.copy()
        sprite[:, :, 0], sprite[:, :, 1], sprite[:, :, 2] = color_rgb
    if scale != 1.0:
        h, w = sprite.shape[:2]
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        sprite = cv2.resize(sprite, size, interpolation=cv2.INTER_LINEAR)
    if angle_deg != 0.0:
        sprite = _rotate(sprite, angle_deg)
    if hue_deg != 0.0:
        sprite = _hue_shift(sprite, hue_deg)
    return sprite


def _compose_canvas(placed: list[tuple[np.ndarray, float, float]], angle_deg: float) -> np.ndarray:
    """Слои на симметричную канву (центр объекта в центре), затем поворот объекта."""
    # ponytail: смещение слоя округляется до целого пикселя (так ставит composite);
    # субпиксельное размещение — если понадобится.
    w, h = canvas_size(placed)
    canvas_pm = np.zeros((h, w, 3), dtype=np.uint8)
    canvas_a = np.zeros((h, w), dtype=np.uint8)
    for sprite, ox, oy in placed:
        canvas_pm, canvas_a = _over(canvas_pm, canvas_a, sprite, (w / 2.0 + ox, h / 2.0 + oy))

    # Распремультипликация: rgb = rgb_pm * 255 / alpha (где alpha > 0).
    a = canvas_a.astype(np.float32)
    rgb = np.where(a[:, :, None] > 0, canvas_pm.astype(np.float32) * 255.0 / np.maximum(a, 1.0)[:, :, None], 0.0)
    rgba = np.dstack([np.clip(rgb + 0.5, 0, 255).astype(np.uint8), canvas_a])
    if angle_deg != 0.0:
        rgba = _rotate(rgba, angle_deg)
    return rgba


def compose_layers(
    layers: Sequence[LayerSpec],
    rng: np.random.Generator,
    object_angle_deg: float = 0.0,
    forced_defects: Iterable[str] = (),
    *,
    label: str = "",
) -> ComposedLayers:
    """Разыграть слои объекта и скомпоновать их в один RGBA.

    `label` — имя объекта в текстах ошибок (`LayeredObject '<label>': ...`).

    Pre:
      - `layers` не пуст; спрайты — RGBA uint8 (строковые id грузит `ObjectFactory`)
      - имена слоёв уникальны; `forced_defects` — последовательность имён defect-слоёв из `layers`
        (не строка: строку `"a,b"` разбирает вызывающий, иначе она разобралась бы по символам)
    Post:
      - `rgba` — новый записываемый массив, альфа не пуста
      - `layer_params` — выбранные значения; `active_defects` — в порядке слоёв
      - слой i берёт случайность из `rng.spawn(len(layers))[i]`: порядок слоёв —
        часть контракта seed, розыгрыш одного слоя не сдвигает другие
      - `forced_defects` включает эти defect-слои без розыгрыша; неизвестное имя — ValueError
      - входные слои и спрайты не мутируются; callable-провайдер зовётся ровно раз на слой
    Порядок проверок: `forced_defects` строкой (`TypeError`) → пустой список → спрайты → дубли имён →
    неизвестный дефект → розыгрыш → полностью прозрачный итог.
    """
    # 0. Форма аргумента — до любых проверок содержимого: `str` тоже Iterable[str], и `list("scratch")`
    #    дал бы отдельные символы (а слой с односимвольным именем молча включился бы).
    if isinstance(forced_defects, str):
        raise TypeError(
            f"LayeredObject '{label}': forced_defects — последовательность имён defect-слоёв "
            "(list/tuple), получена строка; строку паспорта разбирает вызывающий"
        )
    if not layers:
        raise ValueError(f"LayeredObject '{label}': пустой список слоёв — нечего рисовать")

    # 1. Все спрайты загружаются и проверяются ДО любого розыгрыша: битый спрайт
    #    невыпавшего defect-слоя падает детерминированно, провайдер зовётся ровно раз.
    sprites = [load_layer_sprite(layer) for layer in layers]

    # 2. Принудительный дефект: имена defect-слоёв (разбор строки паспорта — у вызывающего).
    names = [layer.name for layer in layers]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        why = "layer_params и defect адресуют слой по имени"
        raise ValueError(f"LayeredObject '{label}': имена слоёв повторяются {dupes} — {why}")
    defect_names = {layer.name for layer in layers if layer.mode == "defect"}
    forced = list(forced_defects)
    unknown = [n for n in forced if n not in defect_names]
    if unknown:
        raise ValueError(
            f"LayeredObject '{label}': defect={unknown} — нет таких defect-слоёв (есть: {sorted(defect_names)})"
        )

    # 3. Своя подпоследовательность rng на каждый слой (по индексу): розыгрыш одного
    #    слоя не сдвигает выборку следующих. Порядок слоёв — часть контракта seed.
    subs = rng.spawn(len(layers))
    placed: list[tuple[np.ndarray, float, float]] = []
    params: dict[str, dict[str, Any]] = {}
    active_defects: list[str] = []
    for layer, sprite, sub in zip(layers, sprites, subs, strict=True):
        dx = dy = dang = dhue = 0.0
        mul = 1.0
        if layer.mode == "defect":
            active = layer.name in forced or bool(sub.random() < layer.defect_probability)
            params[layer.name] = {"active": active}
            if layer.color_rgb is not None:
                params[layer.name]["color_rgb"] = list(_hue_shift_color(layer.color_rgb, dhue))
            if not active:
                continue
            active_defects.append(layer.name)
        elif layer.mode == "augmented" and layer.augment is not None:
            sampled = {f: float(sub.uniform(*getattr(layer.augment, f))) for f in AUGMENT_FIELDS}
            params[layer.name] = sampled
            dx, dy = sampled["offset_x_px"], sampled["offset_y_px"]
            dang, mul, dhue = sampled["angle_deg"], sampled["scale"], sampled["hue_shift_deg"]
            if layer.color_rgb is not None:
                params[layer.name]["color_rgb"] = list(_hue_shift_color(layer.color_rgb, dhue))
        elif layer.color_rgb is not None:
            params[layer.name] = {"color_rgb": list(_hue_shift_color(layer.color_rgb, dhue))}
        placed.append(
            (
                transform_layer(sprite, layer.scale * mul, layer.angle_deg + dang, dhue, layer.color_rgb),
                layer.offset_px[0] + dx,
                layer.offset_px[1] + dy,
            )
        )

    rgba = _compose_canvas(placed, object_angle_deg)
    if not np.any(rgba[:, :, 3]):
        raise ValueError(f"LayeredObject '{label}': итоговый RGBA полностью прозрачен")
    return ComposedLayers(rgba=rgba, layer_params=params, active_defects=tuple(active_defects))
