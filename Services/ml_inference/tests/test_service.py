"""Фасад MLInferenceService для вкладки «Сервисы»: контракт IService."""

from __future__ import annotations

from multiprocess_framework.modules.service_module import IService

from Services.ml_inference.service import MLInferenceService


def test_iservice_contract():
    assert isinstance(MLInferenceService(), IService)


def test_start_scans_models_dir(tmp_path):
    svc = MLInferenceService()
    assert svc.start({"models_dir": str(tmp_path)}) is True  # пустой каталог — не ошибка
    status = svc.get_status()
    assert status["state"] == "running"
    assert status["models"] == []
    assert "onnxruntime" in status["backends"]
    assert svc.stop() is True
