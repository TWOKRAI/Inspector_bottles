"""Smoke: полный цикл обучения на CPU (крошечные данные) + экспорт в ONNX.

Требует torch. mobilenet_v3_small без pretrained-весов (без сети), 2 эпохи.
"""

import numpy as np
import pytest

torch = pytest.importorskip("torch")
cv2 = pytest.importorskip("cv2")

from Services.ml_train.config import TrainConfig  # noqa: E402
from Services.ml_train.models import available_archs, build_model  # noqa: E402
from Services.ml_train.selection import RunRegistry  # noqa: E402
from Services.ml_train.trainer import Trainer  # noqa: E402


def _make_folder_data(root, n_per_class=6):
    rng = np.random.default_rng(0)
    for ci, name in enumerate(["circle", "square"]):
        d = root / name
        d.mkdir(parents=True)
        for i in range(n_per_class):
            img = np.full((40, 40, 3), 30, dtype=np.uint8)
            if ci == 0:
                cv2.circle(img, (20, 20), 12, (220, 220, 220), -1)
            else:
                cv2.rectangle(img, (8, 8), (32, 32), (220, 220, 220), -1)
            noise = rng.integers(0, 20, img.shape, dtype=np.uint8)
            cv2.imwrite(str(d / f"{i}.png"), cv2.add(img, noise))


@pytest.fixture(scope="module")
def tiny_run(tmp_path_factory):
    """Один полный прогон на модуль (дорого) — артефакты переиспользуются тестами."""
    base = tmp_path_factory.mktemp("ml_train_smoke")
    _make_folder_data(base / "data")
    config = TrainConfig.from_dict(
        {
            "model": {"arch": "mobilenet_v3_small", "pretrained": False},
            "data": {
                "source": "folder",
                "root": str(base / "data"),
                "image_size": [32, 32],
                "batch_size": 4,
                "val_split": 0.25,
                "augment": {"enabled": False},
            },
            "optim": {"epochs": 2, "lr": 0.001, "warmup_epochs": 1},
            "train": {
                "device": "cpu",
                "amp": "off",
                "channels_last": False,
                "ema_decay": 0.9,
                "runs_dir": str(base / "runs"),
                "run_name": "smoke",
            },
        }
    )
    result = Trainer(config).fit()
    return base, result


def test_fit_artifacts(tiny_run):
    base, result = tiny_run
    run_dir = base / "runs" / "smoke"
    assert result.run_dir == run_dir
    for name in ("config.yaml", "classes.txt", "history.json", "metrics.json", "best.pt", "last.pt"):
        assert (run_dir / name).is_file(), name
    assert len(result.history) == 2
    assert result.best_epoch >= 0
    assert (run_dir / "classes.txt").read_text(encoding="utf-8").split() == ["circle", "square"]
    assert 0.0 <= result.best_metrics["accuracy"] <= 1.0


def test_checkpoint_loadable_weights_only(tiny_run):
    base, result = tiny_run
    ckpt = torch.load(result.checkpoint_path, map_location="cpu", weights_only=True)
    assert ckpt["class_names"] == ["circle", "square"]
    assert ckpt["image_size"] == [32, 32]
    cfg = TrainConfig.from_dict(ckpt["config"])
    model = build_model(cfg.model, num_classes=2)
    model.load_state_dict(ckpt["model_state"])  # strict — все ключи совпадают


def test_run_registry_sees_run(tiny_run):
    base, _ = tiny_run
    reg = RunRegistry(base / "runs")
    reg.scan()
    best = reg.best("balanced_accuracy")
    assert best is not None and best.name == "smoke"
    assert best.arch == "mobilenet_v3_small"


def test_export_onnx_with_sidecar(tiny_run):
    onnx = pytest.importorskip("onnx")  # noqa: F841
    base, result = tiny_run
    from Services.ml_train.export import export_onnx

    models_dir = base / "models"
    onnx_path = export_onnx(result.checkpoint_path, models_dir=models_dir, model_id="smoke_model")
    assert onnx_path.is_file()
    assert (models_dir / "smoke_model.yaml").is_file()
    labels = (models_dir / "smoke_model_classes.txt").read_text(encoding="utf-8").split()
    assert labels == ["circle", "square"]

    import yaml

    sidecar = yaml.safe_load((models_dir / "smoke_model.yaml").read_text(encoding="utf-8"))
    assert sidecar["backend"] == "onnx"
    assert sidecar["weights"] == "smoke_model.onnx"
    assert sidecar["input_size"] == [32, 32]
    assert sidecar["labels"] == "smoke_model_classes.txt"


def test_exported_model_visible_to_ml_inference(tiny_run):
    """Интеграция: ModelRegistry ml_inference видит экспортированную модель."""
    pytest.importorskip("onnx")
    base, _ = tiny_run
    from Services.ml_inference.core.registry import ModelRegistry

    reg = ModelRegistry(base / "models")
    specs = reg.scan()
    assert "smoke_model" in specs
    spec = specs["smoke_model"]
    assert spec.input_size == (32, 32)
    assert spec.load_labels() == ["circle", "square"]


def test_export_onnx_angle_head_two_outputs(tmp_path):
    """Нетривиальный путь экспорта: модель с угловой головой → два выхода ONNX."""
    pytest.importorskip("onnx")
    ort = pytest.importorskip("onnxruntime")
    from Services.ml_train.config import TrainConfig
    from Services.ml_train.export import export_onnx

    config = TrainConfig.from_dict(
        {
            "model": {"arch": "mobilenet_v3_small", "pretrained": False, "angle_head": True},
            "data": {"source": "folder", "root": "unused"},
        }
    )
    model = build_model(config.model, num_classes=4)
    ckpt = {
        "model_state": model.state_dict(),
        "config": config.to_dict(),
        "class_names": ["a", "b", "c", "d"],
        "image_size": [32, 32],
        "epoch": 0,
        "metrics": {},
    }
    torch.save(ckpt, tmp_path / "best.pt")
    onnx_path = export_onnx(tmp_path / "best.pt", models_dir=tmp_path / "models", model_id="ang")

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    names = [o.name for o in session.get_outputs()]
    assert names == ["logits", "angle"]
    logits, angle = session.run(None, {"input": np.random.rand(2, 3, 32, 32).astype(np.float32)})
    assert logits.shape == (2, 4) and angle.shape == (2, 2)


def test_angle_head_forward_and_loss_mask():
    """Модель с угловой головой: 2 выхода; full-симметрия маскируется в loss."""
    from Services.ml_train.config import ModelConfig
    from Services.ml_train.trainer import _angle_loss

    model = build_model(ModelConfig(arch="mobilenet_v3_small", pretrained=False, angle_head=True), 3)
    logits, angle = model(torch.randn(2, 3, 32, 32))
    assert logits.shape == (2, 3) and angle.shape == (2, 2)

    target = {
        "angle": torch.tensor([[0.0, 1.0], [1.0, 0.0]]),
        "angle_valid": torch.tensor([False, False]),
    }
    loss = _angle_loss(angle, target, torch.device("cpu"))
    assert loss.item() == 0.0 and loss.requires_grad


def test_build_model_unknown_arch():
    from Services.ml_train.config import ModelConfig

    with pytest.raises(ValueError, match="Неизвестная архитектура"):
        build_model(ModelConfig(arch="resnet999"), 2)


def test_available_archs_lists_sources():
    archs = available_archs()
    assert archs["mobilenet_v3_large"] == "torchvision"
    assert "mobilenetv4_medium" in archs
