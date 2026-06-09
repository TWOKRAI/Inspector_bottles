"""Фикстуры для тестов ml_inference.

dummy_models_dir — генерирует минимальную ONNX-модель (GlobalAveragePool→Flatten,
3 «класса») + sidecar .yaml + labels.txt в tmp-папке. Позволяет гонять реальный
ONNX-инференс в CI/headless без скачивания настоящих весов.
"""

from __future__ import annotations

from pathlib import Path

import pytest

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper  # noqa: E402

_LABELS = ["alpha", "beta", "gamma"]


def _build_dummy_onnx(path: Path) -> None:
    """Сохранить ONNX: вход (1,3,224,224) → выход (1,3) (среднее по каналам)."""
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 224, 224])
    y = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 3])
    pool = helper.make_node("GlobalAveragePool", ["input"], ["pooled"])
    flat = helper.make_node("Flatten", ["pooled"], ["logits"], axis=1)
    graph = helper.make_graph([pool, flat], "dummy_clf", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    onnx.save(model, str(path))


@pytest.fixture
def dummy_models_dir(tmp_path: Path) -> Path:
    """Папка с одной готовой ONNX-моделью 'dummy' + sidecar + labels."""
    weights = tmp_path / "dummy.onnx"
    _build_dummy_onnx(weights)

    labels = tmp_path / "labels.txt"
    labels.write_text("\n".join(_LABELS), encoding="utf-8")

    sidecar = tmp_path / "dummy.yaml"
    sidecar.write_text(
        "name: Dummy Classifier\n"
        "task: classification\n"
        "backend: onnx\n"
        "weights: dummy.onnx\n"
        "input_size: [224, 224]\n"
        "layout: NCHW\n"
        "color: RGB\n"
        "normalize:\n"
        "  mean: [0.0, 0.0, 0.0]\n"
        "  std: [1.0, 1.0, 1.0]\n"
        "labels: labels.txt\n",
        encoding="utf-8",
    )
    return tmp_path
