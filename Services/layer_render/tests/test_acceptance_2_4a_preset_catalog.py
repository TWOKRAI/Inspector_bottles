"""Task 2.4a (слепой тест тестера): `ScenePreset` и каталог классов переезжают в `Services/layer_render`.

Пишется по acceptance-критериям A1-A5 и A8 плана `layer-render/phase-2-core-2.4a.md` (A6 — ручная проверка лида,
A7 — прогон наборов). Реализации в дереве нет по построению (worktree на коммите до кода): новых модулей
`layer_render.{preset,catalog,metadata,procedural_backgrounds}` нет.

ЗЕЛЁНЫЕ ДО ЗАДАЧИ (страховочная сеть: те же кейсы по СТАРЫМ путям + блок стенда + AST «старый модуль ещё определяет»):
  * A3 / A4  поведение каталога, меты, процедурных фонов и пресета через старые пути (литералы снимка ниже)
  * A5       блок стенда `line_sim.core.preset` (`REPO_ROOT`, `resolve_repo_path`, `load_scene_preset`, подмена relpath)
  * граница  чистый процесс: `import Services.dataset_gen` / `Services.line_sim` / `Services.layer_render` не ломается
КРАСНЫЕ ДО ЗАДАЧИ (новый API — `ModuleNotFoundError` / `AttributeError`; импорт идёт ВНУТРИ теста, не при сборе):
  * A1  тождества `is` и `__module__` (каждое имя — отдельный кейс)
  * A2  AST: старые модули не определяют переехавшее; новые — определяют
  * A3 / A4 те же поведенческие кейсы по НОВЫМ путям
  * A8  `Services.layer_render.__all__`

ОРАКУЛЫ. Ожидаемые значения — литералы словаря `_EXP`, снятые одноразовым скриптом на коде ДО переезда (по старым
путям); в тесте они не вычисляются из проверяемого кода. Деревья строит сам тест во `tmp_path` из детерминированных
массивов (`np.random.default_rng(<seed>)`); спрайты записываются PNG без потерь, так что оракул `get_sprite` — исходные
массивы, а не хэш.
Окружение снимка sha256 (цвета/хэши процедурных фонов и `_cover_crop` зависят от `INTER_CUBIC`/`GaussianBlur`):
Windows-10-10.0.19045-SP0, CPython 3.12.12, numpy 2.4.4, cv2 5.0.0. На другой платформе возможны расхождения —
прецедент в тестах 2.1, 2.3, 6.1.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
import yaml
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
_SERVICES = _ROOT / "Services"

# Старые и новые места одних и тех же механизмов (модуль каталога, модуль конфига с CatalogConfig).
_CATALOG_PATHS = (
    pytest.param(("Services.dataset_gen.core.catalog", "Services.dataset_gen.core.config"), id="old"),
    pytest.param(("Services.layer_render.catalog", "Services.layer_render.catalog"), id="new"),
)
_META_MODULES = (
    pytest.param("Services.dataset_gen.core.metadata", id="old"),
    pytest.param("Services.layer_render.metadata", id="new"),
)
_BG_MODULES = (
    pytest.param("Services.dataset_gen.core.backgrounds", id="old"),
    pytest.param("Services.layer_render.procedural_backgrounds", id="new"),
)
_PRESET_MODULES = (
    pytest.param("Services.line_sim.core.preset", id="old"),
    pytest.param("Services.layer_render.preset", id="new"),
)


def _mod(name: str) -> Any:
    """Импорт ВНУТРИ теста: отсутствующий модуль валит кейс, а не сбор файла."""
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# Сборщики деревьев (тест строит всё сам; без сети, без сна, без абсолютных путей в литералах)
# ---------------------------------------------------------------------------


def _rgba(seed: int, h: int = 5, w: int = 6) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (h, w, 4), dtype=np.uint8)


def _write_png_rgba(path: Path, rgba: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    assert ok
    path.write_bytes(buf.tobytes())


def _write_png_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    assert ok
    path.write_bytes(buf.tobytes())


# относительный путь спрайта -> seed его массива
_SPRITE_SEEDS = {
    "shapes/A/a0.png": 1,
    "shapes/A/a1.png": 2,
    "shapes/B/b0.png": 3,
    "tools/Жук/z0.png": 4,
}


def _build_class_tree(root: Path) -> dict[str, np.ndarray]:
    """Дерево классов: 3 листа, вложенность 2 уровня, кириллица, meta на корне и ниже, `_meta/`, README.txt."""
    oracle: dict[str, np.ndarray] = {}
    for rel, seed in _SPRITE_SEEDS.items():
        arr = _rgba(seed)
        _write_png_rgba(root / rel, arr)
        oracle[rel] = arr
    (root / "README.txt").write_text("не изображение", encoding="utf-8")
    (root / "meta.yaml").write_text('symmetry: "180"\ntags: [top]\nzone: north\n', encoding="utf-8")
    (root / "shapes" / "meta.yaml").write_text("description: геометрия\nsymmetry: full\n", encoding="utf-8")
    (root / "shapes" / "A" / "meta.yaml").write_text("display_name: Круг\ntags: [round, small]\n", encoding="utf-8")
    (root / "tools" / "Жук" / "meta.json").write_text(
        '{"symmetry": "none", "zone": "south", "display_name": "Жук-плотник"}', encoding="utf-8"
    )
    # служебные папки с «спрайтом» внутри — обязаны игнорироваться
    _write_png_rgba(root / "_meta" / "ghost.png", _rgba(99))
    _write_png_rgba(root / ".hidden" / "ghost.png", _rgba(98))
    return oracle


def _build_bg_dir(bg: Path) -> None:
    """Два однотонных фона разного цвета; один лежит в подпапке."""
    _write_png_rgb(bg / "red.png", np.full((40, 50, 3), (200, 10, 10), dtype=np.uint8))
    _write_png_rgb(bg / "sub" / "blue.png", np.full((30, 60, 3), (10, 10, 200), dtype=np.uint8))


def _gradient_image() -> np.ndarray:
    ys, xs = np.mgrid[0:40, 0:50]
    return np.stack([(xs * 5) % 256, (ys * 6) % 256, (xs + ys * 3) % 256], axis=-1).astype(np.uint8)


def _build_gradient_bg_dir(bg: Path) -> None:
    _write_png_rgb(bg / "grad.png", _gradient_image())


def _sha(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _make_catalog(paths: tuple[str, str], classes_dir: Path, backgrounds_dir: Path | None) -> Any:
    cat_mod, cfg_mod = _mod(paths[0]), _mod(paths[1])
    cfg = cfg_mod.CatalogConfig(classes_dir=classes_dir, backgrounds_dir=backgrounds_dir)
    return cat_mod.SpriteCatalog(cfg)


# ---------------------------------------------------------------------------
# Наблюдатели: одна и та же функция снимает литералы (на старом коде) и сверяет их (в тестах)
# ---------------------------------------------------------------------------


def _observe_entries(paths: tuple[str, str], tmp: Path) -> list[dict[str, Any]]:
    root = tmp / "classes"
    _build_class_tree(root)
    cat = _make_catalog(paths, root, None)
    out = []
    for i in range(cat.num_classes):
        e = cat.entry(i)
        out.append(
            {
                "name": e.name,
                "index": e.index,
                "path": list(e.path),
                "qualified_name": e.qualified_name,
                "display_name": e.display_name,
                "sprite_paths": [p.relative_to(root).as_posix() for p in e.sprite_paths],
                "meta": e.meta.model_dump(),
            }
        )
    return out


def _observe_names(paths: tuple[str, str], tmp: Path) -> dict[str, Any]:
    root = tmp / "classes"
    _build_class_tree(root)
    cat = _make_catalog(paths, root, None)
    return {"class_names": cat.class_names, "num_classes": cat.num_classes}


def _observe_sprite_choices(paths: tuple[str, str], tmp: Path) -> dict[str, list[int]]:
    """Для каждого класса — индекс выбранного эталона по seed 0..4 (узнаётся сравнением с исходными массивами)."""
    root = tmp / "classes"
    oracle = _build_class_tree(root)
    cat = _make_catalog(paths, root, None)
    out: dict[str, list[int]] = {}
    for i in range(cat.num_classes):
        entry = cat.entry(i)
        originals = [oracle[p.relative_to(root).as_posix()] for p in entry.sprite_paths]
        picked = []
        for seed in range(5):
            got = cat.get_sprite(i, np.random.default_rng(seed))
            assert got.dtype == np.uint8 and got.shape == (5, 6, 4)
            matches = [j for j, o in enumerate(originals) if np.array_equal(got, o)]
            assert len(matches) == 1, f"класс {entry.name}, seed {seed}: спрайт не совпал с исходным массивом"
            picked.append(matches[0])
        out[entry.name] = picked
    return out


def _observe_procedural_catalog_bg(paths: tuple[str, str], tmp: Path) -> dict[str, str]:
    root = tmp / "classes"
    _build_class_tree(root)
    cat = _make_catalog(paths, root, None)
    out = {}
    for seed in range(5):
        bg = cat.get_background(np.random.default_rng(seed), (24, 32))
        assert bg.shape == (24, 32, 3) and bg.dtype == np.uint8
        out[str(seed)] = _sha(bg)
    return out


_COLOR_NAMES = {(200, 10, 10): "red", (10, 10, 200): "blue"}


def _observe_folder_bg(paths: tuple[str, str], tmp: Path) -> dict[str, list[str]]:
    """Фоны из папки: цвет кропа (узнаём выбор по цвету, не по приватному кэшу) + sha256, seed 0..4, два размера."""
    root, bg_dir = tmp / "classes", tmp / "bgs"
    _build_class_tree(root)
    _build_bg_dir(bg_dir)
    cat = _make_catalog(paths, root, bg_dir)
    out: dict[str, list[str]] = {}
    for size in ((8, 12), (64, 80)):
        row = []
        for seed in range(5):
            crop = cat.get_background(np.random.default_rng(seed), size)
            assert crop.shape == (*size, 3) and crop.dtype == np.uint8
            corner = tuple(int(v) for v in crop[0, 0])
            assert (crop == crop[0, 0]).all(), "однотонный фон дал неоднородный кроп"
            row.append(f"{_COLOR_NAMES[corner]}:{_sha(crop)}")
        out[f"{size[0]}x{size[1]}"] = row
    return out


def _observe_gradient_bg(paths: tuple[str, str], tmp: Path) -> dict[str, list[str]]:
    """Неоднородный фон: `_cover_crop` в обе стороны масштаба (уменьшение — INTER_AREA, увеличение — INTER_LINEAR)."""
    root, bg_dir = tmp / "classes", tmp / "bgs"
    _build_class_tree(root)
    _build_gradient_bg_dir(bg_dir)
    cat = _make_catalog(paths, root, bg_dir)
    out: dict[str, list[str]] = {}
    for size in ((30, 30), (50, 60), (60, 80)):  # 40x50 -> вниз с случайным смещением / вверх / вверх сильнее
        out[f"{size[0]}x{size[1]}"] = [_sha(cat.get_background(np.random.default_rng(s), size)) for s in range(6)]
    return out


def _observe_bad_sprite_error(paths: tuple[str, str], tmp: Path) -> tuple[str, str]:
    root = tmp / "bad_classes"
    p = root / "cls" / "s.png"
    p.parent.mkdir(parents=True)
    bgr = np.random.default_rng(5).integers(0, 256, (5, 6, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", bgr)
    assert ok
    p.write_bytes(buf.tobytes())
    cat = _make_catalog(paths, root, None)
    with pytest.raises(ValueError) as ei:
        cat.load()
    msg = str(ei.value)
    prefix, sep, tail = msg.partition(": ")
    assert sep, msg
    return prefix.split(" ")[0], tail


_BG_SIZES = ((24, 32), (17, 40))


def _observe_procedural(bg_mod: str) -> dict[str, str]:
    m = _mod(bg_mod)
    out = {}
    for h, w in _BG_SIZES:
        for seed in range(10):
            out[f"{seed},{h}x{w}"] = _sha(m.procedural_background(np.random.default_rng(seed), (h, w)))
    return out


def _observe_generators(bg_mod: str) -> dict[str, str]:
    m = _mod(bg_mod)
    out = {}
    for fname in ("gradient_bg", "brushed_metal_bg", "conveyor_belt_bg", "speckled_bg"):
        for seed in (0, 1):
            out[f"{fname},{seed}"] = _sha(getattr(m, fname)(np.random.default_rng(seed), (24, 32)))
    return out


_META_FILE_BODIES = {
    "meta.yaml": 'display_name: "Круг"\nsymmetry: "180"\ntags: [a, b]\nzone: x\n',
    "meta.yml": "symmetry: full\ndescription: yml\n",
    "meta.json": '{"display_name": "J", "symmetry": "none", "tags": ["j"], "extra_k": 7}',
}


def _observe_load_meta(meta_mod: str, tmp: Path) -> dict[str, Any]:
    m = _mod(meta_mod)
    out: dict[str, Any] = {}
    empty = tmp / "empty"
    empty.mkdir()
    out["no_meta"] = m.load_meta(empty).model_dump()
    for fname, body in _META_FILE_BODIES.items():
        d = tmp / fname.replace(".", "_")
        d.mkdir()
        (d / fname).write_text(body, encoding="utf-8")
        out[fname] = m.load_meta(d).model_dump()
    both = tmp / "both"
    both.mkdir()
    (both / "meta.yaml").write_text("display_name: from-yaml\n", encoding="utf-8")
    (both / "meta.json").write_text('{"display_name": "from-json"}', encoding="utf-8")
    out["yaml_wins_over_json"] = m.load_meta(both).model_dump()
    blank = tmp / "blank"
    blank.mkdir()
    (blank / "meta.yaml").write_text("", encoding="utf-8")
    out["empty_yaml"] = m.load_meta(blank).model_dump()
    return out


def _observe_load_meta_not_a_dict(meta_mod: str, tmp: Path) -> str:
    m = _mod(meta_mod)
    d = tmp / "list_meta"
    d.mkdir()
    (d / "meta.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        m.load_meta(d)
    return str(ei.value).partition(": ")[2]


def _observe_write_meta(meta_mod: str, tmp: Path) -> dict[str, Any]:
    m = _mod(meta_mod)
    d = tmp / "w"
    d.mkdir()
    meta = m.ClassMeta(display_name="Круг", symmetry="180", tags=["a"], zone="x")
    written = m.write_meta(d, meta)
    return {
        "returned_name": written.name,
        "returned_parent_is_dir": written.parent == d,
        "text": (d / "meta.yaml").read_text(encoding="utf-8"),
        "reload": m.load_meta(d).model_dump(),
    }


def _observe_merge(meta_mod: str) -> dict[str, Any]:
    m = _mod(meta_mod)
    parent = m.ClassMeta(display_name="P", symmetry="180", tags=["t"], k=1, j=2)
    child = m.ClassMeta(symmetry="none", j=3, tags=[])
    merged = parent.merged_with_child(child)
    return {"to_dict": merged.to_dict(), "extra": merged.extra}


_PRESET_DICTS: dict[str, dict[str, Any]] = {
    "catalog": {"catalog_dir": "data/classes", "angle_range_deg": [10, 20.5], "defect_probability": 0.25},
    "layers": {
        "layers": [
            {"name": "back", "mode": "static", "sprite_source": "fixture://back"},
            {
                "name": "base",
                "mode": "augmented",
                "sprite_source": "sprites/s.png",
                "offset_px": [1, -2],
                "augment": {"angle_deg": [-5, 5]},
            },
        ]
    },
    "both_class": {
        "catalog_dir": "cls",
        "base_dir": "fixed/base",
        "layers": [
            {"name": "body", "mode": "static", "sprite_source": "class://"},
            {"name": "scratch", "mode": "defect", "sprite_source": "sprites/scratch.png", "defect_probability": 0.5},
        ],
    },
}


def _observe_preset_roundtrip(preset_mod: str) -> dict[str, Any]:
    sp = _mod(preset_mod).ScenePreset
    return {k: sp.from_dict(d).to_dict() for k, d in _PRESET_DICTS.items()}


_YAML_PRESET = {
    "catalog_dir": "classes/x",
    "layers": [
        {"name": "body", "mode": "static", "sprite_source": "class://"},
        {"name": "s", "mode": "static", "sprite_source": "sprites/s.png"},
        {"name": "i", "mode": "static", "sprite_source": "fixture://i"},
    ],
}


def _observe_to_yaml(preset_mod: str, tmp: Path) -> dict[str, Any]:
    sp = _mod(preset_mod).ScenePreset
    a, b = tmp / "a", tmp / "b"
    a.mkdir()
    b.mkdir()
    preset = sp.from_dict({**_YAML_PRESET, "base_dir": str(a)})
    preset.to_yaml(a / "p.yaml")
    preset.to_yaml(b / "p.yaml")
    return {
        "same_dir": yaml.safe_load((a / "p.yaml").read_text(encoding="utf-8")),
        "neighbour_dir": yaml.safe_load((b / "p.yaml").read_text(encoding="utf-8")),
    }


_PRESET_ERROR_DICTS: dict[str, dict[str, Any]] = {
    "empty": {},
    "reserved_base": {"catalog_dir": "c", "layers": [{"name": "base", "mode": "static", "sprite_source": "x.png"}]},
    "reserved_damaged": {
        "catalog_dir": "c",
        "layers": [{"name": "damaged", "mode": "static", "sprite_source": "x.png"}],
    },
    "angle_lo_gt_hi": {"catalog_dir": "c", "angle_range_deg": [30, 10]},
}


def _observe_preset_errors(preset_mod: str) -> dict[str, list[list[Any]]]:
    sp = _mod(preset_mod).ScenePreset
    out = {}
    for key, d in _PRESET_ERROR_DICTS.items():
        with pytest.raises(ValidationError) as ei:
            sp.from_dict(d)
        out[key] = [[list(e["loc"]), e["msg"]] for e in ei.value.errors()]
    return out


# Литералы сняты одноразовым скриптом по СТАРЫМ путям на коде до переезда (коммит c05a9a07d).
# Окружение: Windows-10-10.0.19045-SP0, CPython 3.12.12, numpy 2.4.4, cv2 5.0.0.
_EXP: dict[str, Any] = {
    "names": {"class_names": ["A", "B", "Жук"], "num_classes": 3},
    "entries": [
        {
            "name": "A",
            "index": 0,
            "path": ["shapes", "A"],
            "qualified_name": "shapes/A",
            "display_name": "Круг",
            "sprite_paths": ["shapes/A/a0.png", "shapes/A/a1.png"],
            "meta": {
                "display_name": "Круг",
                "symmetry": "full",
                "description": "геометрия",
                "tags": ["round", "small"],
                "zone": "north",
            },
        },
        {
            "name": "B",
            "index": 1,
            "path": ["shapes", "B"],
            "qualified_name": "shapes/B",
            "display_name": "B",
            "sprite_paths": ["shapes/B/b0.png"],
            "meta": {
                "display_name": None,
                "symmetry": "full",
                "description": "геометрия",
                "tags": ["top"],
                "zone": "north",
            },
        },
        {
            "name": "Жук",
            "index": 2,
            "path": ["tools", "Жук"],
            "qualified_name": "tools/Жук",
            "display_name": "Жук-плотник",
            "sprite_paths": ["tools/Жук/z0.png"],
            "meta": {
                "display_name": "Жук-плотник",
                "symmetry": "none",
                "description": None,
                "tags": ["top"],
                "zone": "south",
            },
        },
    ],
    "sprite_choices": {"A": [1, 0, 1, 1, 1], "B": [0, 0, 0, 0, 0], "Жук": [0, 0, 0, 0, 0]},
    "catalog_procedural_bg": {
        "0": "75a149e7475c067da4070fb764f689a15436926906db1b24261d6e7b502d52f4",
        "1": "34b4b8258f0c4bd2742aef6e9dc7fef13191ff1292513877d0d469a7c5903b7d",
        "2": "5abf51869e016b7a196b601ea6663a70251348d6d6d5abb0599dd507efd840eb",
        "3": "53c9b39ca9599b12f53fdf06b6bcd6377bf38ba3904ef4fb30c2a582317cc336",
        "4": "bfde833007ae31fcfef39da2a73cab25fa5fa7c2f5eeb8b5c4f905644d91b77b",
    },
    "folder_bg": {
        "8x12": [
            "blue:73b95782ee48bf8557b7e1ecf91888468186e283445fa3f046d4874b287a1df0",
            "red:d327c67fbf93553e9a74434ccd9792ee53d672d11c0f1d3cd6a57e61a31babf2",
            "blue:73b95782ee48bf8557b7e1ecf91888468186e283445fa3f046d4874b287a1df0",
            "blue:73b95782ee48bf8557b7e1ecf91888468186e283445fa3f046d4874b287a1df0",
            "blue:73b95782ee48bf8557b7e1ecf91888468186e283445fa3f046d4874b287a1df0",
        ],
        "64x80": [
            "blue:96daaf982457a723f93f48da081c2496e02d0513f1aa3f6d9f9f288a8089332e",
            "red:e8f1ee416b97d88a8da357f96b090122f5fed936e2aed6176f5356711c3b9d28",
            "blue:96daaf982457a723f93f48da081c2496e02d0513f1aa3f6d9f9f288a8089332e",
            "blue:96daaf982457a723f93f48da081c2496e02d0513f1aa3f6d9f9f288a8089332e",
            "blue:96daaf982457a723f93f48da081c2496e02d0513f1aa3f6d9f9f288a8089332e",
        ],
    },
    "gradient_bg": {
        "30x30": [
            "36b24167a8063b8d8d09214e766c5b28f12cbc9bdf57c99675e884fc4879e0e2",
            "b691970f22915a468cf9f66ff74815dee85cd80e967526b27270951289aeae6b",
            "36b24167a8063b8d8d09214e766c5b28f12cbc9bdf57c99675e884fc4879e0e2",
            "36b24167a8063b8d8d09214e766c5b28f12cbc9bdf57c99675e884fc4879e0e2",
            "07740f518cd85f7028cfd43daa252b84abf1a412c7e28508fbec88f81d853ffc",
            "07740f518cd85f7028cfd43daa252b84abf1a412c7e28508fbec88f81d853ffc",
        ],
        "50x60": [
            "3fa75f00785605feb04004e7340ccf46e92b3dca471576963dc7dcc404e5765a",
            "a9c2fa29346ab45faa98195dea4bb5f712a44565db302d60c0e2e051bfeda96a",
            "3fa75f00785605feb04004e7340ccf46e92b3dca471576963dc7dcc404e5765a",
            "3fa75f00785605feb04004e7340ccf46e92b3dca471576963dc7dcc404e5765a",
            "3fa75f00785605feb04004e7340ccf46e92b3dca471576963dc7dcc404e5765a",
            "3fa75f00785605feb04004e7340ccf46e92b3dca471576963dc7dcc404e5765a",
        ],
        "60x80": [
            "a4aded93a02a95bd30033690318ebddbd795969126e19de1b717be166be982db",
            "c592df3aeab7253675862e1cd2b1ca8386734176d421ec3f16436e6484e00089",
            "a4aded93a02a95bd30033690318ebddbd795969126e19de1b717be166be982db",
            "a4aded93a02a95bd30033690318ebddbd795969126e19de1b717be166be982db",
            "2e15804c2170d7141bba500ea46b8809922d5255f7859a006402423eca59cf74",
            "2e15804c2170d7141bba500ea46b8809922d5255f7859a006402423eca59cf74",
        ],
    },
    "bad_sprite_tail": "нужен альфа-канал (RGBA, объект на прозрачном фоне), получено shape=(5, 6, 3)",
    "procedural": {
        "0,24x32": "75a149e7475c067da4070fb764f689a15436926906db1b24261d6e7b502d52f4",
        "1,24x32": "34b4b8258f0c4bd2742aef6e9dc7fef13191ff1292513877d0d469a7c5903b7d",
        "2,24x32": "5abf51869e016b7a196b601ea6663a70251348d6d6d5abb0599dd507efd840eb",
        "3,24x32": "53c9b39ca9599b12f53fdf06b6bcd6377bf38ba3904ef4fb30c2a582317cc336",
        "4,24x32": "bfde833007ae31fcfef39da2a73cab25fa5fa7c2f5eeb8b5c4f905644d91b77b",
        "5,24x32": "357c390e09e7cc1b205fb6a89f99f55564860746c32cad970cc154c5b04b8052",
        "6,24x32": "0a72189ba012a712d44a1b95d710d8fbeaba26952463fbb21514853e641d4756",
        "7,24x32": "b727f50b1124aa1bb3eab8667f71d2948dd7785ba0c587016f745a3a3527734d",
        "8,24x32": "f36282776ff4eacebf22145d0168a11f4ad35eb41559e0b20fedd75a47da3854",
        "9,24x32": "f724867c0ac28693663bddc7c5bb072a8c9f75f70fbed668905fe3b6dd8342c4",
        "0,17x40": "3fb486a10fc957f5ee7f20ce3a6b28d6ba9ee4bc63bb35121d7a1aa969a94b6c",
        "1,17x40": "8ea307fb6481c305c46e7b07556400bf4043bf1e863bb1ce0d1bcc1653c8513c",
        "2,17x40": "efe6c3a6e54a4d7b8228ab86499ad3aa37cfe1ed238232382a6144714e59302d",
        "3,17x40": "d5157a08b80418670ae1b449f4f3b18ccdc6b25e03785d733550effbdffd9c48",
        "4,17x40": "bd6128db8d3828a58a81678e83b3a22bd915f4f0ed33314de2540280fe054cc7",
        "5,17x40": "1d5ec0e954fe8fda3872172643fc0bcbeb94fc818f999c3167edcbf96a18cbe9",
        "6,17x40": "2fa77b921c68602c98fe4ba5deca914025ad2bcaac49928912ca87ca504c0d80",
        "7,17x40": "889210a79423f95aee508e7ffba0ea6a4f4e01acd50b8eb1d04b8e6990390e84",
        "8,17x40": "33e4235a05d43f29f61f8f06f23d50cd0d3291e785bd2e313c1848fcdffaf3c8",
        "9,17x40": "3804620c1526c8b14663a4d5888ccadf4f1a195103c8040b7ffe22cb1569c17e",
    },
    "generators": {
        "gradient_bg,0": "cadd21b3ad466798de60c2df3f74efd6f4c0cee2402edef517006967d887e527",
        "gradient_bg,1": "f70c2059c1ff904577fcebb42345ac5a621b94efe3a16b982d74eee01f9b2460",
        "brushed_metal_bg,0": "5e3380da702a6380ffe6ea0a57c8fd0119fbbfc5527a3c426b56ba7bfa9a5960",
        "brushed_metal_bg,1": "3a1491976f652de1cb9ef33428acc7dba12cb0e446459e52f28346d37624f2f9",
        "conveyor_belt_bg,0": "01819e6b2385778b6236fea08a839f610ff3b98edf902a3972851d389c65c784",
        "conveyor_belt_bg,1": "1fe5fd89e0d2c968a84724090e8e280cf803dfc1dae5939594c65600364b953f",
        "speckled_bg,0": "c1892fc7bdffe2e9035968c287241c1cd680c4dcb241c7deb112a5efedf0c106",
        "speckled_bg,1": "e88c1c4ba5d0b87643b03923e663f21d7d396f82a2073cf61fb590a464e3edd0",
    },
    "load_meta": {
        "no_meta": {"display_name": None, "symmetry": None, "description": None, "tags": []},
        "meta.yaml": {"display_name": "Круг", "symmetry": "180", "description": None, "tags": ["a", "b"], "zone": "x"},
        "meta.yml": {"display_name": None, "symmetry": "full", "description": "yml", "tags": []},
        "meta.json": {"display_name": "J", "symmetry": "none", "description": None, "tags": ["j"], "extra_k": 7},
        "yaml_wins_over_json": {"display_name": "from-yaml", "symmetry": None, "description": None, "tags": []},
        "empty_yaml": {"display_name": None, "symmetry": None, "description": None, "tags": []},
    },
    "load_meta_not_dict_tail": "ожидался словарь, получено list",
    "write_meta": {
        "returned_name": "meta.yaml",
        "returned_parent_is_dir": True,
        "text": "display_name: Круг\nsymmetry: '180'\ntags:\n- a\nzone: x\n",
        "reload": {"display_name": "Круг", "symmetry": "180", "description": None, "tags": ["a"], "zone": "x"},
    },
    "merge": {
        "to_dict": {"display_name": "P", "symmetry": "none", "description": None, "tags": ["t"], "k": 1, "j": 3},
        "extra": {"k": 1, "j": 3},
    },
    "preset_roundtrip": {
        "catalog": {
            "catalog_dir": "data/classes",
            "angle_range_deg": [10.0, 20.5],
            "defect_probability": 0.25,
            "layers": [],
            "base_dir": None,
        },
        "layers": {
            "catalog_dir": None,
            "angle_range_deg": [0.0, 360.0],
            "defect_probability": 0.0,
            "layers": [
                {
                    "name": "back",
                    "mode": "static",
                    "sprite_source": "fixture://back",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
                {
                    "name": "base",
                    "mode": "augmented",
                    "sprite_source": "sprites/s.png",
                    "offset_px": [1.0, -2.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": {
                        "offset_x_px": [0.0, 0.0],
                        "offset_y_px": [0.0, 0.0],
                        "angle_deg": [-5.0, 5.0],
                        "scale": [1.0, 1.0],
                        "hue_shift_deg": [0.0, 0.0],
                    },
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
            ],
            "base_dir": None,
        },
        "both_class": {
            "catalog_dir": "cls",
            "angle_range_deg": [0.0, 360.0],
            "defect_probability": 0.0,
            "layers": [
                {
                    "name": "body",
                    "mode": "static",
                    "sprite_source": "class://",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
                {
                    "name": "scratch",
                    "mode": "defect",
                    "sprite_source": "sprites/scratch.png",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.5,
                    "color_rgb": None,
                },
            ],
            "base_dir": "fixed/base",
        },
    },
    "to_yaml": {
        "same_dir": {
            "catalog_dir": "classes/x",
            "angle_range_deg": [0.0, 360.0],
            "defect_probability": 0.0,
            "layers": [
                {
                    "name": "body",
                    "mode": "static",
                    "sprite_source": "class://",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
                {
                    "name": "s",
                    "mode": "static",
                    "sprite_source": "sprites/s.png",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
                {
                    "name": "i",
                    "mode": "static",
                    "sprite_source": "fixture://i",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
            ],
        },
        "neighbour_dir": {
            "catalog_dir": "../a/classes/x",
            "angle_range_deg": [0.0, 360.0],
            "defect_probability": 0.0,
            "layers": [
                {
                    "name": "body",
                    "mode": "static",
                    "sprite_source": "class://",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
                {
                    "name": "s",
                    "mode": "static",
                    "sprite_source": "../a/sprites/s.png",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
                {
                    "name": "i",
                    "mode": "static",
                    "sprite_source": "fixture://i",
                    "offset_px": [0.0, 0.0],
                    "angle_deg": 0.0,
                    "scale": 1.0,
                    "augment": None,
                    "defect_probability": 0.0,
                    "color_rgb": None,
                },
            ],
        },
    },
    "preset_errors": {
        "empty": [
            [[], "Value error, пресет без catalog_dir и без layers: нечего рисовать — нужен хотя бы один источник"]
        ],
        "reserved_base": [
            [
                [],
                "Value error, слои ['base']: имена зарезервированы ObjectFactory (база "
                "и дефект-слой ставятся под именами ['base', 'damaged']) — "
                "переименуйте слои пресета",
            ]
        ],
        "reserved_damaged": [
            [
                [],
                "Value error, слои ['damaged']: имена зарезервированы ObjectFactory "
                "(база и дефект-слой ставятся под именами ['base', 'damaged']) — "
                "переименуйте слои пресета",
            ]
        ],
        "angle_lo_gt_hi": [[["angle_range_deg"], "Value error, angle_range_deg: lo=30.0 > hi=10.0"]],
    },
    "load_none_none_msgs": [
        "Value error, пресет без catalog_dir и без layers: нечего рисовать — нужен хотя бы один источник"
    ],
}


# ---------------------------------------------------------------------------
# A1. Идентичность и __module__ — каждое имя отдельным кейсом
# ---------------------------------------------------------------------------

_P = "Services.layer_render.preset"
_C = "Services.layer_render.catalog"
_M = "Services.layer_render.metadata"
_B = "Services.layer_render.procedural_backgrounds"

# (старый модуль, имя в старом модуле, новый модуль, имя в новом). Объекты со своим __module__ — отдельный список ниже.
_IDENTITY: list[tuple[str, str, str, str]] = [
    ("Services.line_sim.core.preset", "ScenePreset", _P, "ScenePreset"),
    ("Services.line_sim.core.preset", "CLASS_SPRITE_SOURCE", _P, "CLASS_SPRITE_SOURCE"),
    ("Services.line_sim", "ScenePreset", _P, "ScenePreset"),
    ("Services.line_sim.core", "ScenePreset", _P, "ScenePreset"),
    ("Services.dataset_gen.core.catalog", "SpriteCatalog", _C, "SpriteCatalog"),
    ("Services.dataset_gen.core.catalog", "ClassEntry", _C, "ClassEntry"),
    ("Services.dataset_gen.core.catalog", "SPRITE_SUFFIXES", _C, "SPRITE_SUFFIXES"),
    ("Services.dataset_gen.core.catalog", "BACKGROUND_SUFFIXES", _C, "BACKGROUND_SUFFIXES"),
    ("Services.dataset_gen.core.config", "CatalogConfig", _C, "CatalogConfig"),
    ("Services.dataset_gen.core.metadata", "ClassMeta", _M, "ClassMeta"),
    ("Services.dataset_gen.core.metadata", "load_meta", _M, "load_meta"),
    ("Services.dataset_gen.core.metadata", "write_meta", _M, "write_meta"),
    ("Services.dataset_gen.core.metadata", "META_FILENAMES", _M, "META_FILENAMES"),
    ("Services.dataset_gen.core.config", "SymmetryType", _M, "SymmetryType"),
    ("Services.dataset_gen.core.backgrounds", "procedural_background", _B, "procedural_background"),
    ("Services.dataset_gen.core.backgrounds", "gradient_bg", _B, "gradient_bg"),
    ("Services.dataset_gen.core.backgrounds", "brushed_metal_bg", _B, "brushed_metal_bg"),
    ("Services.dataset_gen.core.backgrounds", "conveyor_belt_bg", _B, "conveyor_belt_bg"),
    ("Services.dataset_gen.core.backgrounds", "speckled_bg", _B, "speckled_bg"),
    ("Services.dataset_gen.core.backgrounds", "_GENERATORS", _B, "_GENERATORS"),
    ("Services.dataset_gen.core.catalog", "imread_unicode", "Services.layer_render.io", "imread_unicode"),
    ("Services.dataset_gen.core.catalog", "imwrite_unicode", "Services.layer_render.io", "imwrite_unicode"),
    # пакетный уровень
    ("Services.dataset_gen.core", "SpriteCatalog", _C, "SpriteCatalog"),
    ("Services.dataset_gen.core", "ClassMeta", _M, "ClassMeta"),
    ("Services.dataset_gen.core", "SymmetryType", _M, "SymmetryType"),
    ("Services.dataset_gen.core", "load_meta", _M, "load_meta"),
    ("Services.dataset_gen.core", "write_meta", _M, "write_meta"),
    ("Services.dataset_gen", "ClassMeta", _M, "ClassMeta"),
    ("Services.dataset_gen", "SymmetryType", _M, "SymmetryType"),
]


@pytest.mark.parametrize(
    ("old_mod", "old_name", "new_mod", "new_name"),
    [pytest.param(*row, id=f"{row[0]}.{row[1]}") for row in _IDENTITY],
)
def test_a1_old_path_returns_the_same_object(old_mod: str, old_name: str, new_mod: str, new_name: str) -> None:
    new_obj = getattr(_mod(new_mod), new_name)
    old_obj = getattr(_mod(old_mod), old_name)
    assert old_obj is new_obj


# имя -> модуль, в котором объект обязан быть определён (классы и функции; константы и Literal без __module__)
_DEFINED_IN: list[tuple[str, str]] = [
    (_P, "ScenePreset"),
    (_C, "SpriteCatalog"),
    (_C, "ClassEntry"),
    (_C, "CatalogConfig"),
    (_M, "ClassMeta"),
    (_M, "load_meta"),
    (_M, "write_meta"),
    (_B, "procedural_background"),
    (_B, "gradient_bg"),
    (_B, "brushed_metal_bg"),
    (_B, "conveyor_belt_bg"),
    (_B, "speckled_bg"),
]


@pytest.mark.parametrize(("mod", "name"), [pytest.param(m, n, id=f"{m.rsplit('.', 1)[1]}.{n}") for m, n in _DEFINED_IN])
def test_a1_object_is_defined_in_the_new_module(mod: str, name: str) -> None:
    assert getattr(_mod(mod), name).__module__ == mod


@pytest.mark.parametrize("name", ["imread_unicode", "imwrite_unicode"])
def test_a1_unicode_io_reexport_keeps_its_home_in_layer_render_io(name: str) -> None:
    old = getattr(_mod("Services.dataset_gen.core.catalog"), name)
    assert old.__module__ == "Services.layer_render.io"


def test_a1_generator_config_catalog_field_is_the_moved_class() -> None:
    new_cls = _mod(_C).CatalogConfig
    field = _mod("Services.dataset_gen.core.config").GeneratorConfig.model_fields["catalog"]
    assert field.annotation is new_cls


# константы: значение — литерал (отдельно от тождества, которое для них слабее)
def test_a1_constants_keep_their_literal_values() -> None:
    assert _mod(_M).META_FILENAMES == ("meta.yaml", "meta.yml", "meta.json")
    assert _mod(_C).SPRITE_SUFFIXES == {".png", ".webp", ".tif", ".tiff"}
    assert _mod(_C).BACKGROUND_SUFFIXES == {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
    assert _mod(_P).CLASS_SPRITE_SOURCE == "class://"


# ---------------------------------------------------------------------------
# A2. AST: старые модули не определяют переехавшее (парсим, не импортируем)
# ---------------------------------------------------------------------------


def _tree(rel: str) -> ast.Module:
    return ast.parse((_SERVICES / rel).read_text(encoding="utf-8"), filename=rel)


def _assigned_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _top_defs(tree: ast.Module) -> set[str]:
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


@pytest.mark.parametrize(
    "rel", ["dataset_gen/core/catalog.py", "dataset_gen/core/metadata.py", "dataset_gen/core/backgrounds.py"]
)
def test_a2_old_reexport_modules_define_no_def_or_class_anywhere(rel: str) -> None:
    defs = [
        n.name for n in ast.walk(_tree(rel)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert defs == []


def test_a2_dataset_gen_config_no_longer_defines_catalog_config() -> None:
    assert "CatalogConfig" not in _top_defs(_tree("dataset_gen/core/config.py"))


@pytest.mark.parametrize("rel", ["dataset_gen/core/config.py", "dataset_gen/core/metadata.py"])
def test_a2_symmetry_type_is_not_assigned_in_old_modules(rel: str) -> None:
    assert "SymmetryType" not in _assigned_names(_tree(rel))


def test_a2_line_sim_preset_no_longer_defines_scene_preset() -> None:
    assert "ScenePreset" not in _top_defs(_tree("line_sim/core/preset.py"))


@pytest.mark.parametrize("name", ["resolve_repo_path", "apply_defect_override", "load_scene_preset"])
def test_a2_line_sim_preset_keeps_the_stand_functions(name: str) -> None:
    assert name in _top_defs(_tree("line_sim/core/preset.py"))


@pytest.mark.parametrize("name", ["REPO_ROOT", "DEFAULT_DEFECT_PROBABILITY"])
def test_a2_line_sim_preset_keeps_the_stand_constants(name: str) -> None:
    assert name in _assigned_names(_tree("line_sim/core/preset.py"))


def test_a2_line_sim_preset_keeps_module_level_import_os() -> None:
    imports = [n for n in _tree("line_sim/core/preset.py").body if isinstance(n, ast.Import)]
    assert any(alias.name == "os" and alias.asname is None for n in imports for alias in n.names)


# новый дом: определено именно здесь (положительная сторона A2)
_NEW_HOME_DEFS = {
    "layer_render/preset.py": ({"ScenePreset"}, {"CLASS_SPRITE_SOURCE"}),
    "layer_render/catalog.py": (
        {"SpriteCatalog", "ClassEntry", "CatalogConfig", "_cover_crop"},
        {"SPRITE_SUFFIXES", "BACKGROUND_SUFFIXES"},
    ),
    "layer_render/metadata.py": ({"ClassMeta", "load_meta", "write_meta"}, {"META_FILENAMES", "SymmetryType"}),
    "layer_render/procedural_backgrounds.py": (
        {"procedural_background", "gradient_bg", "brushed_metal_bg", "conveyor_belt_bg", "speckled_bg"},
        {"_GENERATORS"},
    ),
}


@pytest.mark.parametrize("rel", sorted(_NEW_HOME_DEFS))
def test_a2_new_modules_define_the_moved_names(rel: str) -> None:
    defs, assigns = _NEW_HOME_DEFS[rel]
    tree = _tree(rel)
    assert defs <= _top_defs(tree)
    assert assigns <= _assigned_names(tree)


@pytest.mark.parametrize("rel", sorted(_NEW_HOME_DEFS))
def test_a2_new_modules_do_not_import_dataset_gen_or_line_sim(rel: str) -> None:
    bad = []
    for node in ast.walk(_tree(rel)):
        mods = (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else []
        )
        bad += [m for m in mods if m.startswith(("Services.dataset_gen", "Services.line_sim"))]
    assert bad == []


# ---------------------------------------------------------------------------
# A3. Поведение каталога прежнее (старые и новые пути; литералы _EXP сняты на коде ДО переезда)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_class_names_and_count(paths: tuple[str, str], tmp_path: Path) -> None:
    assert _observe_names(paths, tmp_path) == _EXP["names"]


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_entries_fields_and_inherited_meta(paths: tuple[str, str], tmp_path: Path) -> None:
    assert _observe_entries(paths, tmp_path) == _EXP["entries"]


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_get_sprite_returns_the_written_arrays_and_picks_both_sprites(
    paths: tuple[str, str], tmp_path: Path
) -> None:
    choices = _observe_sprite_choices(paths, tmp_path)
    assert choices == _EXP["sprite_choices"]
    assert set(choices["A"]) == {0, 1}  # seed 0..4 выбрали оба эталона класса с двумя


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_get_background_procedural_sha256(paths: tuple[str, str], tmp_path: Path) -> None:
    assert _observe_procedural_catalog_bg(paths, tmp_path) == _EXP["catalog_procedural_bg"]


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_get_background_from_folder_picks_both_files(paths: tuple[str, str], tmp_path: Path) -> None:
    observed = _observe_folder_bg(paths, tmp_path)
    assert observed == _EXP["folder_bg"]
    picked = {cell.split(":")[0] for row in observed.values() for cell in row}
    assert picked == {"red", "blue"}  # оба файла (в том числе из подпапки) выбираются по seed 0..4


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_get_background_cover_crop_sha256_on_a_non_uniform_image(paths: tuple[str, str], tmp_path: Path) -> None:
    assert _observe_gradient_bg(paths, tmp_path) == _EXP["gradient_bg"]


@pytest.mark.parametrize("paths", _CATALOG_PATHS)
def test_a3_sprite_without_alpha_raises_value_error_with_literal_tail(paths: tuple[str, str], tmp_path: Path) -> None:
    head, tail = _observe_bad_sprite_error(paths, tmp_path)
    assert head == "Эталон"
    assert tail == _EXP["bad_sprite_tail"]


@pytest.mark.parametrize("bg_mod", _BG_MODULES)
def test_a3_procedural_background_sha256_seeds_0_9_two_sizes(bg_mod: str) -> None:
    assert _observe_procedural(bg_mod) == _EXP["procedural"]


@pytest.mark.parametrize("bg_mod", _BG_MODULES)
def test_a3_each_background_generator_sha256(bg_mod: str) -> None:
    assert _observe_generators(bg_mod) == _EXP["generators"]


@pytest.mark.parametrize("meta_mod", _META_MODULES)
def test_a3_load_meta_for_every_file_name(meta_mod: str, tmp_path: Path) -> None:
    assert _observe_load_meta(meta_mod, tmp_path) == _EXP["load_meta"]


@pytest.mark.parametrize("meta_mod", _META_MODULES)
def test_a3_load_meta_non_dict_error_tail(meta_mod: str, tmp_path: Path) -> None:
    assert _observe_load_meta_not_a_dict(meta_mod, tmp_path) == _EXP["load_meta_not_dict_tail"]


@pytest.mark.parametrize("meta_mod", _META_MODULES)
def test_a3_write_meta_text_and_roundtrip(meta_mod: str, tmp_path: Path) -> None:
    assert _observe_write_meta(meta_mod, tmp_path) == _EXP["write_meta"]


@pytest.mark.parametrize("meta_mod", _META_MODULES)
def test_a3_merged_with_child_and_to_dict(meta_mod: str) -> None:
    assert _observe_merge(meta_mod) == _EXP["merge"]


# ---------------------------------------------------------------------------
# A4. Поведение пресета прежнее (литералы до переезда; msg и loc, не str(exc))
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_from_dict_to_dict_for_three_dicts(preset_mod: str) -> None:
    assert _observe_preset_roundtrip(preset_mod) == _EXP["preset_roundtrip"]


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_to_yaml_same_dir_and_neighbour_dir(preset_mod: str, tmp_path: Path) -> None:
    assert _observe_to_yaml(preset_mod, tmp_path) == _EXP["to_yaml"]


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_validation_errors_loc_and_msg(preset_mod: str) -> None:
    assert _observe_preset_errors(preset_mod) == _EXP["preset_errors"]


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_layers_only_preset_allows_reserved_names(preset_mod: str) -> None:
    # без catalog_dir имена base/damaged разрешены (в _PRESET_DICTS["layers"] слой "base" и есть)
    sp = _mod(preset_mod).ScenePreset
    assert [layer.name for layer in sp.from_dict(_PRESET_DICTS["layers"]).layers] == ["back", "base"]


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_preset_is_frozen(preset_mod: str) -> None:
    preset = _mod(preset_mod).ScenePreset.from_dict(_PRESET_DICTS["catalog"])
    with pytest.raises(ValidationError):
        preset.catalog_dir = "other"  # type: ignore[misc]


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_resolve_path_relative_absolute_and_id(preset_mod: str, tmp_path: Path) -> None:
    sp = _mod(preset_mod).ScenePreset
    preset = sp.from_dict({"catalog_dir": "c", "base_dir": str(tmp_path)})
    assert preset.resolve_path("sub/x.png") == str(tmp_path / "sub/x.png")
    assert preset.resolve_path("fixture://x") == "fixture://x"
    absolute = str(tmp_path / "abs.png")
    assert preset.resolve_path(absolute) == absolute
    assert sp.from_dict({"catalog_dir": "c"}).resolve_path("sub/x.png") == "sub/x.png"


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a4_from_yaml_sets_base_dir_to_file_dir(preset_mod: str, tmp_path: Path) -> None:
    sp = _mod(preset_mod).ScenePreset
    f = tmp_path / "p.yaml"
    f.write_text('catalog_dir: "classes"\nbase_dir: "/stale"\n', encoding="utf-8")
    preset = sp.from_yaml(f)
    assert preset.catalog_dir == "classes"
    assert Path(preset.base_dir) == tmp_path.resolve()


# ---------------------------------------------------------------------------
# A5. Блок стенда в line_sim.core.preset не сломан
# ---------------------------------------------------------------------------

_OLD_PRESET = "Services.line_sim.core.preset"


def test_a5_repo_root_is_three_levels_above_services_and_has_pyproject() -> None:
    root = _mod(_OLD_PRESET).REPO_ROOT
    assert root == Path(__file__).resolve().parents[3]
    assert (root / "pyproject.toml").is_file()


def test_a5_resolve_repo_path_is_a_str_under_repo_root() -> None:
    m = _mod(_OLD_PRESET)
    got = m.resolve_repo_path("data/x")
    assert isinstance(got, str)
    assert Path(got) == m.REPO_ROOT / "data" / "x"


def test_a5_resolve_repo_path_passes_none_and_absolute_through(tmp_path: Path) -> None:
    m = _mod(_OLD_PRESET)
    assert m.resolve_repo_path(None) is None
    assert m.resolve_repo_path(str(tmp_path)) == str(tmp_path)


def test_a5_resolve_repo_path_sees_repo_root_substituted_on_the_old_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # REPO_ROOT и resolve_repo_path обязаны жить в одном модуле: плагин подменяет REPO_ROOT именно здесь
    monkeypatch.setattr(f"{_OLD_PRESET}.REPO_ROOT", tmp_path)
    got = _mod(_OLD_PRESET).resolve_repo_path("data/x")
    assert Path(got) == (tmp_path / "data" / "x").resolve()


def test_a5_load_scene_preset_for_a_catalog_dir_has_zero_defect_probability(tmp_path: Path) -> None:
    preset = _mod(_OLD_PRESET).load_scene_preset(str(tmp_path), None)
    assert preset.defect_probability == 0.0
    assert preset.catalog_dir == str(tmp_path)


def test_a5_load_scene_preset_explicit_probability_wins(tmp_path: Path) -> None:
    assert _mod(_OLD_PRESET).load_scene_preset(str(tmp_path), 0.4).defect_probability == 0.4


def test_a5_load_scene_preset_none_none_raises_validation_error_with_literal_msg() -> None:
    with pytest.raises(ValidationError) as ei:
        _mod(_OLD_PRESET).load_scene_preset(None, None)
    assert [e["msg"] for e in ei.value.errors()] == _EXP["load_none_none_msgs"]


def test_a5_load_scene_preset_yaml_path_applies_the_override(tmp_path: Path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text("catalog_dir: classes\ndefect_probability: 0.1\n", encoding="utf-8")
    m = _mod(_OLD_PRESET)
    assert m.load_scene_preset(str(f), None).defect_probability == 0.1
    assert m.load_scene_preset(str(f), 0.7).defect_probability == 0.7


def test_a5_apply_defect_override_none_returns_same_and_value_replaces() -> None:
    m = _mod(_OLD_PRESET)
    preset = m.ScenePreset.from_dict(_PRESET_DICTS["catalog"])
    assert m.apply_defect_override(preset, None) is preset
    assert m.apply_defect_override(preset, 0.5).defect_probability == 0.5


@pytest.mark.parametrize("preset_mod", _PRESET_MODULES)
def test_a5_relpath_substitution_through_the_module_path_changes_to_yaml(
    preset_mod: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.path.relpath` подменяют по строке `<модуль>.os.path.relpath` (AttributeError, если `os` из модуля ушёл).
    Эффект: relpath упал `ValueError` (другой диск Windows) -> `to_yaml` откатывается на абсолютный путь."""
    sp = _mod(preset_mod).ScenePreset
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()

    def _raise(_path: str, _start: str) -> str:
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    monkeypatch.setattr(f"{preset_mod}.os.path.relpath", _raise)
    sp.from_dict({"catalog_dir": "sprites", "base_dir": str(a)}).to_yaml(b / "q.yaml")
    written = yaml.safe_load((b / "q.yaml").read_text(encoding="utf-8"))
    assert written["catalog_dir"] == str((a / "sprites").resolve())


