"""Тесты InferenceEngine — реальный ONNX-инференс (dummy) + graceful degradation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from Services.ml_inference import engine as engine_mod
from Services.ml_inference.engine import InferenceEngine, _make_backend


def test_load_and_predict(dummy_models_dir: Path):
    eng = InferenceEngine(str(dummy_models_dir))
    assert "dummy" in eng.registry.names()
    eng.load_model("dummy", device="cpu")
    assert eng.is_ready
    assert eng.current_model == "Dummy Classifier"

    frame = (np.random.rand(480, 640, 3) * 255).astype(np.uint8)
    preds = eng.predict(frame, top_k=3)
    assert len(preds) == 3
    assert {p["label"] for p in preds} == {"alpha", "beta", "gamma"}
    assert all(0.0 <= p["confidence"] <= 1.0 for p in preds)


def test_predict_not_ready_returns_empty(dummy_models_dir: Path):
    eng = InferenceEngine(str(dummy_models_dir))
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert eng.predict(frame) == []


def test_unknown_model_raises(dummy_models_dir: Path):
    eng = InferenceEngine(str(dummy_models_dir))
    with pytest.raises(ValueError):
        eng.load_model("does_not_exist")


def test_unload_resets(dummy_models_dir: Path):
    eng = InferenceEngine(str(dummy_models_dir))
    eng.load_model("dummy")
    assert eng.is_ready
    eng.unload()
    assert not eng.is_ready
    assert eng.current_model is None


def test_graceful_degradation_onnx_missing(dummy_models_dir: Path, monkeypatch):
    """Если onnxruntime недоступен — backend-фабрика даёт понятную ошибку."""
    monkeypatch.setattr(engine_mod, "ONNX_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="onnx"):
        _make_backend("onnx")


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        _make_backend("tensorrt")
