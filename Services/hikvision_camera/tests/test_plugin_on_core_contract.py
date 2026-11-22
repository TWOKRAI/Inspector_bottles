# -*- coding: utf-8 -*-
"""Слепые тесты Task 4.2a, контракт плагина: набор команд, умолчания и согласованность `register`, выход.

Часть набора `test_plugin_on_core.py` (каркас — `core_rig.py`). Плагин в этих тестах не запускается.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.registers_module import RegistersManager
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.hikvision_camera import driver
from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin
from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters

pytestmark = pytest.mark.timeout(60)

SOURCE_FILE = Path(__file__).resolve().parents[1] / "plugin" / "plugin.py"


# ---------------------------------------------------------------------------------------------- #
# 4. Команды: ровно девять, старые тринадцать ушли, subprocess в плагине нет
# ---------------------------------------------------------------------------------------------- #

NEW_COMMANDS = {
    "take_device",
    "release_device",
    "get_status",
    "reset_stats",
    "read_params",
    "apply_params",
    "list_devices",
    "describe_params",
    "trigger_software",
}
OLD_COMMANDS = (
    "open",
    "close",
    "start_capture",
    "stop_capture",
    "enum_devices",
    "get_parameters",
    "set_parameters",
    "set_exposure",
    "set_gain",
    "set_frame_rate",
    "set_resolution",
    "open_sdk_app",
    "close_sdk_app",
)


def test_плагин_наследует_ядро_и_называется_hikvision():
    assert issubclass(HikvisionCameraPlugin, CameraDevicePlugin)
    assert HikvisionCameraPlugin.name == "hikvision"


def test_register_плагина_наследует_register_ядра():
    assert issubclass(HikvisionCameraRegisters, CameraDeviceRegisters)


def test_команды_плагина_ровно_девять_имён_ядра():
    assert set(HikvisionCameraPlugin.commands) == NEW_COMMANDS


@pytest.mark.parametrize("old", OLD_COMMANDS)
def test_старая_команда_отсутствует(old):
    assert old not in HikvisionCameraPlugin.commands


def test_в_исходнике_плагина_нет_subprocess():
    assert "subprocess" not in SOURCE_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------- #
# 9. Умолчания и согласованность таблицы привязки с register'ом
# ---------------------------------------------------------------------------------------------- #


def test_ключи_таблицы_привязки_драйвера_есть_в_полях_register():
    assert set(driver.BINDINGS) <= set(HikvisionCameraRegisters.model_fields)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("gain", 0.0, id="gain"),
        pytest.param("frame_rate", 25.0, id="frame_rate"),
        pytest.param("exposure_time", 10000.0, id="exposure_time"),
        pytest.param("packet_size", 1500, id="packet_size"),
        pytest.param("packet_delay", 0, id="packet_delay"),
        pytest.param("packet_managed", False, id="packet_managed"),
        pytest.param("frame_rate_enable", False, id="frame_rate_enable"),
        pytest.param("exposure_auto", "Off", id="exposure_auto"),
        pytest.param("resolution_width", 1440, id="resolution_width"),
        pytest.param("resolution_height", 1080, id="resolution_height"),
        pytest.param("resize_mode", "letterbox", id="resize_mode"),
    ],
)
def test_умолчание_поля_register(field, expected):
    assert field in HikvisionCameraRegisters.model_fields
    value = getattr(HikvisionCameraRegisters(), field)
    assert value == expected
    assert type(value) is type(expected)


def test_exposure_time_вендорского_register_применяется_перезапуском():
    meta = HikvisionCameraRegisters.get_all_fields_meta()["exposure_time"]
    assert meta.apply == "restart"


def test_exposure_auto_есть_в_базовом_register_ядра_перед_exposure_time():
    fields = list(CameraDeviceRegisters.model_fields)
    assert "exposure_auto" in fields
    assert fields.index("exposure_auto") < fields.index("exposure_time")


def test_exposure_auto_во_вендорском_register_перед_exposure_time():
    fields = list(HikvisionCameraRegisters.model_fields)
    assert "exposure_auto" in fields
    assert fields.index("exposure_auto") < fields.index("exposure_time")


@pytest.mark.parametrize("value", ["Off", "Once", "Continuous"])
def test_exposure_auto_принимает_три_значения(value):
    assert CameraDeviceRegisters(exposure_auto=value).exposure_auto == value


def test_exposure_auto_отвергает_чужое_значение():
    assert "exposure_auto" in CameraDeviceRegisters.model_fields
    with pytest.raises(ValidationError):
        CameraDeviceRegisters(exposure_auto="Bogus")


# ---------------------------------------------------------------------------------------------- #
# 10. Выход и ресайз
# ---------------------------------------------------------------------------------------------- #


def test_выход_плагина_один_порт_frame_image_bgr():
    outputs = HikvisionCameraPlugin.outputs
    assert [(p.name, p.dtype, p.shape) for p in outputs] == [("frame", "image/bgr", "(H, W, 3)")]
    assert all(isinstance(p, Port) for p in outputs)


def test_resolution_width_ноль_отвергается_конструктором_register():
    assert "resolution_width" in HikvisionCameraRegisters.model_fields
    with pytest.raises(ValidationError):
        HikvisionCameraRegisters(resolution_width=0)


def test_resolution_width_ноль_отвергается_менеджером_register_а_один_принимается():
    assert "resolution_width" in HikvisionCameraRegisters.model_fields
    name = HikvisionCameraPlugin.name
    manager = RegistersManager(registers={name: HikvisionCameraRegisters()})
    ok_one, _ = manager.set_field_value(name, "resolution_width", 1)
    ok_zero, _ = manager.set_field_value(name, "resolution_width", 0)
    assert ok_one is True
    assert ok_zero is False
