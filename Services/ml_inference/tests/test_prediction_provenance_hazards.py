"""Hazard-тест DS-1 Task 2.1: `angle_symmetry` доходит от движка до выхода ПЛАГИНА.

Приёмочные тесты проверяют симметрию на уровне движка. Здесь — реальный плагин + реальный
движок с fake-backend: между `engine.predict` и выходом плагина лежит `_mark_below_threshold`
(копирует предсказания) — если бы он терял поля, движок-уровневый тест остался бы зелёным.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.engine import InferenceEngine
from Services.ml_inference.plugin.plugin import MLInferencePlugin


class _FakeBackend(BaseInferenceBackend):
    def __init__(self, outputs: dict[str, np.ndarray]) -> None:
        super().__init__()
        self._outputs = outputs

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        return self._outputs

    def unload(self) -> None:
        self._spec = None


def test_plugin_output_carries_angle_symmetry_and_model_id(tmp_path: Path) -> None:
    ctx = MagicMock()
    ctx.config = {"models_dir": str(tmp_path), "model": "fake_model", "confidence_threshold": 0.0}
    ctx.registers = None
    ctx.state_proxy = None
    plugin = MLInferencePlugin()
    plugin.configure(ctx)  # models_dir пуст → загрузка «fake_model» не удалась, движок подменяем ниже

    spec = ModelSpec(
        name="t",
        weights_path=tmp_path / "m.onnx",
        input_size=(32, 32),
        angle_head=True,
        symmetry={"Ж": "none", "О": "180"},
    )
    logits = np.array([[0.0, 9.0, 0.0]], dtype=np.float32)  # top-1 = «О» (симметрия 180)
    outputs = {"logits": logits, "angle": np.array([[0.0, 1.0]], dtype=np.float32)}
    engine = InferenceEngine(str(tmp_path))
    backend = _FakeBackend(outputs)
    backend.load(spec)
    engine._backend, engine._spec, engine._labels = backend, spec, ["Ж", "О", "Щ"]
    plugin._engine = engine
    assert plugin._engine.is_ready  # предусловие

    out = plugin.process([{"frame": np.zeros((40, 40, 3), dtype=np.uint8)}])

    top1 = out[0]["predictions"][0]
    assert top1["label"] == "О"
    assert top1["angle_symmetry"] == "180"
    assert out[0]["model_id"] == "fake_model"
    assert "angle_symmetry" not in out[0]["predictions"][1]  # только у топ-1
