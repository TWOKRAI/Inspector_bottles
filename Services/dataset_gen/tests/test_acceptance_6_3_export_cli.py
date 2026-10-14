# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 6.3: CLI `Services/dataset_gen/tools/export_sim_crops.py`.

Источник контракта: `plans/layer-render/phase-6-task-6.3.md` — REDS 1-9, ACCEPTANCE 1-5 и DESIGN A как контракт текста
ошибки; `phase-6-task-6.3-context.md` — контракт `ml_train` K1-K6. Worktree на коммите литерала 6.3.0,
до кода CLI: модуля `export_sim_crops` в дереве нет. Не читались: реализация CLI,
hazard-тесты автора, секция `train` боевого пресета.

Как устроен файл.
  * CLI зовётся в процессе через `main([...])`; импорт внутри `_main` — сбор тестов не падает, каждый тест красный сам
    по себе. Один тест (REDS 8) запускает `python -m ...` подпроцессом с `encoding="utf-8"` и сроком 120 с.
  * Данные синтетические: numpy -> PNG во `tmp_path`, пресеты — YAML рядом. Каталог `data/` не читается.
  * Ожидаемые значения — литералы (10 / 4 строки, 128x128, (512, 600), `123.5`);
    ни одно не берётся из кода под тестом.
  * Продукт P: 2 класса `p0`/`p1`, слои `under` (static) + `obj` (`class://`), тайл 40x160 (ширина 40, высота 160).
    Имя `base` не годится: с `catalog_dir` оно зарезервировано. Продукт Q: 2 класса прямоугольников 60x30, `layers: []`.
  * `ml_train` импортируется ВНУТРИ теста после `importorskip("torch")` / `("torchvision")`; форма записи —
    `from Services.<pkg>.<module> import <name>`.

Допущения брифа, которые тест читает по тексту, помечены `# BRIEF-AMBIGUITY:`.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

_ROOT = Path(__file__).resolve().parents[3]
_MODULE = "Services.dataset_gen.tools.export_sim_crops"

_HEADER = [
    "filename",
    "class_index",
    "class_name",
    "class_path",
    "angle_deg",
    "angle_sin",
    "angle_cos",
    "symmetry",
    "angle_valid",
]

# Цвета спрайтов (RGB). Внутренность спрайта после композиции и выреза сохраняет цвет точно.
_P_COLORS = ((220, 30, 30), (30, 60, 220))
_Q_COLORS = ((200, 160, 20), (20, 160, 200))

# --------------------------------------------------------------------------- #
# Фикстуры: спрайты, каталог, пресеты                                          #
# --------------------------------------------------------------------------- #


def _save_rgba(path: Path, rgba: np.ndarray) -> None:
    Image.fromarray(rgba, "RGBA").save(path)


def _p_sprite(index: int) -> np.ndarray:
    """Асимметричный RGBA 64x64: сплошной цвет класса, в одном углу вырез (альфа 0). Класс 0 — вырез слева сверху."""
    rgba = np.zeros((64, 64, 4), dtype=np.uint8)
    rgba[..., :3] = _P_COLORS[index]
    rgba[..., 3] = 255
    if index == 0:
        rgba[:24, :24, 3] = 0
    else:
        rgba[40:, 40:, 3] = 0
    return rgba


def _q_sprite(index: int) -> np.ndarray:
    """Прямоугольник 60 в ширину, 30 в высоту, сплошной цвет класса, альфа 255."""
    rgba = np.zeros((30, 60, 4), dtype=np.uint8)
    rgba[..., :3] = _Q_COLORS[index]
    rgba[..., 3] = 255
    return rgba


def _under_circle() -> np.ndarray:
    """RGBA-круг диаметром 100 px на канве 100x100, серый, вне круга альфа 0."""
    yy, xx = np.mgrid[:100, :100]
    inside = (yy - 49.5) ** 2 + (xx - 49.5) ** 2 <= 50.0**2
    rgba = np.zeros((100, 100, 4), dtype=np.uint8)
    rgba[inside, :3] = (200, 200, 200)
    rgba[inside, 3] = 255
    return rgba


