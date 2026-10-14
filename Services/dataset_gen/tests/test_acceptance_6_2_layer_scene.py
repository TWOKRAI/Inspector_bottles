# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 6.2: `Services/dataset_gen/core/layer_scene.py` (`LayerSceneGenerator`, `TrainSection`).

Источник контракта: `plans/layer-render/phase-6-task-6.2.md` — REDS 3-10, ACCEPTANCE 1-7, DESIGN C-F как контракт.
Worktree на коммите брифа, до кода: модуля `layer_scene` и функции `core.symmetry.resolve_symmetries` в дереве нет.
Не читались: реализация 6.2, другие ветки, `data/`.

Как устроен файл.
  * Новые символы (`LayerSceneGenerator`, `TrainSection`, `resolve_symmetries`, `ObjectFactory.render(class_index=)`)
    импортируются/вызываются ВНУТРИ тестов: каждый тест красный сам по себе, сбор не падает.
  * Фикстуры синтетические: numpy-спрайты -> PNG во `tmp_path`, пресеты — YAML во `tmp_path`; `data/` не читается.
  * Эталон «там» (REDS 5, ACCEPTANCE 3) строится из публичных функций `layer_render`: `ObjectFactory`, `render_scene`,
    `SceneBackground`, `PlacedObject`, `square_crop`, `resize_square`, `side_from_radius`. Эталон порядка розыгрышей
    (`oracle_order`) проигрывает DESIGN F явными вызовами numpy — независимая копия контракта, не проверяемый код.
  * Ожидаемые значения — литералы или такие оракулы; нигде не берутся из `LayerSceneGenerator`.

Допущения брифа, которые тест читает буквально, помечены `# BRIEF-AMBIGUITY:`.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from Services.dataset_gen.core.augment import augment_config_to_effects
from Services.dataset_gen.core.config import AugmentConfig, GeneratorConfig, SymmetryConfig
from Services.dataset_gen.core.engine import DatasetEngine
from Services.dataset_gen.interfaces import SampleGenerator
from Services.layer_render import (
    LayerSpec,
    ObjectFactory,
    PlacedObject,
    ScenePreset,
    SceneBackground,
    ScrollingTile,
    SolidFill,
    load_catalog,
    render_scene,
    resize_square,
    rotate_expand,
    side_from_radius,
    square_crop,
)
from Services.layer_render.io import imwrite_unicode

_ROOT = Path(__file__).resolve().parents[3]
_LAYER_SCENE_PY = _ROOT / "Services" / "dataset_gen" / "core" / "layer_scene.py"
_BG = (20, 40, 60)

# --------------------------------------------------------------------------- #
# Фикстуры: спрайты, каталог, пресет-YAML                                      #
# --------------------------------------------------------------------------- #


