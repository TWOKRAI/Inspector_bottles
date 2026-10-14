"""Генератор обучающих сэмплов поверх слоёв сима (Task 6.2): `LayerSceneGenerator` и схема секции `train`.

Purpose:
    Сэмпл «кадр + метка» для обучения классификатора класса и угла — из того же пресета слоёв, что рисует сим:
    объект строит `layer_render.ObjectFactory`, кадр — `layer_render.render_scene` на окне `W×W`, вырез —
    `layer_render.crop`. Продуктовые данные — только в пресете (секция `train`); код знает объект, слой и класс.

Public API:
    `LayerSceneGenerator(preset, *, seed=None)`, `LayerSceneGenerator.from_yaml(path, *, seed=None)`,
    свойства `num_classes`, `class_names`, `symmetry_map`, метод `generate_sample(class_index=None, rng=None)`
    (Protocol `SampleGenerator`); схема `TrainSection` (`TrainCrop`, `TrainLabel`).

Stability: lite

Порядок розыгрышей `generate_sample` — контракт seed (бриф 6.2, DESIGN F):
    класс (`integers`, только без `class_index`) -> `factory.render` -> `uniform` (лат. смещение) -> `random` (знак)
    -> `integers` (фаза тайла, только при `ScrollingTile` в фоне) -> эффекты кадра (`render_scene`) -> `uniform` ×2
    (джиттер центра) -> `uniform` (джиттер радиуса). Розыгрыши лат. смещения, знака и трёх джиттеров есть всегда,
    даже при нулевых диапазонах.

Геометрия `augment` (`rotation`, `shift`, `scale`, `contact_shadow`) игнорируется: геометрию дают слои пресета.
Фотометрия считается на окне `W×W`, а не на кадре сима — блик и виньетка зависят от размера (известное расхождение).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from Services.dataset_gen.core.augment import augment_config_to_effects
from Services.dataset_gen.core.config import AugmentConfig, SymmetryConfig, SymmetryType
from Services.dataset_gen.core.labels import SampleLabel
from Services.dataset_gen.core.symmetry import encode_angle, resolve_symmetries
from Services.layer_render import (
    ObjectFactory,
    PlacedObject,
    ScenePreset,
    SceneBackground,
    ScrollingTile,
    render_scene,
    resize_square,
    side_from_radius,
    square_crop,
)
from Services.layer_render.background import background_layers_from_config
from Services.layer_render.io import imread_unicode
from Services.layer_render.layers import LayerSpec
from Services.layer_render.preset import CLASS_SPRITE_SOURCE

__all__ = ["LayerSceneGenerator", "TrainCrop", "TrainLabel", "TrainSection"]

_AUTO = "auto"
_MAX_SIDE_PX = 4000  # потолок стороны выреза — тот же, что `TrainCrop.side_px` (le=4000)


def _wrap360(angle: float) -> float:
    """Угол в `[0, 360)`: `x % 360.0` у малого отрицательного `x` даёт ровно `360.0` (округление float)."""
    wrapped = angle % 360.0
    return 0.0 if wrapped >= 360.0 else wrapped


# --------------------------------------------------------------------------- #
# Схема секции train (DESIGN D)                                                #
# --------------------------------------------------------------------------- #


class TrainCrop(BaseModel):
    """Вырез вокруг объекта. Дефолты — литералы `CenterCropRegisters` (Plugins отсюда не импортируются).

    `output_size` >= 1: у регистра 0 — «без ресайза», здесь нет — Protocol ждёт один размер сэмпла.
    `center_jitter_px` — `U(−j, j)` по каждой оси; `radius_jitter_frac` — радиус `× (1 + U(−f, f))`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    size_mode: Literal["radius", "fixed"] = "fixed"
    side_px: int = Field(200, ge=2, le=4000)
    radius_scale: float = Field(1.0, gt=0)
    margin_px: int = Field(10, ge=0)
    output_size: int = Field(128, ge=1)
    center_jitter_px: float = Field(0.0, ge=0, le=500)
    radius_jitter_frac: float = Field(0.0, ge=0, lt=1)