def _tile_40x160() -> np.ndarray:
    """RGBA-тайл: ширина 40, высота 160 (shape (160, 40, 4)); узор зелёных тонов, не совпадает с цветами классов."""
    ys, xs = np.mgrid[:160, :40]
    rgba = np.zeros((160, 40, 4), dtype=np.uint8)
    rgba[..., 0] = 40 + (ys % 8) * 3
    rgba[..., 1] = 100 + (xs % 8) * 5
    rgba[..., 2] = 50
    rgba[..., 3] = 255
    return rgba


def _write_catalog(root: Path, names: tuple[str, ...], sprite) -> None:
    for index, name in enumerate(names):
        (root / "cat" / name).mkdir(parents=True)
        _save_rgba(root / "cat" / name / "0.png", sprite(index))


def _dump(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(path)


def _p_preset_dict() -> dict:
    return {
        "catalog_dir": "cat",
        "angle_range_deg": [0, 360],
        "layers": [
            {"name": "under", "mode": "static", "sprite_source": "under.png"},
            {"name": "obj", "mode": "static", "sprite_source": "class://"},
        ],
        "train": {
            "label": {"angle_layer": "obj"},
            "symmetry": {"auto_detect": False},
            "background_layers": [{"solid": [0, 0, 0]}, {"tile": "tile.png"}],
            "lateral_offset_px": [2, 6],
            "crop": {"size_mode": "radius", "radius_scale": 1.0, "margin_px": 8, "output_size": 128},
        },
    }


def _product_p(root: Path, *, name: str = "p.yaml", catalog: bool = True, side_px: int | None = None) -> str:
    """Продукт P: каталог `cat/{p0,p1}`, `under.png`, `tile.png` и пресет `root/<name>`. Возвращает путь пресета.

    `catalog=False` — тот же пресет без ключа `catalog_dir` (слой `class://` остаётся);
    `side_px` — единственное изменение `train.crop.side_px`.
    """
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "cat").exists():
        _write_catalog(root, ("p0", "p1"), _p_sprite)
        _save_rgba(root / "under.png", _under_circle())
        _save_rgba(root / "tile.png", _tile_40x160())
    data = _p_preset_dict()
    if not catalog:
        del data["catalog_dir"]
    if side_px is not None:
        data["train"]["crop"]["side_px"] = side_px
    return _dump(root / name, data)


def _product_q(root: Path) -> str:
    """Продукт Q: 2 класса прямоугольников 60x30, `layers: []`, угол 123.5, вырез `fixed` 96 -> 96."""
    root.mkdir(parents=True, exist_ok=True)
    _write_catalog(root, ("q0", "q1"), _q_sprite)
    data = {
        "catalog_dir": "cat",
        "angle_range_deg": [123.5, 123.5],
        "layers": [],
        "train": {
            "label": {"angle_layer": None},
            "symmetry": {"auto_detect": False},
            "crop": {"size_mode": "fixed", "side_px": 96, "output_size": 96},
        },
    }
    return _dump(root / "q.yaml", data)


# --------------------------------------------------------------------------- #
# Вызов CLI и чтение результата                                                #
# --------------------------------------------------------------------------- #


def _main(argv: list[str]) -> int:
    from Services.dataset_gen.tools.export_sim_crops import main  # noqa: PLC0415

    return main(argv)


def _export(config: str, out: Path, train: int, val: int, seed: int, *extra: str) -> int:
    argv = [
        "--config",
        config,
        "--out",
        str(out),
        "--train",
        str(train),
        "--val",
        str(val),
        "--seed",
        str(seed),
        *extra,
    ]
    return _main(argv)


def _files(out: Path) -> set[str]:
    return {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} if out.is_dir() else set()


def _hashes(out: Path) -> dict[str, str]:
    return {rel: hashlib.sha256((out / rel).read_bytes()).hexdigest() for rel in sorted(_files(out))}


