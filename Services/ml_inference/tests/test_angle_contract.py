"""Контракт угла: декод (sin,cos)→угол, паритет с dataset_gen, end-to-end в engine.

Закрывает разрывы C1-C3 ревью: мульти-выход backend (dict), декод угла в
постпроцессе, симметрия из spec. Паритет с encode_angle гарантирует, что
обучение и инференс не разъедутся по конвенции.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from Services.dataset_gen.core.symmetry import encode_angle
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.core.postprocess import angle_postprocess, decode_angle
from Services.ml_inference.engine import InferenceEngine


# --- декод угла -------------------------------------------------------------


@pytest.mark.parametrize("deg", [0, 17, 45, 90, 123, 200, 270, 359])
def test_decode_none_recovers_angle(deg: int) -> None:
    s, c, _ = encode_angle(deg, "none")
    out = angle_postprocess(np.array([[s, c]], dtype=np.float32), "none")
    assert out["angle_valid"] is True
    assert abs(((out["angle_deg"] - deg + 180) % 360) - 180) < 1e-3


@pytest.mark.parametrize("deg", [0, 30, 90, 170, 200, 350])
def test_decode_180_collapses_half_turn(deg: int) -> None:
    s, c, _ = encode_angle(deg, "180")
    out = angle_postprocess(np.array([s, c], dtype=np.float32), "180")
    assert out["angle_valid"] is True
    assert 0.0 <= out["angle_deg"] < 180.0
    # θ и θ+180° должны декодиться в один угол (с точностью до периода 180°)
    s2, c2, _ = encode_angle(deg + 180, "180")
    out2 = angle_postprocess(np.array([s2, c2], dtype=np.float32), "180")
    d = abs(out["angle_deg"] - out2["angle_deg"]) % 180.0
    assert min(d, 180.0 - d) < 1e-2


def test_decode_full_is_undefined() -> None:
    out = angle_postprocess(np.array([0.0, 0.0], dtype=np.float32), "full")
    assert out == {"angle_deg": 0.0, "angle_valid": False}


def test_decode_scale_invariant() -> None:
    """atan2 масштабо-инвариантен → ненормированный (sin,cos) даёт тот же угол."""
    s, c, _ = encode_angle(73, "none")
    a = decode_angle(s, c, "none")[0]
    b = decode_angle(5.0 * s, 5.0 * c, "none")[0]
    assert abs(a - b) < 1e-4


def test_two_decode_copies_identical() -> None:
    """СТРАЖ: decode_angle в ml_inference и dataset_gen обязаны совпадать бит-в-бит.

    Это дубль одного контракта (deployment-развязка); расхождение = train↔inference
    разъехались. Тест ловит правку одной копии без другой.
    """
    from Services.dataset_gen.core.symmetry import decode_angle as dg_decode

    for sym in ("none", "180", "full"):
        for deg in range(0, 360, 7):
            s, c, _ = encode_angle(deg, sym)
            assert decode_angle(s, c, sym) == dg_decode(s, c, sym), (sym, deg)


# --- end-to-end в движке (fake backend, без ONNX) ---------------------------


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка: возвращает заранее заданные выходы по именам (dict)."""

    def __init__(self, outputs: dict[str, np.ndarray]) -> None:
        super().__init__()
        self._outputs = outputs

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        return self._outputs

    def unload(self) -> None:
        self._spec = None


def _engine_with(spec: ModelSpec, labels: list[str], outputs: dict, tmp_path: Path) -> InferenceEngine:
    eng = InferenceEngine(str(tmp_path))  # пустой каталог моделей
    backend = _FakeBackend(outputs)
    backend.load(spec)
    eng._backend = backend
    eng._spec = spec
    eng._labels = labels
    return eng


def test_engine_attaches_angle_to_top1(tmp_path: Path) -> None:
    s, c, _ = encode_angle(123, "none")
    spec = ModelSpec(
        name="t",
        weights_path=tmp_path / "m.onnx",
        input_size=(32, 32),
        angle_head=True,
        symmetry={"А": "none", "Б": "none"},
    )
    outputs = {
        "logits": np.array([[5.0, 0.0]], dtype=np.float32),  # argmax 0 → 'А'
        "angle": np.array([[s, c]], dtype=np.float32),
    }
    eng = _engine_with(spec, ["А", "Б"], outputs, tmp_path)
    preds = eng.predict(np.zeros((40, 40, 3), dtype=np.uint8))
    assert preds[0]["label"] == "А"
    assert preds[0]["angle_valid"] is True
    assert abs(((preds[0]["angle_deg"] - 123 + 180) % 360) - 180) < 1e-2


def test_engine_full_symmetry_marks_invalid(tmp_path: Path) -> None:
    spec = ModelSpec(
        name="t",
        weights_path=tmp_path / "m.onnx",
        input_size=(32, 32),
        angle_head=True,
        symmetry={"О": "full"},
    )
    outputs = {
        "logits": np.array([[9.0]], dtype=np.float32),
        "angle": np.array([[0.0, 0.0]], dtype=np.float32),
    }
    eng = _engine_with(spec, ["О"], outputs, tmp_path)
    preds = eng.predict(np.zeros((40, 40, 3), dtype=np.uint8))
    assert preds[0]["label"] == "О"
    assert preds[0]["angle_valid"] is False


def test_engine_no_angle_head_no_angle_fields(tmp_path: Path) -> None:
    spec = ModelSpec(name="t", weights_path=tmp_path / "m.onnx", input_size=(32, 32), angle_head=False)
    outputs = {"logits": np.array([[1.0, 2.0]], dtype=np.float32)}
    eng = _engine_with(spec, ["А", "Б"], outputs, tmp_path)
    preds = eng.predict(np.zeros((40, 40, 3), dtype=np.uint8))
    assert "angle_deg" not in preds[0]
