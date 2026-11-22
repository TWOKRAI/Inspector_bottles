# -*- coding: utf-8 -*-
# ruff: noqa: F811 — фикстура `make` из core_rig подключена импортом
"""Слепые тесты Task 4.2a, сеанс: порядок записи плана `run`, правка при захвате, `produce()` во время перезахвата.

Часть набора `test_plugin_on_core.py` (каркас — `core_rig.py`).
"""

from __future__ import annotations

import threading
import time

import pytest

from Services.camera_device.testing.fake_port import ALL_CAPABILITIES, FAKE_BINDINGS, make_port
from Services.hikvision_camera.tests.core_rig import FAKE_PORT_CFG, _gated_cam, _pos, _quiet, _wait
from Services.hikvision_camera.tests.core_rig import make  # noqa: F401 — фикстура pytest

pytestmark = pytest.mark.timeout(60)


# ---------------------------------------------------------------------------------------------- #
# 5. Порядок записи плана run (настоящий драйвер mvs над фейк-камерой)
# ---------------------------------------------------------------------------------------------- #


def test_порядок_записи_open_auto_exposure_readback_start(make):
    cam = _gated_cam()
    rig = make({"exposure_time": 5000}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    i_open = _pos(log, ("MV_CC_OpenDevice", ()))
    i_auto = _pos(log, ("MV_CC_SetEnumValueByString", ("ExposureAuto", "Off")))
    i_set = _pos(log, ("MV_CC_SetFloatValue", ("ExposureTime", 5000.0)))
    i_get = _pos(log, ("MV_CC_GetFloatValue", ("ExposureTime",)), after=i_set)
    i_start = _pos(log, ("MV_CC_StartGrabbing", ()))
    assert i_open < i_auto < i_set < i_get < i_start
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_frame_rate_enable_true_пишется_раньше_frame_rate(make):
    cam = _gated_cam()
    rig = make({"frame_rate_enable": True}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    i_enable = _pos(log, ("MV_CC_SetBoolValue", ("AcquisitionFrameRateEnable", True)))
    i_rate = _pos(log, ("MV_CC_SetFloatValue", ("AcquisitionFrameRate", 25.0)))
    assert i_enable < i_rate
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_frame_rate_enable_false_frame_rate_не_пишется(make):
    cam = _gated_cam()
    rig = make({"frame_rate_enable": False}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    assert [entry for entry in log if entry[0] == "MV_CC_SetFloatValue" and entry[1][0] == "AcquisitionFrameRate"] == []
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_packet_managed_false_пакетные_узлы_не_пишутся(make):
    cam = _gated_cam()
    rig = make({"packet_managed": False}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    written = [entry[1][0] for entry in _quiet(cam) if entry[0] == "MV_CC_SetIntValue"]
    assert "GevSCPSPacketSize" not in written
    assert "GevSCPD" not in written


def test_packet_managed_true_пишет_размер_и_задержку_пакета(make):
    cam = _gated_cam()
    rig = make({"packet_managed": True}, cam_cls=cam)
    assert rig.take()["status"] == "ok"
    log = _quiet(cam)
    _pos(log, ("MV_CC_SetIntValue", ("GevSCPSPacketSize", 1500)))
    _pos(log, ("MV_CC_SetIntValue", ("GevSCPD", 0)))
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


# ---------------------------------------------------------------------------------------------- #
# 6. Правка при захвате (register_update в состоянии grabbing)
# ---------------------------------------------------------------------------------------------- #


def _port_names(port) -> list[str]:
    return [call[0] for call in list(port.calls)]


def test_правка_экспозиции_при_захвате_с_restart_regrab_stop_set_get_start(make):
    port = make_port(frame_period_s=0.02)
    assert "restart_regrab" in port.capabilities
    rig = make(FAKE_PORT_CFG, port=port, bindings=FAKE_BINDINGS)
    assert rig.take()["status"] == "ok"
    base = len(port.calls)

    result = rig.register_update("exposure_time", 6000)

    assert result["success"] is True, result
    _wait(lambda: _port_names(port)[base:].count("start_grabbing") == 1, "перезахват: start_grabbing после правки")
    after = [(name, args) for name, args, _ in port.calls[base:] if name != "get_frame"]
    assert after == [
        ("stop_grabbing", ()),
        ("set_param", ("ExposureTime", 6000.0)),
        ("get_param", ("ExposureTime",)),
        ("start_grabbing", ()),
    ]
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


def test_правка_gain_при_захвате_на_mvs_stop_close_open_весь_план_start(make):
    cam = _gated_cam()
    rig = make(cam_cls=cam)
    assert rig.take()["status"] == "ok"
    base = len(_quiet(cam))

    result = rig.register_update("gain", 6.0)

    assert result["success"] is True, result
    _wait(lambda: ("MV_CC_StartGrabbing", ()) in _quiet(cam)[base:], "перезахват: StartGrabbing после правки")
    window = _quiet(cam)[base:]
    assert window[0] == ("MV_CC_StopGrabbing", ())
    assert window[-1] == ("MV_CC_StartGrabbing", ())
    i_stop = _pos(window, ("MV_CC_StopGrabbing", ()))
    i_close = _pos(window, ("MV_CC_CloseDevice", ()), after=i_stop)
    i_open = _pos(window, ("MV_CC_OpenDevice", ()), after=i_close)
    i_gain = _pos(window, ("MV_CC_SetFloatValue", ("Gain", 6.0)), after=i_open)
    # план записи пишется целиком (не только Gain): ExposureTime идёт в том же окне
    i_exposure = _pos(window, ("MV_CC_SetFloatValue", ("ExposureTime", 10000.0)), after=i_open)
    assert i_gain < len(window) - 1
    assert i_exposure < len(window) - 1
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}


# ---------------------------------------------------------------------------------------------- #
# 8. produce() не блокируется во время перезахвата
# ---------------------------------------------------------------------------------------------- #


def test_produce_не_блокируется_на_перезахвате_с_закрытием_порта(make):
    port = make_port(capabilities=ALL_CAPABILITIES - {"restart_regrab"}, open_delay_s=0.5, frame_period_s=0.02)
    rig = make(FAKE_PORT_CFG, port=port, bindings=FAKE_BINDINGS)
    assert rig.take()["status"] == "ok"
    editor = threading.Thread(target=lambda: rig.register_update("exposure_time", 6000.0), daemon=True)
    editor.start()
    _wait(lambda: _port_names(port).count("open") == 2, "перезахват дошёл до второго open")

    durations = []
    for _ in range(100):
        started = time.perf_counter()
        rig.plugin.produce()
        durations.append(time.perf_counter() - started)
    regrab_still_running = _port_names(port).count("start_grabbing") == 1

    editor.join(10.0)
    assert not editor.is_alive()
    _wait(lambda: _port_names(port).count("start_grabbing") == 2, "перезахват завершился")
    assert regrab_still_running, "перезахват кончился раньше замеров: тест ничего не доказывает"
    assert max(durations) < 0.05


# ---------------------------------------------------------------------------------------------- #
# 9. Умолчания и согласованность таблицы привязки с register'ом
# ---------------------------------------------------------------------------------------------- #


def test_take_device_без_правок_register_параметры_пишутся_без_ошибок(make):
    cam = _gated_cam()
    rig = make(cam_cls=cam)
    answer = rig.take()
    assert answer["status"] == "ok", answer
    assert rig.plugin.cmd_read_params({})["param_errors"] == {}
