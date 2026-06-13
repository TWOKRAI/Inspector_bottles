"""Источники данных и DataLoader'ы.

Три источника (config.data.source):
- synthetic — генерация на лету через Services.dataset_gen (SyntheticDataset);
- exported  — датасет, сохранённый export_dataset/export_splits
              (images/{class:03d}/ + labels.csv|json);
- folder    — подпапки-классы с картинками (формат старого keras-кода:
              Good/Bad/Neutral), вложенные подпапки допустимы.

Единый контракт сэмпла: (image CHW float32 normalized, target-dict
{class_index: long, angle: float32[2] (sin, cos), angle_valid: bool}).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Subset

from Services.ml_train.config import DataConfig

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass
class DataBundle:
    """Всё, что нужно трейнеру от данных."""

    train_loader: DataLoader
    val_loader: DataLoader
    test_loader: DataLoader | None
    class_names: list[str]
    class_weights: torch.Tensor | None  # None при class_weights=none
    image_size: tuple[int, int]  # фактический (H, W) сэмпла — для ONNX sidecar
    #: симметрия класса для декода угла в инференсе {class_name: none|180|full};
    #: None для folder-источника (нет меток угла). Уходит в checkpoint → sidecar.
    symmetry_map: dict[str, str] | None = None


def _imread_unicode(path: Path) -> np.ndarray:
    """cv2.imread не умеет non-ASCII пути на Windows → decode из байтов."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f"Не удалось прочитать изображение: {path}")
    return img


def _make_target(class_index: int, angle_sin: float, angle_cos: float, angle_valid: bool) -> dict[str, torch.Tensor]:
    return {
        "class_index": torch.tensor(class_index, dtype=torch.long),
        "angle": torch.tensor([angle_sin, angle_cos], dtype=torch.float32),
        "angle_valid": torch.tensor(angle_valid, dtype=torch.bool),
    }


class ExportedDataset(Dataset):
    """Набор, сохранённый dataset_gen export_dataset (один сплит).

    Pre: в split_dir лежит labels.csv или labels.json.
    """

    def __init__(self, split_dir: str | Path, transform=None) -> None:
        self.root = Path(split_dir)
        self.transform = transform
        self.rows = _read_label_rows(self.root)
        if not self.rows:
            raise ValueError(f"Пустой датасет: {self.root}")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        row = self.rows[idx]
        bgr = _imread_unicode(self.root / row["filename"])
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
        if self.transform is not None:
            image = self.transform(image)
        target = _make_target(
            int(row["class_index"]),
            float(row["angle_sin"]),
            float(row["angle_cos"]),
            _as_bool(row["angle_valid"]),
        )
        return image, target


class FolderDataset(Dataset):
    """Подпапки-классы (Good/Bad/Neutral, ...); метки угла отсутствуют (angle_valid=False).

    Классы — отсортированные имена подпапок первого уровня; картинки внутри
    класса собираются рекурсивно (вложенность как в исходных съёмках допустима).
    """

    def __init__(self, root: str | Path, transform=None) -> None:
        self.root = Path(root)
        self.transform = transform
        class_dirs = sorted(d for d in self.root.iterdir() if d.is_dir() and not d.name.startswith((".", "_")))
        if not class_dirs:
            raise ValueError(f"Нет подпапок-классов в {self.root}")
        self.class_names = [d.name for d in class_dirs]
        self.samples: list[tuple[Path, int]] = []
        for class_index, class_dir in enumerate(class_dirs):
            files = sorted(p for p in class_dir.rglob("*") if p.suffix.lower() in _IMAGE_SUFFIXES)
            self.samples.extend((p, class_index) for p in files)
        if not self.samples:
            raise ValueError(f"Не найдено изображений в {self.root}")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        path, class_index = self.samples[idx]
        rgb = cv2.cvtColor(_imread_unicode(path), cv2.COLOR_BGR2RGB)
        image = torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
        if self.transform is not None:
            image = self.transform(image)
        return image, _make_target(class_index, 0.0, 0.0, False)


# ---------------------------------------------------------------------- #
# Трансформы
# ---------------------------------------------------------------------- #


def build_transforms(config: DataConfig, train: bool, resize: bool) -> Any:
    """Пайплайн на тензорах CHW float [0..1]: resize → аугментации → normalize.

    resize=False для синтетики (движок сам задаёт размер кадра).
    """
    from torchvision.transforms import v2

    ops: list[Any] = []
    if resize:
        ops.append(v2.Resize(list(config.image_size), antialias=True))
    aug = config.augment
    if train and aug.enabled:
        if aug.hflip:
            ops.append(v2.RandomHorizontalFlip(p=0.5))
        if aug.rotation_deg > 0:
            ops.append(v2.RandomRotation(aug.rotation_deg))
        if aug.color_jitter > 0:
            j = aug.color_jitter
            ops.append(v2.ColorJitter(brightness=j, contrast=j, saturation=j))
    ops.append(v2.Normalize(mean=list(config.normalize.mean), std=list(config.normalize.std)))
    if train and aug.enabled and aug.random_erasing > 0:
        ops.append(v2.RandomErasing(p=aug.random_erasing))
    return v2.Compose(ops)