class TrainLabel(BaseModel):
    """Источник угла метки: `"auto"` — слой `class://`, если он есть, иначе угол объекта; `None` — угол объекта;
    иначе — имя слоя `class://` пресета."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    angle_layer: str | None = _AUTO


class TrainSection(BaseModel):
    """Секция `train` пресета слоёв (в `ScenePreset.train` лежит как непрозрачный dict).

    `background_layers` — схема 1.1 (`solid`/`tile`); `lateral_offset_px` — `[lo, hi]`, смещение объекта по Y
    от центра окна, знак разыгрывается; `augment` — только фотометрия (`None` — без неё; геометрия
    `rotation/shift/scale/contact_shadow` игнорируется); `defect_probability` перекрывает пресет.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    label: TrainLabel = TrainLabel()
    symmetry: SymmetryConfig = SymmetryConfig()
    background_layers: list[dict] = [{"solid": [0, 0, 0]}]
    lateral_offset_px: tuple[float, float] = (0.0, 0.0)
    crop: TrainCrop = TrainCrop()
    augment: AugmentConfig | None = None
    defect_probability: float = Field(0.0, ge=0, le=1)

    @field_validator("lateral_offset_px")
    @classmethod
    def _lateral(cls, v: tuple[float, float]) -> tuple[float, float]:
        lo, hi = v
        if not (0.0 <= lo <= hi <= 2000.0):
            raise ValueError("train.lateral_offset_px: нужно 0 <= lo <= hi <= 2000")
        return v

    @model_validator(mode="before")
    @classmethod
    def _no_unknown_keys(cls, data: Any) -> Any:
        # У SymmetryConfig/AugmentConfig нет extra="forbid": опечатка молча дала бы дефолт.
        if not isinstance(data, dict):
            return data
        blocks: list[tuple[str, Any, Any]] = [
            ("symmetry", data.get("symmetry"), SymmetryConfig),
            ("augment", data.get("augment"), AugmentConfig),
        ]
        aug = data.get("augment")
        if isinstance(aug, dict):
            blocks += [
                (f"augment.{k}", v, AugmentConfig.model_fields[k].annotation)
                for k, v in aug.items()
                if k in AugmentConfig.model_fields
            ]
        for path, block, model in blocks:
            if isinstance(block, dict) and set(block) - set(model.model_fields):
                raise ValueError(f"train.{path}: неизвестный ключ (допустимы: {sorted(model.model_fields)})")
        return data


# --------------------------------------------------------------------------- #
# Генератор (DESIGN E–F)                                                       #
# --------------------------------------------------------------------------- #


def _alpha_radius(rgba: np.ndarray) -> float:
    """`max(bbox_w, bbox_h) / 2` по альфе > 0; ширина/высота — число пикселей (`max − min + 1`)."""
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    if xs.size == 0:
        raise RuntimeError("LayerSceneGenerator: у объекта нет непрозрачных пикселей — радиус не определён")
    width = int(xs.max() - xs.min()) + 1
    height = int(ys.max() - ys.min()) + 1
    return max(width, height) / 2.0


