"""Режим вывода №1: сохранение датасета на диск (изображения + файл меток).

Структура выхода:
    out_dir/
    ├── images/
    │   ├── 000/00000.png ...   # подкаталог на класс (индекс), кадры внутри
    │   └── 001/...
    └── labels.csv | labels.json | labels.parquet

В файле меток поле filename — путь относительно out_dir (POSIX-слэши).
parquet требует pandas+pyarrow (опционально); csv/json — stdlib.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Literal

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.dataset_gen.interfaces import SampleGenerator

LabelsFormat = Literal["csv", "json", "parquet"]

_LABEL_FIELDS = (
    "filename",
    "class_index",
    "class_name",
    "angle_deg",
    "angle_sin",
    "angle_cos",
    "symmetry",
    "angle_valid",
)


def export_dataset(
    generator: SampleGenerator,
    out_dir: str | Path,
    frames_per_class: int,
    image_format: str = "png",
    labels_format: LabelsFormat = "csv",
    rng: np.random.Generator | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """Сгенерировать и сохранить датасет на диск.

    Pre:
      - frames_per_class ≥ 1; labels_format ∈ {csv, json, parquet}
    Post:
      - создано frames_per_class * num_classes изображений;
        файл меток содержит по строке на изображение;
        возвращён путь к файлу меток

    progress_cb(done, total) — опциональный колбэк прогресса.
    """
    out = Path(out_dir)
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    total = frames_per_class * generator.num_classes
    rows: list[dict[str, Any]] = []
    done = 0
    for class_index in range(generator.num_classes):
        class_dir = images_dir / f"{class_index:03d}"
        class_dir.mkdir(exist_ok=True)
        for i in range(frames_per_class):
            frame, label = generator.generate_sample(class_index, rng)
            rel = f"images/{class_index:03d}/{i:05d}.{image_format}"
            imwrite_unicode(out / rel, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            rows.append({"filename": rel, **label.to_dict()})
            done += 1
            if progress_cb is not None:
                progress_cb(done, total)

    return _write_labels(out, rows, labels_format)


def _write_labels(out: Path, rows: list[dict[str, Any]], fmt: LabelsFormat) -> Path:
    if fmt == "csv":
        path = out / "labels.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_LABEL_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path
    if fmt == "json":
        path = out / "labels.json"
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    if fmt == "parquet":
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - зависит от окружения
            raise ImportError(
                "labels_format='parquet' требует pandas + pyarrow: "
                "pip install pandas pyarrow (или используйте csv/json)"
            ) from exc
        path = out / "labels.parquet"
        pd.DataFrame(rows).to_parquet(path, index=False)
        return path
    raise ValueError(f"Неизвестный формат меток: {fmt}")