def _rows(out: Path, split: str) -> list[dict[str, str]]:
    path = out / split / "labels.csv"
    assert path.is_file(), f"нет файла меток {path}"
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _rgb(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"))


def _count_color(frame: np.ndarray, color: tuple[int, int, int]) -> int:
    return int(np.all(frame == np.array(color, dtype=np.uint8), axis=-1).sum())


@pytest.fixture(scope="module")
def p_export(tmp_path_factory) -> Path:
    """Продукт P, `--train 5 --val 2 --seed 0` (ACCEPTANCE 1). Возвращает каталог `--out` (может не существовать)."""
    root = tmp_path_factory.mktemp("p_product")
    config = _product_p(root)
    out = root / "out"
    assert _export(config, out, 5, 2, 0) == 0
    return out


# --------------------------------------------------------------------------- #
# ACCEPTANCE 1: раскладка, число строк, колонки, PNG                           #
# --------------------------------------------------------------------------- #

_P_FILES = (
    {"train/labels.csv", "val/labels.csv"}
    | {f"train/images/{ci:03d}/{i:05d}.png" for ci in (0, 1) for i in (0, 1, 2, 3, 4)}
    | {f"val/images/{ci:03d}/{i:05d}.png" for ci in (0, 1) for i in (0, 1)}
)


def test_layout_and_row_counts(p_export: Path) -> None:
    """Ровно 16 файлов нужной раскладки (без `classes.json`); `train` 10 строк, `val` 4; поля строк `train`."""
    assert len(_P_FILES) == 16  # опечатка в литерале ожидания не должна пройти молча
    assert _files(p_export) == _P_FILES

    train = _rows(p_export, "train")
    val = _rows(p_export, "val")
    assert len(train) == 10
    assert len(val) == 4

    assert [int(r["class_index"]) for r in train] == [0] * 5 + [1] * 5
    assert [r["class_name"] for r in train] == ["p0"] * 5 + ["p1"] * 5
    assert [r["symmetry"] for r in train] == ["none"] * 10
    assert [r["angle_valid"] for r in train] == ["True"] * 10
    # BRIEF-AMBIGUITY: `filename` в ACCEPTANCE не назван; читаю по K3 (путь от каталога сплита) и раскладке ACC 1.
    assert [r["filename"] for r in train] == [f"images/{ci:03d}/{i:05d}.png" for ci in (0, 1) for i in range(5)]
    assert [int(r["class_index"]) for r in val] == [0, 0, 1, 1]
    assert [r["filename"] for r in val] == [f"images/{ci:03d}/{i:05d}.png" for ci in (0, 1) for i in range(2)]
    for r in train:
        assert 0.0 <= float(r["angle_deg"]) < 360.0


def test_png_square_output_size(p_export: Path) -> None:
    """Каждый из 14 PNG читается как `uint8`, `(128, 128, 3)`; кадр не пустой (не однотонный)."""
    pngs = sorted(p for p in p_export.rglob("*.png"))
    assert len(pngs) == 14
    import cv2  # noqa: PLC0415

    for path in pngs:
        data = np.fromfile(str(path), dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        assert frame is not None, path
        assert frame.shape == (128, 128, 3), path
        assert frame.dtype == np.uint8, path
        assert len(np.unique(frame.reshape(-1, 3), axis=0)) > 1, f"однотонный кадр {path}"


def test_labels_columns_and_angle_encoding(p_export: Path) -> None:
    """Заголовок `labels.csv` — ровно девять колонок в порядке брифа; `angle_sin/cos` согласованы с `angle_deg`."""
    for split, count in (("train", 10), ("val", 4)):
        path = p_export / split / "labels.csv"
        assert path.is_file(), path
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == _HEADER
            rows = list(reader)
        assert len(rows) == count
        for r in rows:
            angle = float(r["angle_deg"])
            assert 0.0 <= angle < 360.0
            assert abs(float(r["angle_sin"]) - math.sin(math.radians(angle))) < 1e-9
            assert abs(float(r["angle_cos"]) - math.cos(math.radians(angle))) < 1e-9


def test_images_match_class_labels(p_export: Path) -> None:
    """Кадр в `images/<ci>/` несёт цвет спрайта класса `ci` и не несёт цвет другого класса (метка не путает кадр)."""
    checked = 0
    for split in ("train", "val"):
        for row in _rows(p_export, split):
            ci = int(row["class_index"])
            frame = _rgb(p_export / split / row["filename"])
            assert _count_color(frame, _P_COLORS[ci]) >= 300, (split, row["filename"])
            assert _count_color(frame, _P_COLORS[1 - ci]) == 0, (split, row["filename"])
            checked += 1
    assert checked == 14


# --------------------------------------------------------------------------- #
# ACCEPTANCE 2: ml_train читает каталог без правок                             #
# --------------------------------------------------------------------------- #


def test_ml_train_loader_batch(p_export: Path, tmp_path: Path) -> None:
    """`build_dataloaders` с `source: exported`: формы, типы, классы, симметрия; тот же смоук на продукте Q (PNG 96)."""
    pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    import torch  # noqa: PLC0415

    from Services.ml_train.config import DataConfig  # noqa: PLC0415
    from Services.ml_train.data import build_dataloaders  # noqa: PLC0415

    assert (p_export / "train").is_dir(), "экспорт P не создал каталог train"
    config = DataConfig(
        source="exported",
        root=str(p_export),
        image_size=(128, 128),
        batch_size=4,
        num_workers=0,
        augment={"enabled": False},
    )
    bundle = build_dataloaders(config)

    images, target = next(iter(bundle.train_loader))
    assert tuple(images.shape) == (4, 3, 128, 128)
    assert images.dtype == torch.float32
    assert tuple(target["class_index"].shape) == (4,)
    assert target["class_index"].dtype == torch.int64
    assert set(target["class_index"].tolist()) <= {0, 1}
    assert tuple(target["angle"].shape) == (4, 2)
    assert target["angle"].dtype == torch.float32
    assert tuple(target["angle_valid"].shape) == (4,)
    assert target["angle_valid"].dtype == torch.bool
    assert bool(target["angle_valid"].all())

    val_images, _ = next(iter(bundle.val_loader))
    assert tuple(val_images.shape) == (4, 3, 128, 128)
    assert bundle.class_names == ["p0", "p1"]
    assert bundle.symmetry_map == {"p0": "none", "p1": "none"}

    # Продукт Q: PNG 96x96, `ml_train` приводит к 128x128 сам.
    q_out = tmp_path / "q_out"
    assert _export(_product_q(tmp_path / "q"), q_out, 3, 1, 0) == 0
    assert (q_out / "train").is_dir(), "экспорт Q не создал каталог train"
    q_bundle = build_dataloaders(
        DataConfig(
            source="exported",
            root=str(q_out),
            batch_size=2,
            num_workers=0,
            augment={"enabled": False},
        )
    )
    q_images, q_target = next(iter(q_bundle.train_loader))
    assert tuple(q_images.shape) == (2, 3, 128, 128)
    assert tuple(q_target["angle"].shape) == (2, 2)
    assert q_bundle.class_names == ["q0", "q1"]


# --------------------------------------------------------------------------- #
# ACCEPTANCE 3: seed                                                           #
# --------------------------------------------------------------------------- #


def test_same_seed_same_bytes(tmp_path: Path) -> None:
    """Два прогона `--seed 7` дают побайтно равные каталоги (16 файлов); `--seed 8` меняет хотя бы один PNG."""
    config = _product_p(tmp_path / "prod")
    out1, out2, out8 = tmp_path / "o1", tmp_path / "o2", tmp_path / "o8"
    assert _export(config, out1, 5, 2, 7) == 0
    assert _export(config, out2, 5, 2, 7) == 0
    assert _export(config, out8, 5, 2, 8) == 0

    h1, h2, h8 = _hashes(out1), _hashes(out2), _hashes(out8)
    assert len(h1) == 16
    assert h1 == h2
    assert set(h8) == set(h1), "--seed 8: другая раскладка файлов"
    assert any(h8[rel] != h1[rel] for rel in h1 if rel.endswith(".png")), "другой seed дал те же PNG"


# --------------------------------------------------------------------------- #
# ACCEPTANCE 4: второй продукт без кода                                        #
# --------------------------------------------------------------------------- #


def test_second_product_zero_code(tmp_path: Path) -> None:
    """Тот же `main` на продукте Q: `train` 6 строк, `val` 2, PNG (96, 96, 3), угол 123.5 везде."""
    out = tmp_path / "q_out"
    assert _export(_product_q(tmp_path / "q"), out, 3, 1, 0) == 0

    train = _rows(out, "train")
    val = _rows(out, "val")
    assert len(train) == 6
    assert len(val) == 2
    assert [int(r["class_index"]) for r in train] == [0, 0, 0, 1, 1, 1]
    assert [r["class_name"] for r in train] == ["q0"] * 3 + ["q1"] * 3
    for split, rows in (("train", train), ("val", val)):
        for r in rows:
            assert float(r["angle_deg"]) == pytest.approx(123.5)
            frame = _rgb(out / split / r["filename"])
            assert frame.shape == (96, 96, 3)
            # Объект в центре выреза: центральный пиксель — цвет спрайта своего класса.
            assert tuple(int(v) for v in frame[48, 48]) == _Q_COLORS[int(r["class_index"])]
    assert len(_files(out)) == 2 + 6 + 2


# --------------------------------------------------------------------------- #
# ACCEPTANCE 5: превью и ошибки                                                #
# --------------------------------------------------------------------------- #


def test_preview_grid(tmp_path: Path) -> None:
    """`--preview <каталог>/sub/grid.png`: файл создан (вместе с `sub`), размер `(512, 600)`; экспорт на месте."""
    config = _product_p(tmp_path / "prod")
    out = tmp_path / "out"
    preview = tmp_path / "pv" / "sub" / "grid.png"
    assert _export(config, out, 2, 1, 0, "--preview", str(preview)) == 0

    assert preview.is_file(), "сетка-превью не создана"
    with Image.open(preview) as img:
        assert img.size == (512, 600)  # 4 колонки x 128; 4 строки x (128 + 22)
    assert (out / "train").is_dir()
    assert (out / "val").is_dir()


def _bad_config(case: str, root: Path) -> str:
    if case == "missing":
        return str(root / "no_such_preset.yaml")
    if case == "invalid_train":
        return _product_p(root, side_px=1)
    if case == "no_catalog":
        return _product_p(root, catalog=False)
    if case == "broken_yaml":
        path = root / "broken.yaml"
        path.write_text("a: [1", encoding="utf-8")
        return str(path)
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["missing", "invalid_train", "no_catalog", "broken_yaml"])
def test_bad_config_systemexit_with_path(case: str, tmp_path: Path) -> None:
    """Плохой `--config`: `SystemExit` со строкой `<путь>: <Тип>: <причина>`; `--out` не создан."""
    root = tmp_path / "prod"
    root.mkdir()
    config = _bad_config(case, root)
    out = tmp_path / "out"

    with pytest.raises(SystemExit) as info:
        _export(config, out, 1, 1, 0)

    code = info.value.code
    assert isinstance(code, str), f"код выхода не строка: {code!r}"
    assert code.startswith(f"{config}: "), code
    # BRIEF-AMBIGUITY: ACC 5 требует только префикс `<путь>: `; формат `<путь>: <тип>: <причина>` беру из DESIGN A и E3.
    assert re.match(re.escape(f"{config}: ") + r"[A-Za-z_][A-Za-z0-9_.]*: \S", code), code
    assert not out.exists(), "при ошибке конфига `--out` не должен создаваться"

    if case == "missing":
        assert "FileNotFoundError" in code
    elif case == "invalid_train":
        assert "ValidationError" in code
        assert "crop.side_px" in code
    elif case == "no_catalog":
        assert "ValidationError" in code
        assert "input_value" not in code


def test_module_entry_bad_config(tmp_path: Path) -> None:
    """`python -m ...` подпроцессом на несуществующем конфиге: код 1, в stderr `<путь>: FileNotFoundError:`."""
    config = str(tmp_path / "no_such_preset.yaml")
    out = tmp_path / "out"
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", _MODULE, "--config", config, "--out", str(out), "--train", "1", "--val", "1"],
        capture_output=True,
        encoding="utf-8",
        cwd=str(_ROOT),
        env=env,
        timeout=120,
    )
    assert proc.returncode == 1, (proc.returncode, proc.stderr)
    assert f"{config}: FileNotFoundError:" in proc.stderr, proc.stderr
    assert not out.exists()
