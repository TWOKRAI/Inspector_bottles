"""Источники данных: exported (формат dataset_gen) и folder. Требует torch."""

import csv

import numpy as np
import pytest

torch = pytest.importorskip("torch")
cv2 = pytest.importorskip("cv2")

from Services.ml_train.config import DataConfig  # noqa: E402
from Services.ml_train.data import (  # noqa: E402
    ExportedDataset,
    FolderDataset,
    build_dataloaders,
)

_LABEL_FIELDS = (
    "filename",
    "class_index",
    "class_name",
    "class_path",
    "angle_deg",
    "angle_sin",
    "angle_cos",
    "symmetry",
    "angle_valid",
)


def _write_img(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.full((32, 32, 3), color, dtype=np.uint8)
    assert cv2.imwrite(str(path), img)


def _make_exported(root, n_per_class=4, num_classes=2):
    rows = []
    for ci in range(num_classes):
        for i in range(n_per_class):
            rel = f"images/{ci:03d}/{i:05d}.png"
            _write_img(root / rel, color=40 * (ci + 1))
            rows.append(
                {
                    "filename": rel,
                    "class_index": ci,
                    "class_name": f"cls_{ci}",
                    "class_path": f"cls_{ci}",
                    "angle_deg": 90.0 * i,
                    "angle_sin": float(np.sin(np.radians(90.0 * i))),
                    "angle_cos": float(np.cos(np.radians(90.0 * i))),
                    "symmetry": "none",
                    "angle_valid": True,
                }
            )
    root.mkdir(parents=True, exist_ok=True)
    with (root / "labels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_LABEL_FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_exported_dataset_sample_contract(tmp_path):
    _make_exported(tmp_path / "ds")
    ds = ExportedDataset(tmp_path / "ds")
    image, target = ds[0]
    assert image.shape == (3, 32, 32) and image.dtype == torch.float32
    assert target["class_index"].item() == 0
    assert target["angle"].shape == (2,)
    assert bool(target["angle_valid"]) is True
    # csv хранит bool строкой — проверяем парсинг False
    ds.rows[0]["angle_valid"] = "False"
    _, target2 = ds[0]
    assert bool(target2["angle_valid"]) is False


def test_folder_dataset(tmp_path):
    for name, color in [("Bad", 30), ("Good", 120), ("Neutral", 200)]:
        for i in range(3):
            _write_img(tmp_path / "f" / name / "nested" / f"{i}.png", color)
    ds = FolderDataset(tmp_path / "f")
    assert ds.class_names == ["Bad", "Good", "Neutral"]  # сортировка по имени
    assert len(ds) == 9
    image, target = ds[0]
    assert image.shape == (3, 32, 32)
    assert bool(target["angle_valid"]) is False


def test_build_dataloaders_exported_with_splits(tmp_path):
    root = tmp_path / "ds"
    _make_exported(root / "train", n_per_class=6)
    _make_exported(root / "val", n_per_class=2)
    _make_exported(root / "test", n_per_class=2)
    cfg = DataConfig(source="exported", root=str(root), image_size=(24, 24), batch_size=4)
    bundle = build_dataloaders(cfg)
    assert bundle.class_names == ["cls_0", "cls_1"]
    assert bundle.test_loader is not None
    images, target = next(iter(bundle.train_loader))
    assert images.shape == (4, 3, 24, 24)  # resize к image_size
    assert set(target) == {"class_index", "angle", "angle_valid"}
    # сбалансированный датасет → веса ~1
    assert torch.allclose(bundle.class_weights, torch.ones(2), atol=1e-6)


def test_build_dataloaders_folder_split(tmp_path):
    for name in ("a", "b"):
        for i in range(10):
            _write_img(tmp_path / "f" / name / f"{i}.png", 50)
    cfg = DataConfig(
        source="folder", root=str(tmp_path / "f"), image_size=(16, 16), batch_size=2, val_split=0.2, seed=1
    )
    bundle = build_dataloaders(cfg)
    n_train = len(bundle.train_loader.dataset)
    n_val = len(bundle.val_loader.dataset)
    assert n_train + n_val == 20 and n_val == 4
    assert bundle.image_size == (16, 16)


def test_folder_imbalance_weights(tmp_path):
    for i in range(8):
        _write_img(tmp_path / "f" / "many" / f"{i}.png", 50)
    for i in range(2):
        _write_img(tmp_path / "f" / "few" / f"{i}.png", 50)
    cfg = DataConfig(source="folder", root=str(tmp_path / "f"), image_size=(16, 16))
    bundle = build_dataloaders(cfg)
    # few (индекс 0 по сортировке) реже → вес больше
    w = bundle.class_weights
    assert w[bundle.class_names.index("few")] > w[bundle.class_names.index("many")]
