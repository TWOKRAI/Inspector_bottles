"""Контракт torch-адаптера (пропускается, если torch не установлен)."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from Services.dataset_gen import SyntheticDataset  # noqa: E402
from Services.dataset_gen.core.engine import DatasetEngine  # noqa: E402


@pytest.fixture
def dataset(base_config):
    return SyntheticDataset(DatasetEngine(base_config), length=12, seed=7)


class TestSyntheticDataset:
    def test_len_default_from_config(self, base_config):
        ds = SyntheticDataset(DatasetEngine(base_config))
        # frames_per_class=4 × 3 класса
        assert len(ds) == 12

    def test_item_shapes_and_types(self, dataset):
        image, target = dataset[0]
        assert image.shape == (3, 96, 96)
        assert image.dtype == torch.float32
        assert 0.0 <= float(image.min()) and float(image.max()) <= 1.0
        assert target["class_index"].dtype == torch.long
        assert tuple(target["angle"].shape) == (2,)
        assert target["angle_valid"].dtype == torch.bool

    def test_classes_balanced_round_robin(self, dataset):
        classes = [int(dataset[i][1]["class_index"]) for i in range(6)]
        assert classes == [0, 1, 2, 0, 1, 2]

    def test_deterministic_by_index(self, base_config):
        ds1 = SyntheticDataset(DatasetEngine(base_config), length=4, seed=7)
        ds2 = SyntheticDataset(DatasetEngine(base_config), length=4, seed=7)
        assert torch.equal(ds1[2][0], ds2[2][0])

    def test_dataloader_collates(self, dataset):
        loader = torch.utils.data.DataLoader(dataset, batch_size=4)
        images, targets = next(iter(loader))
        assert images.shape == (4, 3, 96, 96)
        assert targets["angle"].shape == (4, 2)
