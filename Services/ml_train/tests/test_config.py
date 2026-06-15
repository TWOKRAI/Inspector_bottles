"""Контракт TrainConfig: from_yaml/from_dict/to_dict, дефолты, кросс-валидация.

Работает без torch (конфиги доступны в любом окружении).
"""

import pytest
from pydantic import ValidationError

from Services.ml_train.config import TrainConfig


def test_defaults_synthetic_requires_preset():
    with pytest.raises(ValidationError, match="generator_preset"):
        TrainConfig.from_dict({"data": {"source": "synthetic"}})


def test_exported_requires_root():
    with pytest.raises(ValidationError, match="root"):
        TrainConfig.from_dict({"data": {"source": "exported"}})


def test_minimal_valid_and_defaults():
    cfg = TrainConfig.from_dict({"data": {"source": "folder", "root": "data/x"}})
    assert cfg.model.arch == "mobilenet_v3_large"
    assert cfg.optim.scheduler == "cosine"
    assert cfg.train.monitor == "balanced_accuracy"
    assert cfg.monitor_mode == "max"


def test_monitor_mode_min_for_loss():
    cfg = TrainConfig.from_dict({"data": {"source": "folder", "root": "x"}, "train": {"monitor": "val_loss"}})
    assert cfg.monitor_mode == "min"


def test_mixup_incompatible_with_angle_head():
    with pytest.raises(ValidationError, match="mixup"):
        TrainConfig.from_dict(
            {
                "model": {"angle_head": True},
                "data": {"source": "folder", "root": "x"},
                "optim": {"mixup_alpha": 0.2},
            }
        )


def test_angle_monitor_requires_angle_head():
    with pytest.raises(ValidationError, match="angle_head"):
        TrainConfig.from_dict({"data": {"source": "folder", "root": "x"}, "train": {"monitor": "angle_mae_deg"}})


@pytest.mark.parametrize("aug", [{"rotation_deg": 15.0}, {"hflip": True}])
def test_angle_head_rejects_geometric_augment(aug):
    """Геометрические аугментации портят GT угла (метка не пересчитывается) → запрет."""
    with pytest.raises(ValidationError, match="геометрические аугментации"):
        TrainConfig.from_dict(
            {
                "model": {"angle_head": True},
                "data": {
                    "source": "synthetic",
                    "generator_preset": "x.yaml",
                    "augment": {"enabled": True, **aug},
                },
            }
        )


def test_angle_head_allows_photometric_augment():
    """Фотометрия (color_jitter/random_erasing) угол не трогает — разрешена при angle_head."""
    cfg = TrainConfig.from_dict(
        {
            "model": {"angle_head": True},
            "data": {
                "source": "synthetic",
                "generator_preset": "x.yaml",
                "augment": {"enabled": True, "color_jitter": 0.2, "random_erasing": 0.1},
            },
        }
    )
    assert cfg.model.angle_head is True


def test_dict_roundtrip():
    src = {
        "model": {"arch": "mobilenetv4_medium", "angle_head": True},
        "data": {"source": "exported", "root": "data/ds", "image_size": [96, 96]},
        "optim": {"lr": 0.001, "epochs": 5},
    }
    cfg = TrainConfig.from_dict(src)
    d = cfg.to_dict()
    assert d["model"]["arch"] == "mobilenetv4_medium"
    assert d["data"]["image_size"] == [96, 96]
    assert TrainConfig.from_dict(d).to_dict() == d


def test_yaml_roundtrip(tmp_path):
    cfg = TrainConfig.from_dict({"data": {"source": "folder", "root": "x"}})
    path = cfg.to_yaml(tmp_path / "cfg.yaml")
    loaded = TrainConfig.from_yaml(path)
    assert loaded.to_dict() == cfg.to_dict()