class LayerSceneGenerator:
    """Источник сэмплов «кадр + метка» из пресета слоёв (Protocol `SampleGenerator`).

    Pre: `preset.catalog_dir` задан (иначе `ValueError` с `catalog_dir`); `preset.train` — `None` или dict по схеме
    `TrainSection` (иначе `pydantic.ValidationError`); `label.angle_layer` — `"auto"`, `None` или имя слоя
    `class://` пресета (иначе `ValueError` с `label.angle_layer` и списком слоёв `class://`); каждый `tile:` фона
    читается (иначе исключение при создании — обучение без фона было бы тихой порчей).
    Post: `num_classes`/`class_names` — каталог пресета; `symmetry_map` резолвлена один раз; внутренний поток
    `rng` — `default_rng(seed)`.

    Состояние между сэмплами — только внутренний `rng`; фабрика объектов держит лишь кэши слоёв и каталога.
    """

    def __init__(self, preset: ScenePreset, *, seed: int | None = None) -> None:
        train = TrainSection.model_validate(preset.train or {})
        if preset.catalog_dir is None:
            raise ValueError("LayerSceneGenerator: пресет без catalog_dir — генератору обучения нужен каталог классов")
        self._train = train
        self._label_layer = self._resolve_label_layer(preset, train.label.angle_layer)
        self._factory = ObjectFactory(preset.model_copy(update={"defect_probability": train.defect_probability}))

        def load_image(path: str) -> np.ndarray:
            # Нечитаемый файл — исключение imread_unicode наружу, не None: None выкинул бы слой молча.
            image = imread_unicode(preset.resolve_path(path), cv2.IMREAD_UNCHANGED)
            if image.ndim != 3:  # как сим (scene_source): серый тайл не принимается
                raise ValueError(
                    f"train.background_layers: tile должен быть цветным (H, W, 3|4), получено ndim={image.ndim}"
                )
            code = cv2.COLOR_BGRA2RGBA if image.ndim == 3 and image.shape[2] == 4 else cv2.COLOR_BGR2RGB
            return cv2.cvtColor(image, code)

        self._background = background_layers_from_config(train.background_layers, load_image)
        tile_widths = [layer.image.shape[1] for layer in self._background if isinstance(layer, ScrollingTile)]
        self._tile_period = max(tile_widths) if tile_widths else 0
        self._effects = augment_config_to_effects(train.augment) if train.augment is not None else []

        catalog = self._factory.catalog
        assert catalog is not None  # catalog_dir проверен выше
        self._catalog = catalog
        unknown = set(train.symmetry.overrides) - set(catalog.class_names)
        if unknown:
            raise ValueError(
                f"train.symmetry.overrides: нет такого класса в каталоге (классы каталога: {catalog.class_names})"
            )
        self._symmetry: dict[int, SymmetryType] = resolve_symmetries(catalog, train.symmetry)
        self._rng = np.random.default_rng(seed)

    @classmethod
    def from_yaml(cls, path: str | Path, *, seed: int | None = None) -> LayerSceneGenerator:
        """Генератор из YAML-пресета слоёв (секция `train` — в том же файле)."""
        return cls(ScenePreset.from_yaml(path), seed=seed)

    @staticmethod
    def _resolve_label_layer(preset: ScenePreset, angle_layer: str | None) -> LayerSpec | None:
        """Слой, чей угол входит в метку, или `None` (метка = угол объекта)."""
        class_layers = [layer for layer in preset.layers if layer.sprite_source == CLASS_SPRITE_SOURCE]
        if angle_layer is None:
            return None
        if angle_layer == _AUTO:
            return class_layers[0] if class_layers else None
        for layer in class_layers:
            if layer.name == angle_layer:
                return layer
        names = [layer.name for layer in class_layers]
        raise ValueError(f"label.angle_layer: нет такого слоя class:// (слои class:// пресета: {names})")

    # -- свойства (как у DatasetEngine) ---------------------------------------

    @property
    def num_classes(self) -> int:
        return self._catalog.num_classes

    @property
    def class_names(self) -> list[str]:
        return self._catalog.class_names

    @property
    def symmetry_map(self) -> dict[str, SymmetryType]:
        """Имя класса → тип симметрии (override секции → meta.yaml → детектор)."""
        names = self._catalog.class_names
        return {names[i]: s for i, s in self._symmetry.items()}

    # -- генерация ------------------------------------------------------------

    def generate_sample(
        self,
        class_index: int | None = None,
        rng: np.random.Generator | None = None,
    ) -> tuple[np.ndarray, SampleLabel]:
        """Один сэмпл: объект слоёв на окне `W×W` -> вырез вокруг объекта -> ресайз; метка класса и угла.

        Pre: `class_index` — `None` или `int` в `[0, num_classes)` (иначе `ValueError` фабрики до розыгрышей);
        `rng` — `None` (внутренний поток) или `np.random.Generator` (внутренний поток не двигается).
        Post: кадр `(output_size, output_size, 3)` uint8 RGB; `0 <= label.angle_deg < 360`; при `angle_valid`
        `sin² + cos² ≈ 1`. Порядок розыгрышей — контракт seed (докстринг модуля).
        """
        rng = rng if rng is not None else self._rng
        train = self._train
        crop_cfg = train.crop
        lat_lo, lat_hi = train.lateral_offset_px
        jitter = crop_cfg.center_jitter_px
        frac = crop_cfg.radius_jitter_frac

        # F.1–F.2: класс и объект
        if class_index is None:
            class_index = int(rng.integers(self.num_classes))
        obj = self._factory.render(rng, class_index=class_index, label="train")
        ci = int(class_index)

        # F.3: лат. смещение и знак — всегда два розыгрыша
        lat = float(rng.uniform(lat_lo, lat_hi))
        sign = 1.0 if rng.random() < 0.5 else -1.0

        # F.4–F.5: наибольшая сторона выреза и окно W (кратно 4, W/2 чётно — банковское округление composite)
        radius = _alpha_radius(obj.rgba)

        def side_for(k: float) -> int:
            if crop_cfg.size_mode == "fixed":
                return crop_cfg.side_px
            return side_from_radius(radius * (1.0 + k), crop_cfg.radius_scale, crop_cfg.margin_px)

        side_max = side_for(frac)
        if side_max > _MAX_SIDE_PX:  # до выделения окна W×W: radius_scale/margin_px без потолка
            raise ValueError(
                f"train.crop: сторона выреза больше {_MAX_SIDE_PX} px — уменьшите radius_scale или margin_px"
            )
        half = math.ceil(side_max / 2) + math.ceil(lat_hi) + math.ceil(jitter) + 2
        half += half % 2
        w = 2 * half

        # F.6: фаза тайла — розыгрыш только при ScrollingTile в фоне
        scroll_px = int(rng.integers(0, self._tile_period)) if self._tile_period > 0 else 0

        # F.7: кадр окна; центр объекта — float без своего округления
        background = SceneBackground(self._background, (w, w), center_y=w / 2, scroll_px=scroll_px)
        placed = [PlacedObject(obj.rgba, (w / 2, w / 2 + sign * lat))]
        frame = render_scene(background, placed, self._effects, rng)

        # F.8: джиттер центра и радиуса — всегда три розыгрыша
        dx = float(rng.uniform(-jitter, jitter))
        dy = float(rng.uniform(-jitter, jitter))
        k = float(rng.uniform(-frac, frac))
        side = side_for(k)
        cx = int(round(w / 2 + dx))
        cy = int(round(w / 2 + sign * lat + dy))

        # F.9: вырез и ресайз
        crop = square_crop(frame, cx, cy, side, "drop")
        if crop is None:
            raise RuntimeError(
                f"LayerSceneGenerator: вырез side={side} в ({cx}, {cy}) вышел из окна {w}x{w} — нарушен инвариант W"
            )
        out = resize_square(crop, crop_cfg.output_size)

        # F.10: угол метки
        angle = self._label_angle(obj.angle_deg, obj.layer_params)
        symmetry = self._symmetry[ci]
        sin_v, cos_v, valid = encode_angle(angle, symmetry)
        entry = self._catalog.entry(ci)
        label = SampleLabel(
            class_index=ci,
            class_name=entry.name,
            class_path=entry.qualified_name,
            angle_deg=angle,
            angle_sin=sin_v,
            angle_cos=cos_v,
            symmetry=symmetry,
            angle_valid=valid,
        )
        return out, label

    def _label_angle(self, object_angle: float, layer_params: dict[str, dict[str, Any]]) -> float:
        """Угол метки: объект + слой метки (номинал + выбранный augment слоя), по модулю 360."""
        layer = self._label_layer
        if layer is None:
            return _wrap360(object_angle)
        drawn = layer_params.get(layer.name, {}).get("angle_deg", 0.0)
        return _wrap360(object_angle + layer.angle_deg + drawn)
