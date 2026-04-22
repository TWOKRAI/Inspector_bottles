# -*- coding: utf-8 -*-
"""Тесты HikvisionCameraFacade (мок SDK)."""

import pytest


def test_facade_import():
    """Фасад импортируется без SDK."""
    from hikvision_camera_module import HikvisionCameraFacade
    assert HikvisionCameraFacade is not None


def test_facade_create():
    """Фасад создаётся с callbacks."""
    from hikvision_camera_module import HikvisionCameraFacade
    status_calls = []
    error_calls = []
    facade = HikvisionCameraFacade(
        on_status=lambda t: status_calls.append(t),
        on_error=lambda t: error_calls.append(t),
    )
    assert facade is not None


def test_enum_devices_without_sdk():
    """enum_devices возвращает структуру (SDK может быть недоступен)."""
    from hikvision_camera_module.core.capture import enum_devices
    result = enum_devices()
    assert "status" in result
    assert "devices" in result
    assert isinstance(result["devices"], list)


def test_interfaces_contract():
    """IHikvisionCameraFacade определяет все методы."""
    from hikvision_camera_module.interfaces import IHikvisionCameraFacade
    methods = ["enum_devices", "open", "close", "start_grabbing", "stop_grabbing",
               "capture_frame", "get_parameters", "set_parameters"]
    for m in methods:
        assert hasattr(IHikvisionCameraFacade, m)


def test_process_adapter_import():
    """HikvisionCameraProcessAdapter импортируется."""
    from hikvision_camera_module import HikvisionCameraProcessAdapter
    assert HikvisionCameraProcessAdapter is not None


def test_open_close_sdk_window():
    """open_sdk_window и close_sdk_window возвращают dict."""
    from hikvision_camera_module import HikvisionCameraFacade
    facade = HikvisionCameraFacade()
    r = facade.open_sdk_window()
    assert "status" in r
    assert r["status"] in ("ok", "error")
    r2 = facade.close_sdk_window()
    assert r2.get("status") == "ok"