def _disc(side: int, seed: int) -> np.ndarray:
    """RGBA-диск: внутри случайные цвета (разрушают симметрию) и альфа 255, снаружи всё 0."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:side, :side]
    inside = (yy - (side - 1) / 2) ** 2 + (xx - (side - 1) / 2) ** 2 <= (side / 2 - 1) ** 2
    rgb = rng.integers(30, 256, size=(side, side, 3), dtype=np.uint8)
    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[inside, :3] = rgb[inside]
    rgba[inside, 3] = 255
    return rgba


def _rect(height: int, width: int, index: int) -> np.ndarray:
    """Непрозрачный прямоугольник одного цвета (свой у каждого класса), `(height, width, 4)`."""
    color = (60 + 80 * index, 200 - 60 * index, 90)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[:, :, :3] = color
    rgba[:, :, 3] = 255
    return rgba


def _sprite(kind: str, index: int) -> np.ndarray:
    if kind == "disc41":
        return _disc(41, 1000 + index)
    if kind == "rect60x30":  # 60 в ширину, 30 в высоту
        return _rect(30, 60, index)
    if kind == "bar150x64":  # длинный брусок: однозначный угол, ≥ 64 px по меньшей стороне
        return _rect(64, 150, index)
    raise AssertionError(kind)


def _write_rgba(path: Path, rgba: np.ndarray) -> None:
    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _write_rgb(path: Path, rgb: np.ndarray) -> None:
    imwrite_unicode(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def _tile_pattern() -> np.ndarray:
    """RGB-тайл 24x50 с арифметическим узором (меняется по X и по Y): сдвиг тайла виден в пикселях."""
    ys, xs = np.mgrid[:24, :50]
    return np.dstack([(xs * 5) % 256, (ys * 10) % 256, ((xs + ys) * 3) % 256]).astype(np.uint8)


def _build(
    root: Path,
    *,
    names: tuple[str, ...] = ("a", "b", "c"),
    sprite: str = "disc41",
    layers: list[dict] | None = None,
    angle_range: tuple[float, float] | None = None,
    defect_probability: float | None = None,
    train: dict | None = None,
    meta: dict[str, dict] | None = None,
    filename: str = "preset.yaml",
) -> Path:
    """Каталог `root/cat/<имя>/0.png` и пресет-YAML рядом; пути относительные (резолвятся от каталога YAML)."""
    cat = root / "cat"
    for index, name in enumerate(names):
        (cat / name).mkdir(parents=True)
        _write_rgba(cat / name / "0.png", _sprite(sprite, index))
    for name, content in (meta or {}).items():
        (cat / name / "meta.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    data: dict = {"catalog_dir": "cat"}
    if angle_range is not None:
        data["angle_range_deg"] = list(angle_range)
    if defect_probability is not None:
        data["defect_probability"] = defect_probability
    if layers is not None:
        data["layers"] = layers
    if train is not None:
        data["train"] = train
    path = root / filename
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _from_yaml(path: Path, seed: int | None = None):
    from Services.dataset_gen.core.layer_scene import LayerSceneGenerator

    return LayerSceneGenerator.from_yaml(path, seed=seed)


def _clean_factory(path: Path, defect_probability: float = 0.0) -> ObjectFactory:
    preset = ScenePreset.from_yaml(path)
    return ObjectFactory(preset.model_copy(update={"defect_probability": defect_probability}))


def _bbox_radius(rgba: np.ndarray) -> float:
    """`r = max(bbox_w, bbox_h) / 2` по альфе > 0 (DESIGN F.4)."""
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    # BRIEF-AMBIGUITY: «bbox_w» не определён; читаю как число пикселей (max - min + 1), а не max - min.
    width = int(xs.max() - xs.min()) + 1
    height = int(ys.max() - ys.min()) + 1
    return max(width, height) / 2.0


def _check_sample(frame: np.ndarray, label, *, output_size: int, num_classes: int) -> None:
    assert frame.shape == (output_size, output_size, 3)
    assert frame.dtype == np.uint8
    assert 0 <= label.class_index < num_classes
    assert 0.0 <= label.angle_deg < 360.0
    if label.angle_valid:
        assert abs(label.angle_sin**2 + label.angle_cos**2 - 1.0) < 1e-9


def _product_a(root: Path) -> Path:
    """Продукт (а): круг-подложка (статический слой-файл) + слой `class://`, 3 класса, `size_mode: radius`."""
    root.mkdir(parents=True, exist_ok=True)
    _write_rgba(root / "plate.png", _disc(56, 77))
    return _build(
        root,
        layers=[
            {"name": "plate", "mode": "static", "sprite_source": "plate.png"},
            {"name": "mark", "mode": "static", "sprite_source": "class://"},
        ],
        train={
            "background_layers": [{"solid": list(_BG)}],
            "lateral_offset_px": [0.0, 6.0],
            "crop": {
                "size_mode": "radius",
                "radius_scale": 1.0,
                "margin_px": 6,
                "output_size": 48,
                "center_jitter_px": 2.0,
                "radius_jitter_frac": 0.1,
            },
        },
    )


def _product_b(root: Path) -> Path:
    """Продукт (б): 2 класса прямоугольных RGBA 60x30, без `class://`, `angle_layer: null`, `fixed`, `side_px: 96`."""
    return _build(
        root,
        names=("x", "y"),
        sprite="rect60x30",
        angle_range=(123.5, 123.5),
        train={"label": {"angle_layer": None}, "crop": {"size_mode": "fixed", "side_px": 96, "output_size": 80}},
    )


# --------------------------------------------------------------------------- #
# Эталон «там» (ACCEPTANCE 3) и реплей порядка розыгрышей (DESIGN F)           #
# --------------------------------------------------------------------------- #


def _replay(path: Path, train: dict, ci: int, seed: int, *, effects=(), tile: np.ndarray | None = None):
    """DESIGN F.1-F.9 явными вызовами numpy; возвращает `(кадр сэмпла, знак)`. Фон: заливка `_BG` (+ тайл)."""
    crop_cfg = train["crop"]
    lat_lo, lat_hi = train["lateral_offset_px"]
    jitter = crop_cfg["center_jitter_px"]
    frac = crop_cfg["radius_jitter_frac"]
    fixed = crop_cfg["size_mode"] == "fixed"

    def side_for(k: float) -> int:
        if fixed:
            return crop_cfg["side_px"]
        return side_from_radius(radius * (1.0 + k), crop_cfg["radius_scale"], crop_cfg["margin_px"])

    rng = np.random.default_rng(seed)
    obj = _clean_factory(path).render(rng, class_index=ci, label="train")  # F.2
    lat = rng.uniform(lat_lo, lat_hi)  # F.3: всегда два розыгрыша
    sign = 1.0 if rng.random() < 0.5 else -1.0
    radius = _bbox_radius(obj.rgba)  # F.4
    side_max = side_for(frac)
    half = math.ceil(side_max / 2) + math.ceil(lat_hi) + math.ceil(jitter) + 2  # F.5
    half += half % 2
    w = 2 * half
    layers: list = [SolidFill(color_rgb=_BG)]
    scroll_px = 0
    if tile is not None:  # F.6: розыгрыш есть только при наличии ScrollingTile
        layers.append(ScrollingTile(image=tile))
        scroll_px = int(rng.integers(0, tile.shape[1]))
    background = SceneBackground(layers, (w, w), center_y=w / 2, scroll_px=scroll_px)
    frame = render_scene(background, [PlacedObject(obj.rgba, (w / 2, w / 2 + sign * lat))], effects, rng)  # F.7
    dx = rng.uniform(-jitter, jitter)  # F.8: всегда три розыгрыша
    dy = rng.uniform(-jitter, jitter)
    k = rng.uniform(-frac, frac)
    side = side_for(k)
    cx = int(round(w / 2 + dx))
    cy = int(round(w / 2 + sign * lat + dy))
    crop = square_crop(frame, cx, cy, side, "drop")  # F.9
    assert crop is not None, f"эталон: вырез side={side} в ({cx}, {cy}) вышел из окна {w}x{w}"
    return resize_square(crop, crop_cfg["output_size"]), sign


def _default_ref(path: Path, ci: int, seed: int, defect_probability: float):
    """Эталон секции `train` по умолчанию: фон чёрный, `side_px 200`, `output_size 128`, лат. 0, джиттеры 0."""
    obj = _clean_factory(path, defect_probability).render(np.random.default_rng(seed), class_index=ci)
    w = 208  # кратно 4: W/2 чётно (банковское округление composite)
    background = SceneBackground((SolidFill(color_rgb=(0, 0, 0)),), (w, w), center_y=w / 2)
    frame = render_scene(background, [PlacedObject(obj.rgba, (w / 2, w / 2))], (), None)
    crop = square_crop(frame, w // 2, w // 2, 200, "drop")
    assert crop is not None
    return resize_square(crop, 128), obj


# --------------------------------------------------------------------------- #
# REDS 3: протокол и форма кадра                                               #
# --------------------------------------------------------------------------- #


def test_protocol_and_shapes(tmp_path):
    """REDS 3 (без симметрии — она в `test_symmetry_overrides_map_and_label`): протокол, каталог, форма кадра."""
    path = _build(tmp_path, train={"crop": {"side_px": 80, "output_size": 64}})
    gen = _from_yaml(path, seed=1)

    assert isinstance(gen, SampleGenerator)
    assert gen.num_classes == 3
    assert gen.class_names == ["a", "b", "c"]

    frame, label = gen.generate_sample()
    assert frame.shape == (64, 64, 3)
    assert frame.dtype == np.uint8
    assert label.class_name == gen.class_names[label.class_index]
    assert label.class_path == label.class_name  # плоский каталог: qualified_name == имя


def test_symmetry_overrides_map_and_label(tmp_path):
    """REDS 3: `train.symmetry` -> `symmetry_map`; метка класса 0 несёт `180` и кодирование `(sin 2θ, cos 2θ)`."""
    train = {
        "symmetry": {"overrides": {"a": "180"}, "auto_detect": False},
        "crop": {"side_px": 80, "output_size": 64},
    }
    gen = _from_yaml(_build(tmp_path, train=train), seed=1)
    assert gen.symmetry_map == {"a": "180", "b": "none", "c": "none"}

    _, label0 = gen.generate_sample(class_index=0, rng=np.random.default_rng(2))
    assert label0.symmetry == "180"
    assert label0.angle_valid is True
    assert label0.angle_sin == pytest.approx(math.sin(math.radians(2.0 * label0.angle_deg)), abs=1e-9)
    assert label0.angle_cos == pytest.approx(math.cos(math.radians(2.0 * label0.angle_deg)), abs=1e-9)

    _, label1 = gen.generate_sample(class_index=1, rng=np.random.default_rng(2))
    assert label1.symmetry == "none"
    assert label1.angle_sin == pytest.approx(math.sin(math.radians(label1.angle_deg)), abs=1e-9)


# --------------------------------------------------------------------------- #
# REDS 4 / ACCEPTANCE 2: два продукта, ноль кода                               #
# --------------------------------------------------------------------------- #


def test_two_products_zero_code(tmp_path):
    """REDS 4: два продукта грузятся одним `from_yaml`; контракт сэмпла держится у обоих; у (б) метка = угол объекта."""
    gen_a = _from_yaml(_product_a(tmp_path / "product_a"), seed=7)
    gen_b = _from_yaml(_product_b(tmp_path / "product_b"), seed=7)
    assert type(gen_a) is type(gen_b)
    assert gen_a.class_names == ["a", "b", "c"]
    assert gen_b.class_names == ["x", "y"]

    for _ in range(10):
        frame, label = gen_a.generate_sample()
        _check_sample(frame, label, output_size=48, num_classes=3)
    for _ in range(10):
        frame, label = gen_b.generate_sample()
        _check_sample(frame, label, output_size=80, num_classes=2)
        assert label.angle_deg == 123.5  # angle_layer: null -> угол объекта (литерал из пресета)


# --------------------------------------------------------------------------- #
# REDS 5 / ACCEPTANCE 3: «идентично там и там»                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("size_mode", ["fixed", "radius"])
@pytest.mark.parametrize("window", ["small", "1440x1080"])
@pytest.mark.parametrize("obj_kind", ["obj_even", "obj_odd"])
def test_identical_to_scene_crop(tmp_path, obj_kind, window, size_mode):
    """REDS 5: кадр сэмпла == вырез из `render_scene` с тем же объектом на окне любого размера, побайтно.

    `obj_odd`: угол 37 даёт `obj.rgba` 59x59 (нечётная сторона — ловушка банковского округления `composite`);
    `obj_even`: угол 0 даёт 42x42. Окно эталона разное, центры (W/2, W/2) и (720, 540) чётные — результат одинаков.
    """
    # BRIEF-AMBIGUITY: ось size_mode добавлена сверх брифа (бриф: obj × окно); обе ветки `side` из ACCEPTANCE 3.
    odd = obj_kind == "obj_odd"
    angle = 37.0 if odd else 0.0
    crop_cfg = {
        "size_mode": size_mode,
        "side_px": 50,
        "radius_scale": 1.0,
        "margin_px": 5,
        "output_size": 32,
        "center_jitter_px": 0.0,
        "radius_jitter_frac": 0.0,
    }
    train = {"background_layers": [{"solid": list(_BG)}], "lateral_offset_px": [0.0, 0.0], "crop": crop_cfg}
    path = _build(tmp_path, angle_range=(angle, angle), train=train)
    gen = _from_yaml(path)
    factory = _clean_factory(path)

    for ci, seed in ((0, 11), (1, 12), (2, 13)):
        obj = factory.render(np.random.default_rng(seed), class_index=ci)
        assert obj.rgba.shape[0] % 2 == (1 if odd else 0), "предусловие: чётность стороны obj.rgba"
        side = 50 if size_mode == "fixed" else side_from_radius(_bbox_radius(obj.rgba), 1.0, 5)
        fill = (SolidFill(color_rgb=_BG),)
        if window == "small":
            w = 4 * math.ceil((max(side, obj.rgba.shape[0]) + 8) / 4)  # кратно 4, хватает для выреза
            background = SceneBackground(fill, (w, w), center_y=w / 2)
            frame = render_scene(background, [PlacedObject(obj.rgba, (w / 2, w / 2))], (), None)
            crop = square_crop(frame, w // 2, w // 2, side, "drop")
        else:
            background = SceneBackground(fill, (1440, 1080), center_y=540.0)
            frame = render_scene(background, [PlacedObject(obj.rgba, (720.0, 540.0))], (), None)
            crop = square_crop(frame, 720, 540, side, "drop")
        assert crop is not None
        expected = resize_square(crop, 32)

        got, _ = gen.generate_sample(class_index=ci, rng=np.random.default_rng(seed))
        assert got.shape == (32, 32, 3)
        assert got.tobytes() == expected.tobytes(), f"class_index={ci} seed={seed}"


@pytest.mark.parametrize("angle", [0.0, 37.0])
def test_identical_to_scene_crop_label_matches_reference_object(tmp_path, angle):
    """Метка сэмпла (без слоя метки) несёт класс и угол объекта эталона."""
    path = _build(tmp_path, angle_range=(angle, angle), train={"crop": {"side_px": 50, "output_size": 32}})
    gen = _from_yaml(path)
    factory = _clean_factory(path)
    for ci, seed in ((0, 21), (1, 22), (2, 23)):
        obj = factory.render(np.random.default_rng(seed), class_index=ci)
        _, label = gen.generate_sample(class_index=ci, rng=np.random.default_rng(seed))
        assert label.class_index == ci
        assert label.class_name == obj.class_name
        assert label.angle_deg == obj.angle_deg % 360.0


_OQ_AUGMENT = {
    "noise": {"enabled": True, "prob": 1.0},
    "brightness_contrast": {"enabled": False},
    "gaussian_blur": {"enabled": False},
    "color_temperature": {"enabled": False},
}


@pytest.mark.parametrize("variant", ["fixed", "radius_jitter"])
def test_identical_to_scene_crop_oracle_order(tmp_path, variant):
    """REDS 5 `oracle_order`: порядок розыгрышей — контракт seed (DESIGN F). Эталон проигрывает F явными вызовами numpy.

    Лат. смещение 7.3, джиттер центра 3, объект 59x59, один эффект `noise` с `prob 1.0` на кадре `W x W`. Перестановка
    розыгрышей (знак, лат., эффекты, джиттер, радиус) или лишний/недостающий розыгрыш сдвигает поток rng и ломает байты.
    `radius_jitter` — вариант сверх брифа: `size_mode: radius` и `radius_jitter_frac: 0.1` (розыгрыш `k` меняет `side`).
    """
    # BRIEF-AMBIGUITY: бриф даёт один oracle_order (fixed); вариант radius_jitter и 12 сидов (а не 0..7) — мои.
    crop_cfg = {
        "size_mode": "fixed" if variant == "fixed" else "radius",
        "side_px": 48,
        "radius_scale": 1.0,
        "margin_px": 4,
        "output_size": 40,
        "center_jitter_px": 3.0,
        "radius_jitter_frac": 0.0 if variant == "fixed" else 0.1,
    }
    train = {
        "background_layers": [{"solid": list(_BG)}],
        "lateral_offset_px": [7.3, 7.3],
        "crop": crop_cfg,
        "augment": _OQ_AUGMENT,
    }
    path = _build(tmp_path, angle_range=(37.0, 37.0), train=train)
    effects = augment_config_to_effects(AugmentConfig.model_validate(_OQ_AUGMENT))
    assert [e.name for e in effects] == ["noise"], "предусловие: включён ровно один эффект"
    gen = _from_yaml(path)

    signs = set()
    for seed in range(12):
        ci = seed % 3
        expected, sign = _replay(path, train, ci, seed, effects=effects)
        signs.add(sign)
        got, _ = gen.generate_sample(class_index=ci, rng=np.random.default_rng(seed))
        assert got.shape == expected.shape
        assert got.tobytes() == expected.tobytes(), f"seed={seed} class_index={ci} sign={sign}"
    # Оба знака обязаны встретиться (иначе тест не ловит «знак без розыгрыша»). На GREEN один знак на всех
    # сидах — сменить диапазон сидов, утверждение не ослаблять.
    assert signs == {1.0, -1.0}, f"встретились знаки {signs}"


def test_scroll_phase_is_drawn_after_sign_and_before_effects(tmp_path):
    """DESIGN F.6: при `ScrollingTile` после знака тратится `rng.integers(0, ширина тайла)`; порядок — контракт seed."""
    _write_rgb(tmp_path / "belt.png", _tile_pattern())
    crop_cfg = {
        "size_mode": "fixed",
        "side_px": 48,
        "radius_scale": 1.0,
        "margin_px": 4,
        "output_size": 40,
        "center_jitter_px": 3.0,
        "radius_jitter_frac": 0.0,
    }
    train = {
        "background_layers": [{"solid": list(_BG)}, {"tile": "belt.png"}],
        "lateral_offset_px": [2.0, 9.0],
        "crop": crop_cfg,
    }
    path = _build(tmp_path, angle_range=(37.0, 37.0), train=train)
    gen = _from_yaml(path)
    tile = _tile_pattern()
    for seed in range(8):
        ci = seed % 3
        expected, _ = _replay(path, train, ci, seed, tile=tile)
        got, _ = gen.generate_sample(class_index=ci, rng=np.random.default_rng(seed))
        assert got.tobytes() == expected.tobytes(), f"seed={seed} class_index={ci}"


# --------------------------------------------------------------------------- #
# REDS 6 / ACCEPTANCE 4: угол метки                                            #
# --------------------------------------------------------------------------- #


def _iou_aligned(mask_a: np.ndarray, mask_b: np.ndarray, slack: int = 1) -> float:
    """IoU двух масок, положенных центрами на общий холст; наилучший из сдвигов ±`slack` px по обеим осям.

    BRIEF-AMBIGUITY: бриф: «по центру общего холста», без поиска сдвига. Чётность сторон `obj.rgba` (чётная канва)
    и `rotate_expand` (произвольная) даёт сдвиг в полпикселя, поэтому допускаю ±1 px.
    """
    size = max(mask_a.shape + mask_b.shape) + 2 * slack + 2
    canvases = []
    for mask in (mask_a, mask_b):
        canvas = np.zeros((size, size), dtype=bool)
        top, left = (size - mask.shape[0]) // 2, (size - mask.shape[1]) // 2
        canvas[top : top + mask.shape[0], left : left + mask.shape[1]] = mask
        canvases.append(canvas)
    a, b = canvases
    best = 0.0
    for dy in range(-slack, slack + 1):
        for dx in range(-slack, slack + 1):
            shifted = np.roll(b, (dy, dx), axis=(0, 1))
            best = max(best, float(np.logical_and(a, shifted).sum() / np.logical_or(a, shifted).sum()))
    return best


@pytest.mark.parametrize(
    ("mode", "augment", "expected"),
    [("static", None, 47.0), ("augmented", {"angle_deg": [5.0, 5.0]}, 52.0)],
    ids=["static", "augmented"],
)
def test_angle_label_47_and_iou(tmp_path, mode, augment, expected):
    """REDS 6: угол объекта 37 + слой `class://` 10 (+ 5 из `augment`) -> метка 47.0 / 52.0, картинка так же."""
    layer = {"name": "mark", "mode": mode, "sprite_source": "class://", "angle_deg": 10.0}
    if augment is not None:
        layer["augment"] = augment
    path = _build(
        tmp_path,
        names=("a",),
        sprite="bar150x64",
        angle_range=(37.0, 37.0),
        layers=[layer],
        train={"label": {"angle_layer": "mark"}},
    )
    gen = _from_yaml(path)
    _, label = gen.generate_sample(class_index=0, rng=np.random.default_rng(0))
    assert label.angle_deg == pytest.approx(expected, abs=1e-9)

    # Картинка объекта (фабрика слоёв, класс один — путь без `class_index`) повёрнута на тот же угол, что метка.
    obj = _clean_factory(path).render(np.random.default_rng(0))
    obj_mask = obj.rgba[..., 3] > 127
    sprite = _sprite("bar150x64", 0)
    same = _iou_aligned(obj_mask, rotate_expand(sprite, expected)[..., 3] > 127)
    assert same >= 0.98, f"IoU с поворотом на {expected}: {same:.4f}"
    # Контроль чувствительности: поворот на «чужой» угол (на 5 градусов в сторону) обязан давать заметно меньше.
    wrong = 52.0 if expected == 47.0 else 47.0
    other = _iou_aligned(obj_mask, rotate_expand(sprite, wrong)[..., 3] > 127)
    assert other < 0.98, f"IoU с поворотом на {wrong} тоже {other:.4f}: тест не различает углы"


@pytest.mark.parametrize(("angle_layer", "expected"), [("auto", 47.0), ("mark", 47.0), (None, 37.0)])
def test_angle_layer_auto_named_and_null(tmp_path, angle_layer, expected):
    """`auto` = слой `class://`, если он есть; имя слоя — он же; `null` — угол объекта."""
    path = _build(
        tmp_path,
        names=("a",),
        sprite="rect60x30",
        angle_range=(37.0, 37.0),
        layers=[{"name": "mark", "mode": "static", "sprite_source": "class://", "angle_deg": 10.0}],
        train={"label": {"angle_layer": angle_layer}},
    )
    _, label = _from_yaml(path).generate_sample(class_index=0, rng=np.random.default_rng(0))
    assert label.angle_deg == pytest.approx(expected, abs=1e-9)


def test_angle_layer_auto_without_class_layer_is_object_angle(tmp_path):
    """`auto` без слоя `class://` -> угол объекта (`obj.angle_deg % 360`)."""
    path = _build(
        tmp_path, names=("a",), sprite="rect60x30", angle_range=(123.5, 123.5), train={"label": {"angle_layer": "auto"}}
    )
    _, label = _from_yaml(path).generate_sample(class_index=0, rng=np.random.default_rng(0))
    assert label.angle_deg == 123.5


def test_angle_layer_default_is_auto(tmp_path):
    """Ключ `label` не задан = `angle_layer: auto`: со слоем `class://` метка включает его угол."""
    path = _build(
        tmp_path,
        names=("a",),
        sprite="rect60x30",
        angle_range=(37.0, 37.0),
        layers=[{"name": "mark", "mode": "static", "sprite_source": "class://", "angle_deg": 10.0}],
    )
    _, label = _from_yaml(path).generate_sample(class_index=0, rng=np.random.default_rng(0))
    assert label.angle_deg == pytest.approx(47.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# REDS 7 / 8, ACCEPTANCE 5: seed и покрытие классов                             #
# --------------------------------------------------------------------------- #


def _rich_preset(root: Path) -> Path:
    """Пресет с лат. смещением, джиттерами, тайлом в фоне, фотометрией и браком: задействует все ветки розыгрышей."""
    _write_rgb(root / "belt.png", _tile_pattern())
    train = {
        "background_layers": [{"solid": list(_BG)}, {"tile": "belt.png"}],
        "lateral_offset_px": [3.0, 10.0],
        "crop": {
            "size_mode": "radius",
            "radius_scale": 1.0,
            "margin_px": 6,
            "output_size": 40,
            "center_jitter_px": 2.0,
            "radius_jitter_frac": 0.1,
        },
        "augment": {"noise": {"enabled": True, "prob": 1.0}},
        "defect_probability": 0.3,
    }
    return _build(root, train=train)


def test_same_seed_same_bytes(tmp_path):
    """REDS 7: два свежих генератора с `rng=default_rng(3)` -> те же байты кадра и тот же `to_dict()` метки."""
    path = _rich_preset(tmp_path)
    frame1, label1 = _from_yaml(path).generate_sample(rng=np.random.default_rng(3))
    frame2, label2 = _from_yaml(path).generate_sample(rng=np.random.default_rng(3))
    assert frame1.tobytes() == frame2.tobytes()
    assert label1.to_dict() == label2.to_dict()


def test_constructor_seed_makes_reproducible_stream(tmp_path):
    """`seed=` конструктора и `from_yaml(seed=)`: тот же seed -> та же последовательность сэмплов; другой -> другая."""
    from Services.dataset_gen.core.layer_scene import LayerSceneGenerator

    path = _rich_preset(tmp_path)

    def stream(gen):
        return [(f.tobytes(), lab.to_dict()) for f, lab in (gen.generate_sample() for _ in range(3))]

    same_a = stream(LayerSceneGenerator(ScenePreset.from_yaml(path), seed=11))
    same_b = stream(_from_yaml(path, seed=11))
    other = stream(_from_yaml(path, seed=12))
    assert same_a == same_b
    assert same_a != other


def test_explicit_rng_does_not_touch_internal_stream(tmp_path):
    """DESIGN F.1: переданный `rng` используется вместо внутреннего и внутренний поток не двигает."""
    path = _rich_preset(tmp_path)
    used, fresh = _from_yaml(path, seed=21), _from_yaml(path, seed=21)
    used.generate_sample(rng=np.random.default_rng(99))
    frame_used, label_used = used.generate_sample()
    frame_fresh, label_fresh = fresh.generate_sample()
    assert frame_used.tobytes() == frame_fresh.tobytes()
    assert label_used.to_dict() == label_fresh.to_dict()


def test_all_four_classes_in_100(tmp_path):
    """REDS 8: 100 сэмплов с одним `rng=default_rng(0)` на каталоге из 4 классов -> встретились все 4."""
    path = _build(tmp_path, names=("a", "b", "c", "d"), train={"crop": {"side_px": 40, "output_size": 16}})
    gen = _from_yaml(path)
    rng = np.random.default_rng(0)
    labels = [gen.generate_sample(rng=rng)[1] for _ in range(100)]
    assert {label.class_index for label in labels} == {0, 1, 2, 3}
    assert all(label.class_name == gen.class_names[label.class_index] for label in labels)


# --------------------------------------------------------------------------- #
# REDS 9: resolve_symmetries на уровне модуля                                   #
# --------------------------------------------------------------------------- #


def test_resolve_symmetries_module_level(tmp_path):
    """REDS 9: `resolve_symmetries(catalog, sym_cfg)` -> `{индекс: тип}`; по именам == `DatasetEngine.symmetry_map`."""
    from Services.dataset_gen.core.symmetry import resolve_symmetries

    cat = _build(tmp_path).parent / "cat"
    catalog = load_catalog(cat)
    sym = SymmetryConfig(overrides={"a": "180"}, auto_detect=False)
    assert resolve_symmetries(catalog, sym) == {0: "180", 1: "none", 2: "none"}

    engine = DatasetEngine(
        GeneratorConfig.from_dict(
            {"catalog": {"classes_dir": str(cat)}, "symmetry": {"overrides": {"a": "180"}, "auto_detect": False}}
        )
    )
    by_name = {catalog.class_names[i]: kind for i, kind in resolve_symmetries(catalog, sym).items()}
    assert by_name == engine.symmetry_map


def test_resolve_symmetries_priority_override_meta_detector(tmp_path):
    """Приоритет: override по имени > `meta.symmetry` класса > авто-детектор > `none` при выключенном детекторе."""
    from Services.dataset_gen.core.symmetry import resolve_symmetries

    path = _build(tmp_path, meta={"b": {"symmetry": "full"}, "c": {"symmetry": "180"}})
    catalog = load_catalog(path.parent / "cat")
    off = SymmetryConfig(overrides={"c": "none"}, auto_detect=False)
    # a: ни override, ни meta, детектор выключен -> none; b: meta -> full; c: override бьёт meta -> none
    assert resolve_symmetries(catalog, off) == {0: "none", 1: "full", 2: "none"}


def test_resolve_symmetries_auto_detect_known_shapes(tmp_path):
    """Авто-детектор: круг -> full, брусок -> 180, Г-образная фигура -> none (те же формы, что в `test_symmetry`)."""
    from Services.dataset_gen.core.symmetry import resolve_symmetries

    cat = tmp_path / "cat"
    shapes = {"bar": _bar96(), "disk": _full96(), "lshape": _lshape96()}  # индексы по сортировке: bar, disk, lshape
    for name, rgba in shapes.items():
        (cat / name).mkdir(parents=True)
        _write_rgba(cat / name / "base.png", rgba)
    catalog = load_catalog(cat)
    assert catalog.class_names == ["bar", "disk", "lshape"]
    assert resolve_symmetries(catalog, SymmetryConfig()) == {0: "180", 1: "full", 2: "none"}


def _blank96() -> np.ndarray:
    return np.zeros((96, 96, 4), dtype=np.uint8)


def _full96() -> np.ndarray:
    sprite = _blank96()
    yy, xx = np.ogrid[:96, :96]
    sprite[(xx - 47.5) ** 2 + (yy - 47.5) ** 2 <= (48.0 - 4) ** 2] = (255, 255, 255, 255)
    return sprite


def _bar96() -> np.ndarray:
    sprite = _blank96()
    sprite[48 - 12 : 48 + 12, 6:90] = (40, 200, 60, 255)
    return sprite


def _lshape96() -> np.ndarray:
    sprite = _blank96()
    cv2.rectangle(sprite, (10, 10), (30, 86), (220, 60, 60, 255), -1)
    cv2.rectangle(sprite, (10, 62), (86, 86), (220, 60, 60, 255), -1)
    return sprite


# --------------------------------------------------------------------------- #
# REDS 10: ошибки, брак, слова рамки                                            #
# --------------------------------------------------------------------------- #


def test_errors_defect_and_frame_words(tmp_path):
    """REDS 10 дословно: четыре независимые проверки в одном тесте (по порядку брифа)."""
    from Services.dataset_gen.core.layer_scene import LayerSceneGenerator

    # 1. пресет без catalog_dir -> ValueError с `catalog_dir`
    _write_rgba(tmp_path / "plate.png", _disc(30, 5))
    layer = LayerSpec(name="plate", mode="static", sprite_source=str(tmp_path / "plate.png"))
    with pytest.raises(ValueError, match="catalog_dir"):
        LayerSceneGenerator(ScenePreset(layers=[layer]))

    # 2. label.angle_layer: "nope" -> ValueError с именем поля и списком слоёв class:// пресета
    layers = [
        {"name": "plate", "mode": "static", "sprite_source": "plate.png"},
        {"name": "mark", "mode": "static", "sprite_source": "class://"},
    ]
    bad = _build(tmp_path / "nope", layers=layers, train={"label": {"angle_layer": "nope"}})
    _write_rgba(bad.parent / "plate.png", _disc(30, 5))
    with pytest.raises(ValueError) as info:
        _from_yaml(bad)
    assert "label.angle_layer" in str(info.value)
    assert "mark" in str(info.value)  # список слоёв class:// пресета

    # 3. defect_probability: 1.0 пресета без `train` -> кадр == эталон по схеме ACCEPTANCE 3 с дефолтами `train`
    #    и фабрикой с defect_probability 0 (перекрытие train.defect_probability = 0.0)
    path = _build(tmp_path / "defect", defect_probability=1.0)
    clean, obj_clean = _default_ref(path, 1, 4, 0.0)
    defective, obj_defective = _default_ref(path, 1, 4, 1.0)
    assert obj_clean.defect is None and obj_defective.defect == "damaged"  # предусловие эталона
    assert not np.array_equal(clean, defective)  # брак на кадре виден: проверка не пустая
    got, _ = _from_yaml(path).generate_sample(class_index=1, rng=np.random.default_rng(4))
    assert got.shape == (128, 128, 3)
    assert got.tobytes() == clean.tobytes()

    # 4. слова продукта в коде генератора — основная проверка рамки (рамка: «объект», «слой», «класс»)
    assert _LAYER_SCENE_PY.is_file(), f"нет {_LAYER_SCENE_PY}"
    text = _LAYER_SCENE_PY.read_text(encoding="utf-8")
    assert re.search(r"letter|букв|disk|диск", text, re.I) is None


def test_angle_layer_error_names_class_layers_only_and_not_the_input(tmp_path):
    """`angle_layer` — только слой `class://`: обычный слой и выдуманное имя дают отказ без эха ввода."""
    layers = [
        {"name": "plate", "mode": "static", "sprite_source": "plate.png"},
        {"name": "mark", "mode": "static", "sprite_source": "class://"},
    ]
    for index, wrong in enumerate(("nope", "plate")):
        root = tmp_path / f"case{index}"
        path = _build(root, layers=layers, train={"label": {"angle_layer": wrong}})
        _write_rgba(root / "plate.png", _disc(30, 5))
        with pytest.raises(ValueError) as info:
            _from_yaml(path)
        text = str(info.value)
        assert "label.angle_layer" in text
        assert "mark" in text
        if wrong == "nope":
            assert "nope" not in text  # TRAPS: текст без входного значения
        else:
            assert "plate" not in text  # обычный слой в списке допустимых не значится


def test_train_defect_probability_overrides_preset(tmp_path):
    """`train.defect_probability` перекрывает пресет в обе стороны: пресет 0.0 + train 1.0 -> брак есть и наоборот."""
    forced = _build(tmp_path / "forced", train={"defect_probability": 1.0})  # пресет: 0.0 (дефолт)
    got, _ = _from_yaml(forced).generate_sample(class_index=2, rng=np.random.default_rng(6))
    expected, obj = _default_ref(forced, 2, 6, 1.0)
    assert obj.defect == "damaged"
    assert got.tobytes() == expected.tobytes()
    clean, _ = _default_ref(forced, 2, 6, 0.0)
    assert not np.array_equal(got, clean)


# --------------------------------------------------------------------------- #
# Схема TrainSection (DESIGN D) и экспорт                                       #
# --------------------------------------------------------------------------- #


def test_train_section_defaults_and_forbid_extras():
    """Дефолты схемы — литералы DESIGN D; неизвестные ключи (корень, `crop`, `label`) отвергаются, модель заморожена."""
    from Services.dataset_gen.core.layer_scene import TrainSection

    train = TrainSection()
    assert train.crop.size_mode == "fixed"
    assert train.crop.side_px == 200
    assert train.crop.radius_scale == 1.0
    assert train.crop.margin_px == 10
    assert train.crop.output_size == 128
    assert train.crop.center_jitter_px == 0.0
    assert train.crop.radius_jitter_frac == 0.0
    assert train.label.angle_layer == "auto"
    assert train.background_layers == [{"solid": [0, 0, 0]}]
    assert tuple(train.lateral_offset_px) == (0.0, 0.0)
    assert train.augment is None
    assert train.defect_probability == 0.0

    for bad in ({"bogus": 1}, {"crop": {"bogus": 1}}, {"label": {"bogus": 1}}):
        with pytest.raises(ValidationError):
            TrainSection.model_validate(bad)
    with pytest.raises(ValidationError):
        train.defect_probability = 0.5  # frozen


@pytest.mark.parametrize(
    "bad",
    [
        {"crop": {"side_px": 1}},
        {"crop": {"output_size": 0}},
        {"crop": {"radius_scale": 0}},
        {"crop": {"margin_px": -1}},
        {"crop": {"center_jitter_px": -0.5}},
        {"crop": {"size_mode": "circle"}},
        {"defect_probability": 1.01},
        {"defect_probability": -0.01},
    ],
    ids=[
        "side_px-1",
        "output_size-0",
        "radius_scale-0",
        "margin_px-minus1",
        "center_jitter-minus",
        "size_mode-circle",
        "defect-above-1",
        "defect-below-0",
    ],
)
def test_train_section_rejects_out_of_range_values(bad):
    """Границы полей DESIGN D: `side_px >= 2`, `output_size >= 1`, `radius_scale > 0`, `margin_px >= 0`, 0 <= p <= 1."""
    from Services.dataset_gen.core.layer_scene import TrainSection

    with pytest.raises(ValidationError):
        TrainSection.model_validate(bad)


def test_package_exports_generator_and_train_section():
    """`Services.dataset_gen` экспортирует `LayerSceneGenerator` и `TrainSection` (FILES п. 6)."""
    import Services.dataset_gen as package

    assert "LayerSceneGenerator" in package.__all__
    assert "TrainSection" in package.__all__
    from Services.dataset_gen.core.layer_scene import LayerSceneGenerator, TrainSection

    assert package.LayerSceneGenerator is LayerSceneGenerator
    assert package.TrainSection is TrainSection


def test_dataset_gen_import_does_not_pull_line_sim():
    """ACCEPTANCE 7: чистый процесс: импорт `Services.dataset_gen` и генератора не тянет `Services.line_sim*`."""
    code = (
        "import sys; import Services.dataset_gen; "
        "from Services.dataset_gen.core.layer_scene import LayerSceneGenerator, TrainSection; "
        "bad = sorted(m for m in sys.modules if m.startswith('Services.line_sim')); "
        "print('BAD=' + ','.join(bad)); sys.exit(1 if bad else 0)"
    )
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
