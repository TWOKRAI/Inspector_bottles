"""Экспорт обученной модели в ONNX + sidecar YAML для Services/ml_inference.

Результат в models_dir (по конвенции data/models/README.md):
    <model_id>.onnx          — веса (вход NCHW float, динамический batch)
    <model_id>.yaml          — sidecar: препроцессинг + labels
    <model_id>_classes.txt   — имена классов (по строке)

Модель сразу видна ModelRegistry → выпадающий список в Pipeline GUI.
При angle_head выходов два: logits[B,C] и angle[B,2] (sin, cos; декодирование
atan2 не требует нормировки) — ml_inference использует первый выход.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import torch
import yaml

from Services.ml_train.config import TrainConfig
from Services.ml_train.models import build_model

logger = logging.getLogger(__name__)


def load_checkpoint(path: str | Path) -> dict[str, Any]:
    """Прочитать чекпоинт Trainer (best.pt/last.pt). weights_only — безопасный unpickle."""
    return torch.load(Path(path), map_location="cpu", weights_only=True)


def export_onnx(
    checkpoint_path: str | Path,
    models_dir: str | Path = "data/models",
    model_id: str | None = None,
    opset: int = 17,
    verify: bool = True,
) -> Path:
    """Экспортировать чекпоинт в ONNX + sidecar.

    Pre: checkpoint_path — чекпоинт Trainer (содержит config/class_names/image_size).
    Post: в models_dir лежат .onnx + .yaml + _classes.txt; возвращён путь к .onnx.
          При verify и установленном onnxruntime выполнена parity-проверка
          (расхождение torch vs ORT > 1e-3 → ошибка).
    """
    checkpoint_path = Path(checkpoint_path)
    ckpt = load_checkpoint(checkpoint_path)
    config = TrainConfig.from_dict(ckpt["config"])
    class_names: list[str] = list(ckpt["class_names"])
    h, w = (int(v) for v in ckpt["image_size"])
    symmetry_map: dict[str, str] = ckpt.get("symmetry_map") or {}

    # pretrained=False: веса берём из чекпоинта, не из ImageNet (иначе экспорт
    # на офлайн-стенде повиснет на загрузке, а веса всё равно перезатираются)
    model_cfg = config.model.model_copy(update={"pretrained": False})
    model = build_model(model_cfg, num_classes=len(class_names))
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    out_dir = Path(models_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if model_id is None:
        # имя прогона (родитель чекпоинта) — уникально в runs_dir
        model_id = checkpoint_path.parent.name
    onnx_path = out_dir / f"{model_id}.onnx"

    dummy = torch.randn(1, 3, h, w)
    output_names = ["logits", "angle"] if config.model.angle_head else ["logits"]
    _onnx_export(model, dummy, onnx_path, output_names, opset)
    logger.info("ONNX сохранён: %s (вход 1x3x%dx%d, выходы: %s)", onnx_path, h, w, output_names)

    labels_name = f"{model_id}_classes.txt"
    (out_dir / labels_name).write_text("\n".join(class_names) + "\n", encoding="utf-8")
    _write_sidecar(out_dir / f"{model_id}.yaml", model_id, config, (h, w), labels_name, symmetry_map)

    if verify:
        _verify_parity(model, dummy, onnx_path)
    return onnx_path


def _onnx_export(
    model: torch.nn.Module,
    dummy: torch.Tensor,
    onnx_path: Path,
    output_names: list[str],
    opset: int,
) -> None:
    """torch.onnx.export через стабильный TorchScript-путь (dynamo у MultiHead
    с tuple-выходом None|Tensor менее предсказуем)."""
    kwargs: dict[str, Any] = dict(
        input_names=["input"],
        output_names=output_names,
        dynamic_axes={"input": {0: "batch"}, **{name: {0: "batch"} for name in output_names}},
        opset_version=opset,
    )
    try:
        torch.onnx.export(model, (dummy,), str(onnx_path), dynamo=False, **kwargs)
    except TypeError:
        # старые torch без параметра dynamo
        torch.onnx.export(model, (dummy,), str(onnx_path), **kwargs)


def _write_sidecar(
    path: Path,
    model_id: str,
    config: TrainConfig,
    input_size: tuple[int, int],
    labels_name: str,
    symmetry_map: dict[str, str] | None = None,
) -> None:
    """Sidecar по конвенции data/models/README.md (читает ModelRegistry ml_inference).

    Пишет ВСЁ для воспроизводимого инференса: размер/нормализацию/каналы/политику
    ресайза и — при angle_head — имена выходов и симметрию классов (для декода угла).
    resize_policy=stretch: обучение не делает letterbox, инференс не должен тоже.
    """
    sidecar: dict[str, Any] = {
        "name": f"{model_id} ({config.model.arch})",
        "task": "classification",
        "backend": "onnx",
        "weights": f"{model_id}.onnx",
        "input_size": [input_size[0], input_size[1]],
        "layout": "NCHW",
        "color": "RGB",
        "resize_policy": "stretch",
        "normalize": {
            "mean": list(config.data.normalize.mean),
            "std": list(config.data.normalize.std),
        },
        "labels": labels_name,
        "output_name": "logits",
    }
    if config.model.angle_head:
        sidecar["angle_head"] = True
        sidecar["angle_output_name"] = "angle"
        sidecar["angle_convention"] = "ccw_deg"  # угол CCW в градусах (контракт decode_angle)
        sidecar["symmetry"] = dict(symmetry_map or {})
    path.write_text(yaml.safe_dump(sidecar, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _verify_parity(model: torch.nn.Module, dummy: torch.Tensor, onnx_path: Path) -> None:
    """Сверить выходы torch и onnxruntime на dummy-входе (если ORT установлен)."""
    try:
        import onnxruntime as ort
    except ImportError:
        logger.info("onnxruntime не установлен — parity-проверка пропущена")
        return
    import numpy as np

    with torch.no_grad():
        torch_logits = model(dummy)[0].numpy()
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    ort_logits = session.run(None, {"input": dummy.numpy()})[0]
    max_diff = float(np.abs(torch_logits - ort_logits).max())
    if max_diff > 1e-3:
        raise RuntimeError(f"Расхождение torch/ONNX: max|Δ|={max_diff:.2e} > 1e-3")
    logger.info("Parity OK: max|Δ logits|=%.2e", max_diff)
