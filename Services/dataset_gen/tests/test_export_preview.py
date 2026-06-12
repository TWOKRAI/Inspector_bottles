"""Контракт export/preview: файлы на диске, метки, QC-сетка."""

from __future__ import annotations

import csv
import json

import pytest
from PIL import Image

from Services.dataset_gen.core.engine import DatasetEngine
from Services.dataset_gen.export import export_dataset
from Services.dataset_gen.preview import save_preview_grid


class TestExportCsv:
    def test_images_and_labels_written(self, base_config, tmp_path):
        engine = DatasetEngine(base_config)
        out = tmp_path / "dataset"

        labels_path = export_dataset(engine, out, frames_per_class=2)

        with labels_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # 3 класса × 2 кадра, каждая строка ссылается на существующий файл
        assert len(rows) == 6
        for row in rows:
            assert (out / row["filename"]).is_file()
            assert row["class_name"] in {"bar", "disk", "lshape"}
            assert 0.0 <= float(row["angle_deg"]) < 360.0

    def test_progress_callback_called(self, base_config, tmp_path):
        engine = DatasetEngine(base_config)
        calls: list[tuple[int, int]] = []
        export_dataset(
            engine,
            tmp_path / "ds",
            frames_per_class=1,
            progress_cb=lambda done, total: calls.append((done, total)),
        )
        assert calls[-1] == (3, 3)


class TestExportSplits:
    def test_three_splits_with_own_labels(self, base_config, tmp_path):
        from Services.dataset_gen.export import export_splits

        engine = DatasetEngine(base_config)
        result = export_splits(engine, tmp_path / "ds", splits={"train": 2, "val": 1, "test": 1}, seed=5)

        assert set(result) == {"train", "val", "test"}
        with result["train"].open(encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 6  # 3 класса × 2
        with result["val"].open(encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == 3

    def test_splits_differ_between_each_other(self, base_config, tmp_path):
        from Services.dataset_gen.export import export_splits

        engine = DatasetEngine(base_config)
        result = export_splits(engine, tmp_path / "ds", splits={"train": 1, "val": 1}, seed=5)
        img_train = (result["train"].parent / "images/000/00000.png").read_bytes()
        img_val = (result["val"].parent / "images/000/00000.png").read_bytes()
        assert img_train != img_val  # разные rng → нет дубликатов между сплитами

    def test_split_data_stable_under_key_reorder(self, base_config, tmp_path):
        # детерминизм привязан к ИМЕНИ сплита, не к позиции в dict:
        # перестановка ключей не меняет данные train
        from Services.dataset_gen.export import export_splits

        engine = DatasetEngine(base_config)
        r1 = export_splits(engine, tmp_path / "a", splits={"train": 1, "val": 1}, seed=5)
        r2 = export_splits(engine, tmp_path / "b", splits={"val": 1, "train": 1}, seed=5)
        train1 = (r1["train"].parent / "images/000/00000.png").read_bytes()
        train2 = (r2["train"].parent / "images/000/00000.png").read_bytes()
        assert train1 == train2


class TestExportParquet:
    def test_parquet_labels_roundtrip(self, base_config, tmp_path):
        pytest.importorskip("pyarrow")
        import pyarrow.parquet as pq

        engine = DatasetEngine(base_config)
        labels_path = export_dataset(engine, tmp_path / "ds", frames_per_class=2, labels_format="parquet")
        table = pq.read_table(labels_path)
        assert table.num_rows == 6  # 3 класса × 2
        assert {"filename", "class_index", "angle_sin", "angle_valid"} <= set(table.column_names)


class TestExportJson:
    def test_json_labels_parse(self, base_config, tmp_path):
        engine = DatasetEngine(base_config)
        labels_path = export_dataset(engine, tmp_path / "ds", frames_per_class=1, labels_format="json")
        rows = json.loads(labels_path.read_text(encoding="utf-8"))
        assert len(rows) == 3
        assert {"filename", "class_index", "angle_sin", "angle_valid"} <= set(rows[0])


class TestPreviewGrid:
    def test_grid_saved_with_expected_size(self, base_config, tmp_path):
        engine = DatasetEngine(base_config)
        path = save_preview_grid(engine, tmp_path / "grid.png", n=6, cols=3)

        img = Image.open(path)
        # 3 колонки × 96px, 2 ряда × (96 + caption)
        assert img.width == 3 * 96
        assert img.height == 2 * (96 + 22)