# ---------------------------------------------------------------------------
# Границы пакетов: циклический импорт и направление зависимостей (чистые процессы)
# ---------------------------------------------------------------------------


def _run_clean(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("pkg", ["Services.dataset_gen", "Services.line_sim", "Services.layer_render"])
def test_boundary_package_imports_in_a_clean_process(pkg: str) -> None:
    res = _run_clean(f"import {pkg}")
    assert res.returncode == 0, res.stderr[-600:]


def test_boundary_layer_render_package_does_not_pull_dataset_gen_or_line_sim() -> None:
    res = _run_clean(
        "import sys, Services.layer_render\n"
        "bad = sorted(m for m in sys.modules if m.startswith(('Services.dataset_gen', 'Services.line_sim')))\n"
        "print(bad)\nsys.exit(1 if bad else 0)"
    )
    assert res.returncode == 0, res.stdout[-600:] + res.stderr[-600:]


@pytest.mark.parametrize("mod", [_P, _C, _M, _B])
def test_boundary_new_module_imports_first_in_a_clean_process_without_dataset_gen(mod: str) -> None:
    res = _run_clean(
        f"import sys, {mod}\n"
        "bad = sorted(m for m in sys.modules if m.startswith(('Services.dataset_gen', 'Services.line_sim')))\n"
        "print(bad)\nsys.exit(1 if bad else 0)"
    )
    assert res.returncode == 0, res.stdout[-600:] + res.stderr[-600:]


# ---------------------------------------------------------------------------
# A8. Services.layer_render.__all__
# ---------------------------------------------------------------------------

_A8_NAMES: list[tuple[str, str]] = [
    ("ScenePreset", _P),
    ("CLASS_SPRITE_SOURCE", _P),
    ("SpriteCatalog", _C),
    ("ClassEntry", _C),
    ("CatalogConfig", _C),
    ("ClassMeta", _M),
    ("load_meta", _M),
    ("write_meta", _M),
    ("SymmetryType", _M),
    ("procedural_background", _B),
]


@pytest.mark.parametrize("name", [n for n, _ in _A8_NAMES])
def test_a8_name_is_in_all(name: str) -> None:
    assert name in _mod("Services.layer_render").__all__


@pytest.mark.parametrize(("name", "home"), [pytest.param(n, h, id=n) for n, h in _A8_NAMES])
def test_a8_package_attribute_is_the_object_of_its_module(name: str, home: str) -> None:
    assert getattr(_mod("Services.layer_render"), name) is getattr(_mod(home), name)


def test_a8_all_has_no_private_names_and_no_duplicates() -> None:
    names = list(_mod("Services.layer_render").__all__)
    assert [n for n in names if n.startswith("_")] == []
    assert len(names) == len(set(names))
