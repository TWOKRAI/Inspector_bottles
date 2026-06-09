"""Тесты ModelRegistry — скан, парс sidecar, sandbox-валидация пути."""

from __future__ import annotations

from pathlib import Path

from Services.ml_inference.core.registry import ModelRegistry


def test_scan_finds_model_with_sidecar(dummy_models_dir: Path):
    reg = ModelRegistry(dummy_models_dir)
    specs = reg.scan()
    assert "dummy" in specs
    assert reg.names() == ["dummy"]
    spec = reg.get("dummy")
    assert spec is not None
    assert spec.name == "Dummy Classifier"
    assert spec.backend == "onnx"
    assert spec.input_size == (224, 224)
    assert spec.weights_path.name == "dummy.onnx"
    assert spec.labels_path is not None and spec.labels_path.name == "labels.txt"


def test_weights_without_sidecar_ignored(tmp_path: Path):
    (tmp_path / "lonely.onnx").write_bytes(b"\x00")
    reg = ModelRegistry(tmp_path)
    assert reg.scan() == {}


def test_broken_sidecar_skipped(tmp_path: Path):
    (tmp_path / "bad.onnx").write_bytes(b"\x00")
    (tmp_path / "bad.yaml").write_text(": not valid yaml :", encoding="utf-8")
    reg = ModelRegistry(tmp_path)
    # битый sidecar не должен ронять скан
    assert reg.scan() == {}


def test_missing_dir_returns_empty(tmp_path: Path):
    reg = ModelRegistry(tmp_path / "nope")
    assert reg.scan() == {}


def test_sandbox_rejects_escape_path(tmp_path: Path):
    (tmp_path / "evil.onnx").write_bytes(b"\x00")
    (tmp_path / "evil.yaml").write_text("name: evil\nweights: ../../../etc/passwd\n", encoding="utf-8")
    reg = ModelRegistry(tmp_path)
    # путь вне песочницы → запись пропущена
    assert reg.scan() == {}


def test_labels_loaded(dummy_models_dir: Path):
    reg = ModelRegistry(dummy_models_dir)
    reg.scan()
    spec = reg.get("dummy")
    assert spec is not None
    assert spec.load_labels() == ["alpha", "beta", "gamma"]
