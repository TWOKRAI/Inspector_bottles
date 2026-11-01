# -*- coding: utf-8 -*-
"""Hazard-тесты фейка порта (Task 1.5, автор — исполнитель): то, что слепой тестер не уместил в лимит.

Ожидаемые значения — литералы из DESIGN задачи 1.5, не вычисляются из кода под тестом.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.camera_device.interface import Binding, DeviceIdentity, PortError
from Services.camera_device.testing.fake_port import from_recording, make_port

REPO_ROOT = Path(__file__).resolve().parents[3]
MVCR_RECORDING = REPO_ROOT / "Services/camera_device/testing/recordings/mvcr_ID3013.json"

IDENT = DeviceIdentity("serial", "FAKE-0001")
TRIGGER_MODE = Binding("genicam", "TriggerMode", "enum")
TRIGGER_SOURCE = Binding("genicam", "TriggerSource", "enum")
EXPOSURE = Binding("genicam", "ExposureTime", "float")


def test_stop_grabbing_outside_grabbing_does_not_arm_neter_after_stop():
    port = make_port(neter_after_stop=True)
    port.open(IDENT)
    port.stop_grabbing()  # вне grabbing: no-op, режим не включается
    port.set_param(TRIGGER_MODE, "On")
    assert port.get_param(TRIGGER_MODE) == "On"
    port.close()


def test_applied_but_error_frozenset_hits_only_listed_keys():
    port = make_port(applied_but_error=frozenset({"TriggerMode"}))
    port.open(IDENT)
    port.set_param(EXPOSURE, 2000.0)  # не в наборе: без ошибки
    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_MODE, "On")  # в наборе: значение меняется, затем ошибка
    assert exc_info.value.kind == "network"
    assert port.get_param(TRIGGER_MODE) == "On"
    port.close()


def test_mvcr_enum_with_null_entries_reads_other_until_first_write_then_accepts_any_string():
    port = from_recording(MVCR_RECORDING)
    port.open(DeviceIdentity("serial", "00DB2156580"))
    port.set_param(TRIGGER_MODE, "On")  # открывает TriggerSource
    with pytest.raises(PortError) as exc_info:
        port.get_param(TRIGGER_SOURCE)  # value: null
    assert exc_info.value.kind == "other"
    port.set_param(TRIGGER_SOURCE, "AnyVendorLine")  # entries: null -> любая строка
    assert port.get_param(TRIGGER_SOURCE) == "AnyVendorLine"
    port.close()


def test_mvcr_node_closed_forever_without_parent_rule():
    port = from_recording(MVCR_RECORDING)
    port.open(DeviceIdentity("serial", "00DB2156580"))
    port.set_param(TRIGGER_MODE, "On")
    with pytest.raises(PortError) as exc_info:
        port.get_param(Binding("genicam", "QualityEnable", "bool"))
    assert exc_info.value.kind == "access"
    assert exc_info.value.code == 0x80020106
    port.close()


def test_sdk_refcount_and_release_without_acquire_raises_runtime_error():
    port = make_port()
    port.sdk.acquire()
    port.sdk.acquire()
    port.sdk.release()
    port.sdk.release()
    with pytest.raises(RuntimeError):
        port.sdk.release()
    assert [entry[0] for entry in port.calls] == ["acquire", "acquire", "release", "release", "release"]
    assert port.sdk.enum_devices() == [DeviceIdentity("serial", "FAKE-0001")]
    assert port.calls[-1][:2] == ("enum_devices", ())


def test_frame_num_starts_at_one_and_increments_by_one():
    port = make_port()
    port.open(IDENT)
    port.start_grabbing()
    nums = [port.get_frame(100).frame_num for _ in range(3)]
    assert nums == [1, 2, 3]
    port.close()


def test_range_kind_is_not_introduced_for_out_of_range_write():
    port = make_port()
    port.open(IDENT)
    port.set_param(EXPOSURE, 1.0e12)  # вне 6.0..9999746.0: фейк не проверяет границы, kind="range" не вводится
    assert port.get_param(EXPOSURE) == 1.0e12
    port.close()


def test_failed_call_is_journaled_before_state_check():
    port = make_port()
    with pytest.raises(PortError) as exc_info:
        port.get_param(EXPOSURE)  # порт закрыт
    assert exc_info.value.kind == "closed"
    assert port.calls[-1][:2] == ("get_param", ("ExposureTime",))