# ---------------------------------------------------------------------- #
# Сборка DataLoader'ов
# ---------------------------------------------------------------------- #


def build_dataloaders(config: DataConfig) -> DataBundle:
    """Собрать train/val(/test) DataLoader'ы по конфигу данных.

    Post: class_names согласованы с class_index во всех сплитах;
          class_weights — сбалансированные веса (auto) либо None.
    """
    if config.source == "synthetic":
        bundle = _build_synthetic(config)
    elif config.source == "exported":
        bundle = _build_exported(config)
    else:
        bundle = _build_folder(config)
    return bundle


def _loader(dataset: Dataset, config: DataConfig, shuffle: bool) -> DataLoader:
    # train (shuffle=True): неполный последний батч отбрасываем — батч размера 1
    # ломает BatchNorm в режиме train; val/test — оставляем всё
    n = len(dataset)  # type: ignore[arg-type]
    drop_last = shuffle and n > config.batch_size
    return DataLoader(
        dataset,
        batch_size=config.batch_size,
        shuffle=shuffle,
        num_workers=config.num_workers,
        pin_memory=torch.cuda.is_available(),
        persistent_workers=config.num_workers > 0,
        drop_last=drop_last,
    )


def _probe_image_size(dataset: Dataset) -> tuple[int, int]:
    image, _ = dataset[0]
    return int(image.shape[1]), int(image.shape[2])


def _build_synthetic(config: DataConfig) -> DataBundle:
    from Services.dataset_gen import DatasetEngine

    engine = DatasetEngine.from_yaml(str(config.generator_preset))
    return bundle_from_generator(engine, config)


def bundle_from_generator(generator, config: DataConfig) -> DataBundle:
    """DataBundle поверх любого SampleGenerator (контракт dataset_gen.interfaces).

    Выделено из _build_synthetic: в тестах подставляется stub-генератор
    без YAML-пресета и реальных спрайтов.
    """
    from Services.dataset_gen import SyntheticDataset

    train_tf = build_transforms(config, train=True, resize=False)
    eval_tf = build_transforms(config, train=False, resize=False)
    # независимые сиды → независимые потоки случайности train/val (без утечки)
    train_ds = SyntheticDataset(generator, length=config.samples_per_epoch, seed=config.seed, transform=train_tf)
    val_ds = SyntheticDataset(generator, length=config.val_samples, seed=config.seed + 1, transform=eval_tf)
    class_names = list(generator.class_names)
    counts = _synthetic_counts(len(train_ds), len(class_names))
    sym = getattr(generator, "symmetry_map", None)
    return DataBundle(
        train_loader=_loader(train_ds, config, shuffle=True),
        val_loader=_loader(val_ds, config, shuffle=False),
        test_loader=None,
        class_names=class_names,
        class_weights=_balanced_weights(counts),
        image_size=_probe_image_size(val_ds),
        symmetry_map={k: str(v) for k, v in sym.items()} if sym else None,
    )


def _synthetic_counts(length: int, num_classes: int) -> np.ndarray:
    """SyntheticDataset чередует классы (idx % C) — счётчики почти равные."""
    base = length // num_classes
    counts = np.full(num_classes, base, dtype=np.int64)
    counts[: length % num_classes] += 1
    return counts


def _build_exported(config: DataConfig) -> DataBundle:
    root = Path(str(config.root))
    train_tf = build_transforms(config, train=True, resize=True)
    eval_tf = build_transforms(config, train=False, resize=True)

    if (root / "train").is_dir():
        train_ds = ExportedDataset(root / "train", transform=train_tf)
        if (root / "val").is_dir():
            val_ds: Dataset = ExportedDataset(root / "val", transform=eval_tf)
        else:
            train_ds, val_ds = _random_split_two_views(
                ExportedDataset(root / "train", transform=train_tf),
                ExportedDataset(root / "train", transform=eval_tf),
                config.val_split,
                config.seed,
            )
        test_ds = ExportedDataset(root / "test", transform=eval_tf) if (root / "test").is_dir() else None
        label_rows = _read_label_rows(root / "train")
    else:
        train_ds, val_ds = _random_split_two_views(
            ExportedDataset(root, transform=train_tf),
            ExportedDataset(root, transform=eval_tf),
            config.val_split,
            config.seed,
        )
        test_ds = None
        label_rows = _read_label_rows(root)

    class_names = _class_names_from_rows(label_rows)
    counts = _counts_from_rows(label_rows, len(class_names))
    # рассинхрон сплитов (экспорт с разными каталогами) ловим здесь с внятной
    # ошибкой — иначе IndexError в confusion_matrix посреди валидации
    for split_name, ds in (("val", val_ds), ("test", test_ds)):
        if isinstance(ds, ExportedDataset):
            _check_class_bounds(ds.rows, len(class_names), split_name)
    return DataBundle(
        train_loader=_loader(train_ds, config, shuffle=True),
        val_loader=_loader(val_ds, config, shuffle=False),
        test_loader=_loader(test_ds, config, shuffle=False) if test_ds is not None else None,
        class_names=class_names,
        class_weights=_balanced_weights(counts),
        image_size=tuple(config.image_size),
        symmetry_map=_symmetry_from_rows(label_rows),
    )


