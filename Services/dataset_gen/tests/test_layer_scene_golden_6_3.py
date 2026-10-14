"""Байтовый литерал выхода LayerSceneGenerator (предусловие Task 6.3, стадия 0).

Что закреплено: кадр и метка `LayerSceneGenerator.generate_sample` на синтетических пресетах слоёв.
Четыре группы:

  G1        — независимый numpy-оракул: кадр собран вручную (`np.full` + срез), вырез `size_mode: fixed`.
  G1-radius — тот же оракул, вырез `size_mode: radius` (сторона выреза равна выходу, ресайза нет).
  G2        — богатый кейс (3 класса, подложка + слой `class://`, тайл-фон, шум): sha256 `frame.tobytes()`,
              shape, dtype и ВСЕ поля `label.to_dict()` литералами; кейсы с явным `rng`.
  G3        — внутренний поток `LayerSceneGenerator(preset, seed=11)`: три вызова `generate_sample()` подряд.

Литералы G2/G3 вставлены из ОДНОГО прогона кода на win32 при 87dd240dc (main) и НИКОГДА не считаются во время
assert. Ни одно ожидаемое значение не считается через `ObjectFactory`, `render_scene`, `square_crop`,
`resize_square`, `encode_angle` или сам генератор.

Данные полностью синтетические: каталог и файлы слоёв строятся в tmp_path из numpy-спрайтов (seed фиксирован),
каталог data/ не читается. Float-поля метки сравниваются точным `==`, как в `test_engine_golden_m4.py`.

Красный литерал здесь — НАХОДКА, а не повод переписать литерал под новый код
(правило plans/layer-render/goldens.md). Осознанное изменение поведения — решение
лида/CTO, с точным диффом, а не regen.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from Services.dataset_gen.core.layer_scene import LayerSceneGenerator
from Services.layer_render.preset import ScenePreset

_BG = (20, 40, 60)
_G1_COLORS = {"k0": (200, 40, 40), "k1": (40, 200, 40)}


def _textured(mask: np.ndarray, base: tuple[int, int, int], seed: int, amp: int) -> np.ndarray:
    """RGBA-спрайт: цвет base + numpy-шум ±amp внутри маски (amp=0 — плоский цвет)."""
    rng = np.random.default_rng(seed)
    h, w = mask.shape
    noise = rng.integers(-amp, amp + 1, size=(h, w, 3))
    rgb = np.clip(np.array(base, dtype=np.int64) + noise, 0, 255).astype(np.uint8)
    sprite = np.zeros((h, w, 4), dtype=np.uint8)
    sprite[..., :3] = rgb
    sprite[..., 3] = np.where(mask, 255, 0)
    return sprite


def _save_rgba(path: Path, rgba: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba).save(path)


def _write_preset(root: Path, data: dict) -> Path:
    path = root / "preset.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# G1 / G1-radius: спрайты 60x30 (ширина 60, высота 30), независимый оракул      #
# --------------------------------------------------------------------------- #


def _build_g1(root: Path, crop: dict) -> Path:
    for name, color in _G1_COLORS.items():
        sprite = np.zeros((30, 60, 4), dtype=np.uint8)
        sprite[..., :3] = color
        sprite[..., 3] = 255
        _save_rgba(root / "cat" / name / "0.png", sprite)
    return _write_preset(
        root,
        {
            "catalog_dir": "cat",
            "angle_range_deg": [0, 0],
            "layers": [],
            "train": {
                "label": {"angle_layer": None},
                "symmetry": {"auto_detect": False},
                "background_layers": [{"solid": list(_BG)}],
                "crop": crop,
            },
        },
    )


_G1_CROP_FIXED = {"size_mode": "fixed", "side_px": 96, "output_size": 96}
# радиус по альфа-bbox max(60, 30) / 2 = 30; сторона round(2 * 30 * 1.0) + 2 * 18 = 96 — ресайза нет
_G1_CROP_RADIUS = {"size_mode": "radius", "radius_scale": 1.0, "margin_px": 18, "output_size": 96}


def _check_g1(tmp_path: Path, crop: dict, class_index: int, seed: int) -> None:
    gen = LayerSceneGenerator.from_yaml(_build_g1(tmp_path, crop))
    frame, label = gen.generate_sample(class_index=class_index, rng=np.random.default_rng(seed))

    name = ["k0", "k1"][class_index]
    expected = np.full((96, 96, 3), _BG, dtype=np.uint8)
    expected[33:63, 18:78] = _G1_COLORS[name]  # (96 - 30) / 2 = 33, (96 - 60) / 2 = 18
    assert frame.shape == (96, 96, 3)
    assert frame.dtype == np.uint8
    differ = np.argwhere(np.any(frame != expected, axis=2))
    assert differ.size == 0, f"{len(differ)} px differ, first (y, x) = {differ[0].tolist()}"

    assert label.class_index == class_index
    assert label.class_name == name
    assert label.angle_deg == 0.0
    assert label.angle_sin == 0.0
    assert label.angle_cos == 1.0
    assert label.symmetry == "none"
    assert label.angle_valid is True


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("class_index", [0, 1])
def test_g1_fixed_crop_matches_numpy_oracle(tmp_path, class_index, seed):
    _check_g1(tmp_path, _G1_CROP_FIXED, class_index, seed)


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("class_index", [0, 1])
def test_g1_radius_crop_matches_numpy_oracle(tmp_path, class_index, seed):
    _check_g1(tmp_path, _G1_CROP_RADIUS, class_index, seed)


# --------------------------------------------------------------------------- #
# G2 / G3: богатый кейс                                                         #
# --------------------------------------------------------------------------- #


def _build_g2(root: Path) -> Path:
    mask = np.zeros((64, 64), dtype=bool)  # Г-образная: нет вращательной симметрии
    mask[8:56, 8:24] = True
    mask[40:56, 8:56] = True
    colors = {"k0": (220, 60, 60), "k1": (60, 200, 60), "k2": (60, 60, 220)}
    for i, (name, color) in enumerate(colors.items()):
        _save_rgba(root / "cat" / name / "0.png", _textured(mask, color, 201 + i, 30))

    yy, xx = np.mgrid[:104, :104]
    inside = (xx - 51.5) ** 2 + (yy - 51.5) ** 2 <= 50.0**2  # круг диаметра 100 на канве 104
    under = np.zeros((104, 104, 4), dtype=np.uint8)
    under[inside, :3] = (230, 230, 230)
    under[inside, 3] = 255
    _save_rgba(root / "under.png", under)

    tile = np.zeros((160, 40, 4), dtype=np.uint8)  # ширина 40, высота 160
    tile[..., :3] = np.random.default_rng(5).integers(0, 256, size=(160, 40, 3), dtype=np.uint8)
    tile[..., 3] = 255
    tile[:, 0:6, 3] = 0
    _save_rgba(root / "tile.png", tile)

    return _write_preset(
        root,
        {
            "catalog_dir": "cat",
            "angle_range_deg": [0, 360],
            "layers": [
                {"name": "under", "mode": "static", "sprite_source": "under.png"},
                {
                    "name": "obj",
                    "mode": "augmented",
                    "sprite_source": "class://",
                    "angle_deg": 10,
                    "augment": {"angle_deg": [-5, 5]},
                },
            ],
            "train": {
                "label": {"angle_layer": "obj"},
                "symmetry": {"auto_detect": False, "overrides": {"k1": "180"}},
                "background_layers": [{"solid": [10, 10, 10]}, {"tile": "tile.png"}],
                "lateral_offset_px": [3, 9],
                "crop": {
                    "size_mode": "radius",
                    "radius_scale": 1.0,
                    "margin_px": 6,
                    "output_size": 64,
                    "center_jitter_px": 2.0,
                    "radius_jitter_frac": 0.1,
                },
                "augment": {
                    "noise": {"enabled": True, "prob": 1.0},
                    "brightness_contrast": {"enabled": False},
                    "gaussian_blur": {"enabled": False},
                    "color_temperature": {"enabled": False},
                },
            },
        },
    )


def _snapshot(frame: np.ndarray, label) -> dict:
    return {
        "shape": frame.shape,
        "dtype": str(frame.dtype),
        "sha256": hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest(),
        "label": label.to_dict(),
    }


def _assert_matches(got: dict, want: dict) -> None:
    assert got["shape"] == want["shape"]
    assert got["dtype"] == want["dtype"]
    assert set(got["label"]) == set(want["label"])
    for field, value in want["label"].items():
        assert got["label"][field] == value, field
    assert got["sha256"] == want["sha256"]


# (кейс) -> литерал. Заполнено из одного прогона (win32, 87dd240dc).
GOLDEN_G2: dict[str, dict] = {
    "rand-0": {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "99c3cdb31f67fd7f17d7c745feff557808f9628046df5576184e77f7d330de8e",
        "label": {
            "class_index": 2,
            "class_name": "k2",
            "class_path": "k2",
            "angle_deg": 108.24085491821143,
            "angle_sin": 0.9497490987393906,
            "angle_cos": -0.31301221932013346,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    "rand-1": {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "05ece8f06abeb000ae47b4cfef20f68732b0fb18fe54bd7e53a8e8d2b7894837",
        "label": {
            "class_index": 1,
            "class_name": "k1",
            "class_path": "k1",
            "angle_deg": 349.6177929176974,
            "angle_sin": -0.3545262830793095,
            "angle_cos": 0.9350460494574422,
            "symmetry": "180",
            "angle_valid": True,
        },
    },
    "rand-2": {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "3d6378e1042d080658acf2b6299a92e0c02e8861ac234b557a22412dc07e77d9",
        "label": {
            "class_index": 2,
            "class_name": "k2",
            "class_path": "k2",
            "angle_deg": 118.03136687375101,
            "angle_sin": 0.8826904458997807,
            "angle_cos": -0.4699548666810955,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    "rand-3": {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "63c53be17cab4e29e4a20837c286c17aaed6dcaf1e7c18c759e85e45eb6814a8",
        "label": {
            "class_index": 2,
            "class_name": "k2",
            "class_path": "k2",
            "angle_deg": 95.54061717590075,
            "angle_sin": 0.9953280028727818,
            "angle_cos": -0.09655136817922191,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    "class2-0": {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "b699b03ea2e3e7a2b9fc20ee12adee659ae4d7ea2a09b11257b061e1bc7aba43",
        "label": {
            "class_index": 2,
            "class_name": "k2",
            "class_path": "k2",
            "angle_deg": 311.56168660843906,
            "angle_sin": -0.7482418873015861,
            "angle_cos": 0.663426015534031,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    "class2-1": {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "9efe9ff83925f738fc076fe629cdba49c6eb1592be151fd2c4f30cc0191bbaf4",
        "label": {
            "class_index": 2,
            "class_name": "k2",
            "class_path": "k2",
            "angle_deg": 352.13470381726887,
            "angle_sin": -0.13684457336647252,
            "angle_cos": 0.9905925311348497,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
}

# три вызова generate_sample() подряд у LayerSceneGenerator(preset, seed=11).
GOLDEN_G3: list[dict] = [
    {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "69070378638b91e43ffe7a9c798c61cd7f4730768d30deb5093aadaee95f4d24",
        "label": {
            "class_index": 0,
            "class_name": "k0",
            "class_path": "k0",
            "angle_deg": 190.06902882725356,
            "angle_sin": -0.17483452834939742,
            "angle_cos": -0.9845978304347637,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "2577334e17ace2aca811fb145814010e387df702ae9f635daa1ff049baa436a9",
        "label": {
            "class_index": 1,
            "class_name": "k1",
            "class_path": "k1",
            "angle_deg": 243.9933256904726,
            "angle_sin": 0.7881541674003522,
            "angle_cos": -0.6154778699591544,
            "symmetry": "180",
            "angle_valid": True,
        },
    },
    {
        "shape": (64, 64, 3),
        "dtype": "uint8",
        "sha256": "c6b8e3b6b592f6a6da8f52d066df173b8c33435ffec6f881d45b6716d1085246",
        "label": {
            "class_index": 2,
            "class_name": "k2",
            "class_path": "k2",
            "angle_deg": 127.88836196577222,
            "angle_sin": 0.7892088434036789,
            "angle_cos": -0.6141249070778902,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
]

_G2_CASES = [("rand", s) for s in range(4)] + [("class2", s) for s in range(2)]


def _g2_call(gen: LayerSceneGenerator, kind: str, s: int):
    if kind == "rand":
        return gen.generate_sample(rng=np.random.default_rng(s))
    return gen.generate_sample(class_index=2, rng=np.random.default_rng(100 + s))


@pytest.mark.parametrize(("kind", "s"), _G2_CASES, ids=lambda v: str(v))
def test_g2_matches_literal(tmp_path, kind, s):
    gen = LayerSceneGenerator.from_yaml(_build_g2(tmp_path))
    frame, label = _g2_call(gen, kind, s)
    _assert_matches(_snapshot(frame, label), GOLDEN_G2[f"{kind}-{s}"])


def test_g2_random_class_cases_cover_two_classes():
    drawn = {GOLDEN_G2[f"rand-{s}"]["label"]["class_index"] for s in range(4)}
    assert len(drawn) >= 2, f"розыгрыш класса не различает классы: {sorted(drawn)}"


def test_g3_internal_stream_matches_literal(tmp_path):
    gen = LayerSceneGenerator(ScenePreset.from_yaml(_build_g2(tmp_path)), seed=11)
    got = [_snapshot(*gen.generate_sample()) for _ in range(3)]
    assert len(GOLDEN_G3) == 3
    for index, (g, want) in enumerate(zip(got, GOLDEN_G3)):
        try:
            _assert_matches(g, want)
        except AssertionError as exc:
            raise AssertionError(f"вызов {index}: {exc}") from exc
