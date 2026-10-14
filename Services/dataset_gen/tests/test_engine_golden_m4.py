"""Byte-литеральный golden DatasetEngine.generate_sample (m4, предусловие Task 6.2).

Что закреплено: для каждого кейса (конфиг, seed, class_index) — sha256 байт кадра,
shape, dtype и поля SampleLabel (class_index/class_name/angle_deg/angle_sin/angle_cos/
symmetry/angle_valid). Литералы вставлены из ОДНОГО прогона кода на win32 при
e65281652 (main) и НИКОГДА не считаются во время assert.

Конфигурация полностью синтетическая и детерминированная: каталог строится в tmp_path
из numpy-спрайтов (seed фиксирован), каталога data/ нет. Кадр генерируется с явным
`rng=np.random.default_rng(seed)` — состояние движка (config.seed) не участвует.

  A — фотометрия ВЫКЛ (геометрия вкл: поворот, сдвиг, масштаб), фоны-файлы
      (шумовые PNG из numpy), size 96x120, supersample 1.0.
  B — все эффекты ВКЛ с prob=1.0 (blur, motion, noise, gamma, vignette, channel_shift,
      shadow, glare, occlusion, contact_shadow, jpeg), процедурные фоны,
      size 80x112, supersample 1.5 (финальный INTER_AREA).

Красный литерал здесь — НАХОДКА, а не повод переписать литерал под новый код
(правило plans/layer-render/goldens.md). Осознанное изменение поведения — решение
лида/CTO, с точным диффом, а не regen.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
from PIL import Image

from Services.dataset_gen.core.config import GeneratorConfig
from Services.dataset_gen.core.engine import DatasetEngine


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


def _sprites() -> dict[str, np.ndarray]:
    size = 96
    yy, xx = np.mgrid[:size, :size]
    c = (size - 1) / 2.0
    disk = (xx - c) ** 2 + (yy - c) ** 2 <= (size / 2.0 - 4) ** 2
    bar = np.zeros((size, size), dtype=bool)
    bar[size // 2 - 12 : size // 2 + 12, 6 : size - 6] = True
    lshape = np.zeros((size, size), dtype=bool)  # асимметричная: нет вращательной симметрии
    lshape[10 : size - 10, 10:30] = True
    lshape[size - 34 : size - 10, 10 : size - 10] = True
    return {
        # bar/disk плоские — детектор симметрии обязан увидеть 180/full; lshape с текстурой
        "bar": _textured(bar, (40, 200, 60), 101, 0),
        "disk": _textured(disk, (240, 240, 240), 102, 0),
        "lshape": _textured(lshape, (220, 60, 60), 103, 40),
    }


def _build_catalog(root, with_backgrounds: bool) -> None:
    for name, sprite in _sprites().items():
        d = root / "classes" / name
        d.mkdir(parents=True)
        Image.fromarray(sprite).save(d / "base.png")
    if with_backgrounds:
        bg_dir = root / "backgrounds"
        bg_dir.mkdir()
        rng = np.random.default_rng(7)
        for i in range(2):
            bg = rng.integers(0, 256, size=(200, 260, 3), dtype=np.uint8)
            Image.fromarray(bg).save(bg_dir / f"bg{i}.png")


_PHOTOMETRY_OFF = {
    "brightness_contrast": {"enabled": False},
    "gaussian_blur": {"enabled": False},
    "noise": {"enabled": False},
    "color_temperature": {"enabled": False},
}

_PHOTOMETRY_ON = {
    "brightness_contrast": {"enabled": True, "prob": 1.0},
    "gaussian_blur": {"enabled": True, "prob": 1.0},
    "motion_blur": {"enabled": True, "prob": 1.0},
    "noise": {"enabled": True, "prob": 1.0},
    "color_temperature": {"enabled": True, "prob": 1.0},
    "gamma": {"enabled": True, "prob": 1.0},
    "vignette": {"enabled": True, "prob": 1.0},
    "channel_shift": {"enabled": True, "prob": 1.0},
    "shadow": {"enabled": True, "prob": 1.0},
    "glare": {"enabled": True, "prob": 1.0},
    "occlusion": {"enabled": True, "prob": 1.0},
    "contact_shadow": {"enabled": True, "prob": 1.0},
    "jpeg": {"enabled": True, "prob": 1.0},
}


def _config(cfg_id: str, root) -> GeneratorConfig:
    if cfg_id == "A":
        _build_catalog(root, with_backgrounds=True)
        data = {
            "catalog": {"classes_dir": str(root / "classes"), "backgrounds_dir": str(root / "backgrounds")},
            "output": {"size": [96, 120], "supersample": 1.0},
            "augment": _PHOTOMETRY_OFF,
            "seed": 123,
        }
    else:
        _build_catalog(root, with_backgrounds=False)  # процедурные фоны
        data = {
            "catalog": {"classes_dir": str(root / "classes")},
            "output": {"size": [80, 112], "supersample": 1.5},
            "augment": _PHOTOMETRY_ON,
            "seed": 123,
        }
    return GeneratorConfig.from_dict(data)


def _snapshot(cfg_id: str, root, seed: int, class_index: int | None) -> dict:
    """Один прогон generate_sample → словарь для сравнения с литералом."""
    engine = DatasetEngine(_config(cfg_id, root))
    frame, label = engine.generate_sample(class_index, rng=np.random.default_rng(seed))
    return {
        "shape": frame.shape,
        "dtype": str(frame.dtype),
        "sha256": hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest(),
        "label": label.to_dict(),
    }


# (cfg_id, seed, class_index) -> литерал. Заполнено из одного прогона (win32, e65281652).
GOLDEN: dict[tuple[str, int, int | None], dict] = {
    ("A", 0, None): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "634896d2a2b544ee223e4a1ccf917a019c748ef6f14dc0e56f7240d70340797c",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 97.12321695499331,
            "angle_sin": 0.9922817715783613,
            "angle_cos": -0.12400357169577353,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("A", 1, None): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "88edbed2774e87428c4d2bcc02becf2dbf824fe5abef0497da26a1cbf1222594",
        "label": {
            "class_index": 1,
            "class_name": "disk",
            "angle_deg": 342.1669306773367,
            "angle_sin": 0.0,
            "angle_cos": 0.0,
            "symmetry": "full",
            "angle_valid": False,
        },
    },
    ("A", 2, None): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "211b543272fedb069b844bc4e607c261727646f24a25607d44a146db6defad97",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 107.45681162908438,
            "angle_sin": 0.9539433455821565,
            "angle_cos": -0.29998682207644095,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("A", 3, None): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "fb9a744418fb9382d21e781515ad309af84a918a18fdc9332b8ac5d833b85896",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 85.25178237459589,
            "angle_sin": 0.9965680780385521,
            "angle_cos": 0.08277720600833575,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("A", 4, None): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "6868c3a1f7fd7c88396cc58e59caafea2ee4f68d0fefa726d8e21c6fe589e71a",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 184.07791901317017,
            "angle_sin": -0.07111303939667908,
            "angle_cos": -0.9974682629676828,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("B", 0, None): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "474c3dcd39ac3e11ee090aa249331a3dade028ab11a93092d371d4fb383af295",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 97.12321695499331,
            "angle_sin": 0.9922817715783613,
            "angle_cos": -0.12400357169577353,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("B", 1, None): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "712fd04492f02f71e49d806a93690bef1f5fc01e4ede1edbb01aee76ca719e79",
        "label": {
            "class_index": 1,
            "class_name": "disk",
            "angle_deg": 342.1669306773367,
            "angle_sin": 0.0,
            "angle_cos": 0.0,
            "symmetry": "full",
            "angle_valid": False,
        },
    },
    ("B", 2, None): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "3fea2c268306ed6f70fb2b91aeb692ceb03046c2d0f73e68dfc914a115552b17",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 107.45681162908438,
            "angle_sin": 0.9539433455821565,
            "angle_cos": -0.29998682207644095,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("B", 3, None): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "018b4d2d3ae71d83230038117785065103a2fb833df2e2c12ddf92b3d4dded0a",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 85.25178237459589,
            "angle_sin": 0.9965680780385521,
            "angle_cos": 0.08277720600833575,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("B", 4, None): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "3b358f9acca3fb3ce838ae64595f282a11423aa9cbce0ff11b6bfb85b911a9c2",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 184.07791901317017,
            "angle_sin": -0.07111303939667908,
            "angle_cos": -0.9974682629676828,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("A", 0, 0): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "83de250bb934b1270735d2826c0c6a3b913ee9e8ca6a6f939ecbebeb209a5382",
        "label": {
            "class_index": 0,
            "class_name": "bar",
            "angle_deg": 229.30620743572354,
            "angle_sin": 0.9887239564605275,
            "angle_cos": -0.14974958404296465,
            "symmetry": "180",
            "angle_valid": True,
        },
    },
    ("A", 0, 1): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "e1466ec50928b7e696e2e4a1cfb528b290fac6e7cca11f5a69031b75f59246ec",
        "label": {
            "class_index": 1,
            "class_name": "disk",
            "angle_deg": 229.30620743572354,
            "angle_sin": 0.0,
            "angle_cos": 0.0,
            "symmetry": "full",
            "angle_valid": False,
        },
    },
    ("A", 0, 2): {
        "shape": (96, 120, 3),
        "dtype": "uint8",
        "sha256": "0008e7be2a3ae9f6e47039e221a00878ad86a71545af9f90e25566525f5eb598",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 229.30620743572354,
            "angle_sin": -0.7582049802141122,
            "angle_cos": -0.6520162635843662,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
    ("B", 0, 0): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "3743b015a94facb6a8b9c311c8a2b340cb3f861f1e6d852dbaf0ab40d0f3fa3f",
        "label": {
            "class_index": 0,
            "class_name": "bar",
            "angle_deg": 229.30620743572354,
            "angle_sin": 0.9887239564605275,
            "angle_cos": -0.14974958404296465,
            "symmetry": "180",
            "angle_valid": True,
        },
    },
    ("B", 0, 1): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "a365ddc61c7468c88af44bef2fd6d9ca8817c3745e99b8443f44ddd1e555e0c3",
        "label": {
            "class_index": 1,
            "class_name": "disk",
            "angle_deg": 229.30620743572354,
            "angle_sin": 0.0,
            "angle_cos": 0.0,
            "symmetry": "full",
            "angle_valid": False,
        },
    },
    ("B", 0, 2): {
        "shape": (80, 112, 3),
        "dtype": "uint8",
        "sha256": "f515da88e1099096bf6b7a832c1bc54d18d68d526843c6200c89fb1b4347ee53",
        "label": {
            "class_index": 2,
            "class_name": "lshape",
            "angle_deg": 229.30620743572354,
            "angle_sin": -0.7582049802141122,
            "angle_cos": -0.6520162635843662,
            "symmetry": "none",
            "angle_valid": True,
        },
    },
}

# class_names отсортированы: bar=0, disk=1, lshape=2
SYMMETRY_MAP_GOLDEN: dict[str, dict[str, str]] = {
    "A": {"bar": "180", "disk": "full", "lshape": "none"},
    "B": {"bar": "180", "disk": "full", "lshape": "none"},
}

CASES = [(cfg, seed, None) for cfg in ("A", "B") for seed in range(5)] + [
    (cfg, 0, ci) for cfg in ("A", "B") for ci in (0, 1, 2)
]


@pytest.mark.parametrize(("cfg_id", "seed", "class_index"), CASES, ids=lambda v: str(v))
def test_generate_sample_matches_literal(tmp_path, cfg_id, seed, class_index):
    got = _snapshot(cfg_id, tmp_path, seed, class_index)
    want = GOLDEN[(cfg_id, seed, class_index)]
    assert got["shape"] == want["shape"]
    assert got["dtype"] == want["dtype"]
    lab, wlab = got["label"], want["label"]
    assert lab["class_index"] == wlab["class_index"]
    assert lab["class_name"] == wlab["class_name"]
    assert lab["symmetry"] == wlab["symmetry"]
    assert lab["angle_valid"] == wlab["angle_valid"]
    assert lab["angle_deg"] == pytest.approx(wlab["angle_deg"], rel=0, abs=1e-9)
    assert lab["angle_sin"] == pytest.approx(wlab["angle_sin"], rel=0, abs=1e-9)
    assert lab["angle_cos"] == pytest.approx(wlab["angle_cos"], rel=0, abs=1e-9)
    assert got["sha256"] == want["sha256"]


@pytest.mark.parametrize("cfg_id", ["A", "B"])
def test_symmetry_map_matches_literal(tmp_path, cfg_id):
    engine = DatasetEngine(_config(cfg_id, tmp_path))
    assert engine.symmetry_map == SYMMETRY_MAP_GOLDEN[cfg_id]
