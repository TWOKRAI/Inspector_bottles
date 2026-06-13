"""Фасад MLTrainService для вкладки «Сервисы»: контракт IService (без torch)."""

from __future__ import annotations

import json

import yaml

from multiprocess_framework.modules.service_module import IService

from Services.ml_train.service import MLTrainService


def test_iservice_contract():
    assert isinstance(MLTrainService(), IService)


def test_start_with_empty_runs_dir(tmp_path):
    svc = MLTrainService()
    assert svc.start({"runs_dir": str(tmp_path)}) is True
    status = svc.get_status()
    assert status["state"] == "running"
    assert status["runs"] == 0 and status["best_run"] is None
    assert set(status["ml_stack"]) == {"torch", "torchvision", "timm", "onnx"}
    assert svc.stop() is True


def test_start_sees_runs(tmp_path):
    run = tmp_path / "exp1"
    run.mkdir()
    (run / "config.yaml").write_text(yaml.safe_dump({"model": {"arch": "x"}}), encoding="utf-8")
    (run / "metrics.json").write_text(
        json.dumps({"best_epoch": 1, "monitor": "balanced_accuracy", "best": {"balanced_accuracy": 0.9}}),
        encoding="utf-8",
    )
    (run / "best.pt").write_bytes(b"fake")

    svc = MLTrainService()
    assert svc.start({"runs_dir": str(tmp_path)}) is True
    status = svc.get_status()
    assert status["runs"] == 1
    assert status["best_run"] == "exp1"