def _build_folder(config: DataConfig) -> DataBundle:
    root = Path(str(config.root))
    full_train = FolderDataset(root, transform=build_transforms(config, train=True, resize=True))
    full_eval = FolderDataset(root, transform=build_transforms(config, train=False, resize=True))
    train_ds, val_ds = _random_split_two_views(full_train, full_eval, config.val_split, config.seed)
    counts = np.bincount(
        [class_index for _, class_index in full_train.samples],
        minlength=len(full_train.class_names),
    )
    return DataBundle(
        train_loader=_loader(train_ds, config, shuffle=True),
        val_loader=_loader(val_ds, config, shuffle=False),
        test_loader=None,
        class_names=full_train.class_names,
        class_weights=_balanced_weights(counts),
        image_size=tuple(config.image_size),
    )


def _random_split_two_views(
    train_view: Dataset,
    eval_view: Dataset,
    val_split: float,
    seed: int,
) -> tuple[Dataset, Dataset]:
    """Разбить индексы на train/val поверх ДВУХ инстансов датасета.

    Два инстанса нужны, потому что transform у train (аугментации) и val
    (только resize+normalize) различается, а файлы — одни и те же.
    """
    n = len(train_view)  # type: ignore[arg-type]
    indices = np.random.default_rng(seed).permutation(n)
    n_val = max(1, int(n * val_split))
    # train-сплит < 2 сэмплов: единственный батч размера 1 уронит BatchNorm
    if n - n_val < 2:
        raise ValueError(f"Слишком мало данных ({n}) для val_split={val_split}: train-сплит < 2 сэмплов")
    return Subset(train_view, indices[n_val:].tolist()), Subset(eval_view, indices[:n_val].tolist())


# ---------------------------------------------------------------------- #
# Метки exported-формата
# ---------------------------------------------------------------------- #


def _read_label_rows(split_dir: Path) -> list[dict[str, Any]]:
    """Прочитать labels.csv | labels.json (формат dataset_gen export)."""
    csv_path = split_dir / "labels.csv"
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    json_path = split_dir / "labels.json"
    if json_path.is_file():
        return json.loads(json_path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Не найден labels.csv/labels.json в {split_dir}")


def _as_bool(value: Any) -> bool:
    """csv хранит bool строкой ('True'/'False'), json — нативно."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _check_class_bounds(rows: list[dict[str, Any]], num_classes: int, split_name: str) -> None:
    """Pre-условие согласованности сплитов: class_index < числа классов train."""
    max_index = max(int(r["class_index"]) for r in rows)
    if max_index >= num_classes:
        raise ValueError(
            f"Сплит '{split_name}' содержит class_index={max_index}, а в train классов {num_classes} — "
            f"сплиты экспортированы с разными каталогами классов"
        )


def _symmetry_from_rows(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    """Симметрия класса из колонки symmetry меток (exported dataset_gen)."""
    m: dict[str, str] = {}
    for r in rows:
        if r.get("symmetry"):
            m[str(r["class_name"])] = str(r["symmetry"])
    return m or None


def _class_names_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    by_index: dict[int, str] = {}
    for row in rows:
        by_index[int(row["class_index"])] = str(row["class_name"])
    num_classes = max(by_index) + 1
    return [by_index.get(i, f"class_{i}") for i in range(num_classes)]


def _counts_from_rows(rows: list[dict[str, Any]], num_classes: int) -> np.ndarray:
    return np.bincount([int(r["class_index"]) for r in rows], minlength=num_classes)


def _balanced_weights(counts: np.ndarray) -> torch.Tensor:
    """Веса классов total / (C * count) — компенсация дисбаланса (как в старом keras-коде)."""
    counts = np.maximum(np.asarray(counts, dtype=np.float64), 1.0)
    weights = counts.sum() / (len(counts) * counts)
    return torch.tensor(weights, dtype=torch.float32)
