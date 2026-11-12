"""Происхождение предсказания (DS-1, Task 2.1): режим угла топ-1 и id модели.

Слепые приёмочные тесты: контракт — приёмка из брифа и design.md §4/§5, а не код.

(a) predictions[0] несёт `angle_symmetry` (`none` | `180` | `full`) — симметрию топ-1 класса из карты
    симметрий модели, ею сеть декодировала угол; без головы угла ключа нет.
(b) после успешного predict у item плагина есть `model_id` = значение регистра `model` (имя, не путь);
    pass-through (модель не выбрана) и ветка ошибки инференса — без `model_id`.

Fake backend, без реальных весов; в тестах плагина — dummy ONNX из conftest.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.engine import InferenceEngine
from Services.ml_inference.plugin.plugin import MLInferencePlugin
from Services.ml_inference.tests.conftest import _build_dummy_onnx

_MODEL_NAME = "mobilenet_v3_large_20260616_050828"


# --- harness (копия паттернов test_angle_contract.py / test_plugin.py) -------


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка: возвращает заранее заданные выходы по именам."""

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


def _make_ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.registers = None  # → локальный register (defaults + config overrides)
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    return ctx


def _frame() -> np.ndarray:
    return (np.random.rand(120, 160, 3) * 255).astype(np.uint8)


@pytest.fixture
def named_model_dir(dummy_models_dir: Path) -> Path:
    """Каталог с моделью `_MODEL_NAME`; `name:` в sidecar НАМЕРЕННО другое — model_id берётся не из него."""
    _build_dummy_onnx(dummy_models_dir / f"{_MODEL_NAME}.onnx")
    sidecar = (dummy_models_dir / "dummy.yaml").read_text(encoding="utf-8")
    sidecar = sidecar.replace("Dummy Classifier", "Sidecar Display Name").replace("dummy.onnx", f"{_MODEL_NAME}.onnx")
    (dummy_models_dir / f"{_MODEL_NAME}.yaml").write_text(sidecar, encoding="utf-8")
    return dummy_models_dir


# --- (a) angle_symmetry топ-1 -------------------------------------------------

_SYMMETRY_MAP = {"Ж": "none", "О": "180"}
_LABELS = ["Ж", "О", "Щ"]  # «Щ» нет в карте симметрий


@pytest.mark.parametrize(
    ("top1_index", "expected_label", "expected_symmetry"),
    [
        (0, "Ж", "none"),
        (1, "О", "180"),
        (2, "Щ", "full"),  # метка вне карты → "full"
    ],
)
def test_top1_carries_symmetry_of_its_class(
    tmp_path: Path, top1_index: int, expected_label: str, expected_symmetry: str
) -> None:
    spec = ModelSpec(
        name="t",
        weights_path=tmp_path / "m.onnx",
        input_size=(32, 32),
        angle_head=True,
        symmetry=_SYMMETRY_MAP,
    )
    logits = np.zeros((1, 3), dtype=np.float32)
    logits[0, top1_index] = 9.0
    outputs = {"logits": logits, "angle": np.array([[0.0, 1.0]], dtype=np.float32)}
    eng = _engine_with(spec, _LABELS, outputs, tmp_path)

    preds = eng.predict(np.zeros((40, 40, 3), dtype=np.uint8))

    assert preds[0]["label"] == expected_label
    assert preds[0].get("angle_symmetry") == expected_symmetry


def test_no_angle_head_no_symmetry_key(tmp_path: Path) -> None:
    """Без головы угла у топ-1 нет и `angle_symmetry` (рядом с отсутствием angle_deg)."""
    spec = ModelSpec(name="t", weights_path=tmp_path / "m.onnx", input_size=(32, 32), angle_head=False)
    outputs = {"logits": np.array([[1.0, 2.0]], dtype=np.float32)}
    eng = _engine_with(spec, ["А", "Б"], outputs, tmp_path)

    preds = eng.predict(np.zeros((40, 40, 3), dtype=np.uint8))

    assert "angle_symmetry" not in preds[0]


# --- (b) model_id в item плагина ---------------------------------------------


def test_item_has_model_id_after_predict(named_model_dir: Path) -> None:
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(named_model_dir), "model": _MODEL_NAME, "confidence_threshold": 0.0}))
    assert plugin._engine.is_ready  # предусловие: модель загрузилась

    out = plugin.process([{"frame": _frame()}])

    assert len(out[0]["predictions"]) == 3  # предусловие: predict успешен
    assert out[0].get("model_id") == "mobilenet_v3_large_20260616_050828"


def test_passthrough_has_no_model_id(dummy_models_dir: Path) -> None:
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir)}))  # модель не выбрана

    out = plugin.process([{"frame": _frame()}])

    assert out[0]["predictions"] == []
    assert "model_id" not in out[0]


def test_failed_model_load_has_no_model_id(dummy_models_dir: Path) -> None:
    """Регистр `model` задан, но модель не загрузилась (ghost) — pass-through, model_id нет."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(dummy_models_dir), "model": "ghost"}))

    out = plugin.process([{"frame": _frame()}])

    assert out[0]["predictions"] == []
    assert "model_id" not in out[0]


def test_inference_error_has_no_model_id(named_model_dir: Path) -> None:
    """Модель загружена, но predict бросает — ветка ошибки инференса, model_id нет."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(named_model_dir), "model": _MODEL_NAME}))
    assert plugin._engine.is_ready

    def _boom(*_a: object, **_k: object) -> list[dict]:
        raise RuntimeError("synthetic inference failure")

    plugin._engine.predict = _boom  # type: ignore[method-assign]

    out = plugin.process([{"frame": _frame()}])

    assert out[0]["predictions"] == []
    assert "model_id" not in out[0]
