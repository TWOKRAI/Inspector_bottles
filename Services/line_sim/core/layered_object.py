"""LayeredObject — объект ленты из слоёв: выборка и рендер один раз, при создании.

Сцена рисует каждый активный объект на каждом кадре; выборка внутри рендера дала
бы дрожание этикетки от кадра к кадру. Поэтому вся случайность (аугментация,
розыгрыш дефекта) потребляется в `__init__`, там же объект компонуется в RGBA и
кэшируется; `render()` случайности не потребляет и возвращает тот же массив.

Конвенция холста объекта: центр объекта = центр возвращаемого массива
(канва симметрична относительно центра и расширяется под слой, выехавший за
базу; по альфе не обрезается — иначе потерялся бы центр объекта).
"""

from __future__ import annotations

import math
from dataclasses import replace

import cv2
import numpy as np

from Services.dataset_gen.core.compose import composite, rotate_expand
from Services.line_sim.interfaces import AUGMENT_FIELDS, LayerSpec, ObjectPassport


def _load_sprite(layer: LayerSpec) -> np.ndarray:
    """Достать RGBA-спрайт слоя; callable-провайдер зовётся ровно один раз."""
    source = layer.sprite_source
    if isinstance(source, str):
        raise TypeError(
            f"слой '{layer.name}': sprite_source='{source}' — строка-идентификатор; "
            "загрузка спрайта по id — Task 3.2, сюда нужен RGBA-массив или callable"
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


class LayeredObject:
    """Объект = паспорт + слои; RGBA компонуется один раз при создании.

    Pre:
      - `layers` не пуст; спрайты — RGBA uint8 (строковые id — Task 3.2)
    Post:
      - `render()` возвращает один и тот же read-only RGBA-массив, альфа не пуста
      - `passport.layer_params` содержит выбранные значения; `passport.defect` —
        имена активных defect-слоёв через запятую или None
      - входной `passport.defect` (имена через запятую) принудительно включает эти
        defect-слои без розыгрыша; неизвестное имя — ValueError
      - слой i берёт случайность из `rng.spawn(len(layers))[i]`: порядок слоёв —
        часть контракта seed, розыгрыш одного слоя не сдвигает другие
      - входной `passport` не мутируется (у объекта своя копия)
    """

    def __init__(self, passport: ObjectPassport, layers: list[LayerSpec], rng: np.random.Generator) -> None:
        if not layers:
            raise ValueError(f"LayeredObject '{passport.object_id}': пустой список слоёв — нечего рисовать")

        # 1. Все спрайты загружаются и проверяются ДО любого розыгрыша: битый спрайт
        #    невыпавшего defect-слоя падает детерминированно, провайдер зовётся ровно раз.
        sprites = [_load_sprite(layer) for layer in layers]

        # 2. Принудительный дефект из входного паспорта: имена defect-слоёв через запятую.
        defect_names = {layer.name for layer in layers if layer.mode == "defect"}
        forced = [n.strip() for n in (passport.defect or "").split(",") if n.strip()]
        unknown = [n for n in forced if n not in defect_names]
        if unknown:
            raise ValueError(
                f"LayeredObject '{passport.object_id}': defect={unknown} — нет таких defect-слоёв "
                f"(есть: {sorted(defect_names)})"
            )

        # 3. Своя подпоследовательность rng на каждый слой (по индексу): розыгрыш одного
        #    слоя не сдвигает выборку следующих. Порядок слоёв — часть контракта seed.
        subs = rng.spawn(len(layers))
        placed: list[tuple[np.ndarray, float, float]] = []
        params: dict[str, dict] = {}
        active_defects: list[str] = []
        for layer, sprite, sub in zip(layers, sprites, subs, strict=True):
            dx = dy = dang = dhue = 0.0
            mul = 1.0
            if layer.mode == "defect":
                active = layer.name in forced or bool(sub.random() < layer.defect_probability)
                params[layer.name] = {"active": active}
                if not active:
                    continue
                active_defects.append(layer.name)
            elif layer.mode == "augmented" and layer.augment is not None:
                sampled = {f: float(sub.uniform(*getattr(layer.augment, f))) for f in AUGMENT_FIELDS}
                params[layer.name] = sampled
                dx, dy = sampled["offset_x_px"], sampled["offset_y_px"]
                dang, mul, dhue = sampled["angle_deg"], sampled["scale"], sampled["hue_shift_deg"]
            placed.append(
                (
                    self._transform(sprite, layer.scale * mul, layer.angle_deg + dang, dhue),
                    layer.offset_px[0] + dx,
                    layer.offset_px[1] + dy,
                )
            )

        self.passport = replace(passport, layer_params=params, defect=",".join(active_defects) or None)
        self._rgba = self._compose(placed, passport.angle_deg)
        if not np.any(self._rgba[:, :, 3]):
            raise ValueError(f"LayeredObject '{passport.object_id}': итоговый RGBA полностью прозрачен")
        self._rgba.flags.writeable = False  # кэш не портится через возвращённую ссылку

    @staticmethod
    def _transform(sprite: np.ndarray, scale: float, angle_deg: float, hue_deg: float) -> np.ndarray:
        """Спрайт слоя → scale → rotate_expand (CCW) → сдвиг тона."""
        if scale != 1.0:
            h, w = sprite.shape[:2]
            size = (max(1, round(w * scale)), max(1, round(h * scale)))
            sprite = cv2.resize(sprite, size, interpolation=cv2.INTER_LINEAR)
        if angle_deg != 0.0:
            sprite = _rotate(sprite, angle_deg)
        if hue_deg != 0.0:
            sprite = _hue_shift(sprite, hue_deg)
        return sprite

    @staticmethod
    def _compose(placed: list[tuple[np.ndarray, float, float]], angle_deg: float) -> np.ndarray:
        """Слои на симметричную канву (центр объекта в центре), затем поворот объекта."""
        # ponytail: смещение слоя округляется до целого пикселя (так ставит composite);
        # субпиксельное размещение — если понадобится.
        half_w = max(abs(ox) + s.shape[1] / 2.0 for s, ox, _ in placed)
        half_h = max(abs(oy) + s.shape[0] / 2.0 for s, _, oy in placed)
        w, h = 2 * math.ceil(half_w), 2 * math.ceil(half_h)
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

    def render(self) -> np.ndarray:
        """Закэшированный RGBA объекта (read-only; копию делать вызывающему)."""
        return self._rgba
