"""Фасад DatasetGenService для вкладки «Сервисы»: контракт IService."""

from __future__ import annotations

from multiprocess_framework.modules.service_module import IService

from Services.dataset_gen.service import DatasetGenService


def test_iservice_contract():
    assert isinstance(DatasetGenService(), IService)


def test_start_status_stop():
    svc = DatasetGenService()
    assert svc.status == "stopped"
    assert svc.start({}) is True
    status = svc.get_status()
    assert status["state"] == "running"
    assert "ru_letters_disk.yaml" in status["presets"]  # комплектный пресет
    assert svc.stop() is True
    assert svc.get_status()["state"] == "stopped"
