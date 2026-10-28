# -*- coding: utf-8 -*-
"""Режимы и загрузчик записей честного фейка порта (Task 1.5).

Только фейк: `make_port(**opts)` и `from_recording(path, **opts)`. Ожидаемые значения — литералы
из ACCEPTANCE задачи 1.5 и из записей `testing/recordings/*.json`, не вычисляются из кода под тестом.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from Services.camera_device.interface import Binding, DeviceIdentity, ParamInfo, PortError
from Services.camera_device.testing.fake_port import from_recording, make_port

REPO_ROOT = Path(__file__).resolve().parents[3]
MVS_RECORDING = "Services/camera_device/testing/recordings/mvs_MV-CS020-10GC.json"
MVCR_RECORDING = "Services/camera_device/testing/recordings/mvcr_ID3013.json"

IDENT = DeviceIdentity("serial", "FAKE-0001")
TRIGGER_MODE = Binding("genicam", "TriggerMode", "enum")
TRIGGER_SOURCE = Binding("genicam", "TriggerSource", "enum")
TRIGGER_PERIOD = Binding("genicam", "TriggerSelfTriggerPeriod", "int")
EXPOSURE = Binding("genicam", "ExposureTime", "float")


@pytest.fixture(autouse=True)
def _cwd_is_repo_root(monkeypatch):
    """`from_recording` принимает путь относительно корня репозитория: тест не зависит от cwd запуска."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture
def opened():
    """Фабрика: `opened(**opts)` -> порт фейка после `open(IDENT)`; на выходе все порты закрываются."""
    ports = []

    def factory(**opts):
        port = make_port(**opts)
        port.open(IDENT)
        ports.append(port)
        return port

    yield factory
    for port in ports:
        port.stop_grabbing()
        port.close()


def test_applied_but_error_changes_value_then_raises(opened):
    port = opened(applied_but_error=True)
    assert port.get_param(TRIGGER_MODE) == "Off"
    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_MODE, "On")
    assert exc_info.value.kind == "network"
    assert port.get_param(TRIGGER_MODE) == "On"


def test_neter_after_stop_rejects_writes_keeps_value_and_resets_on_reopen(opened):
    port = opened(neter_after_stop=True)
    port.set_param(TRIGGER_MODE, "On")
    port.start_grabbing()
    port.stop_grabbing()

    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_MODE, "Off")
    assert exc_info.value.kind == "network"
    assert exc_info.value.code == 0x80020206
    assert port.get_param(TRIGGER_MODE) == "On"
    assert port.describe_param(TRIGGER_MODE) is not None  # чтение и описание работают (H1)

    port.close()
    port.open(IDENT)
    assert port.get_param(TRIGGER_MODE) == "On"  # close/open значения узлов не сбрасывают
    port.set_param(TRIGGER_MODE, "Off")
    assert port.get_param(TRIGGER_MODE) == "Off"


@pytest.mark.parametrize(
    ("written", "stored"),
    [(1234.5, 1234.0), (1235.5, 1235.0), (1236.0, 1236.0)],
)
def test_float_node_with_inc_is_coerced_by_floor(opened, written, stored):
    port = opened()
    port.set_param(EXPOSURE, written)
    # 1235.5 -> 1235.0: банковское округление (round) дало бы 1236.0
    assert port.get_param(EXPOSURE) == pytest.approx(stored, abs=1e-9)


def test_closed_node_denies_read_until_its_parent_gets_the_value(opened):
    port = opened()
    with pytest.raises(PortError) as exc_info:
        port.get_param(TRIGGER_SOURCE)
    assert exc_info.value.kind == "access"
    assert exc_info.value.code == 0x80020106
    # describe_param на закрытом узле не бросает
    assert port.describe_param(TRIGGER_SOURCE).entries == ("Line0", "Software", "SelfTrigger")

    port.set_param(TRIGGER_MODE, "On")
    assert port.get_param(TRIGGER_SOURCE) == "Line0"

    # второй уровень цепочки PARENTS: период открывается, когда TriggerSource == SelfTrigger
    with pytest.raises(PortError) as exc_info:
        port.get_param(TRIGGER_PERIOD)  # пока Source == Line0, период закрыт
    assert exc_info.value.code == 0x80020106
    port.set_param(TRIGGER_SOURCE, "SelfTrigger")
    assert port.get_param(TRIGGER_PERIOD) == 300
    port.set_param(TRIGGER_PERIOD, 1000)
    assert port.get_param(TRIGGER_PERIOD) == 1000


def test_closed_node_write_is_denied_and_error_text_hides_the_value(opened):
    port = opened()
    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_PERIOD, 987654)
    assert exc_info.value.kind == "access"
    assert exc_info.value.code == 0x80020106
    assert "987654" not in str(exc_info.value)
    assert "987654" not in repr(exc_info.value)
    # записи не было: после открытия цепочки узел хранит умолчание, а не 987654
    port.set_param(TRIGGER_MODE, "On")
    port.set_param(TRIGGER_SOURCE, "SelfTrigger")
    assert port.get_param(TRIGGER_PERIOD) == 300


def test_journal_records_the_calling_thread_ident(opened):
    port = opened()
    seen: dict = {}

    def worker():
        seen["tid"] = threading.get_ident()
        try:
            port.set_param(EXPOSURE, 2000.0)
        except BaseException as exc:  # noqa: BLE001 - отдать тесту, не терять в потоке
            seen["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert "error" not in seen
    name, args, tid = port.calls[-1]
    assert name == "set_param"
    assert args == ("ExposureTime", 2000.0)
    assert tid == seen["tid"]
    assert tid != threading.get_ident()


def test_busy_for_s_refuses_open_until_the_deadline_passes():
    port = make_port(busy_for_s=0.3)
    with pytest.raises(PortError) as exc_info:
        port.open(IDENT)
    assert exc_info.value.kind == "busy"

    time.sleep(0.5)
    try:
        port.open(IDENT)
        assert port.get_param(EXPOSURE) == 10000.0  # порт действительно открыт
    finally:
        port.close()


def test_from_recording_mvs_serves_nodes_and_freezes_writes_while_grabbing():
    port = from_recording(MVS_RECORDING)
    port.open(DeviceIdentity("serial", "DA1689923"))
    try:
        assert port.get_param(EXPOSURE) == 40000.0
        assert port.describe_param(EXPOSURE) == ParamInfo(min=6.0, max=9999746.0, inc=None, entries=None, access="RW")
        assert port.describe_param(TRIGGER_MODE).entries == ("Off", "On")

        width = Binding("genicam", "Width", "int")
        port.start_grabbing()
        with pytest.raises(PortError) as exc_info:
            port.set_param(width, 1620)
        assert exc_info.value.kind == "access"
        assert exc_info.value.code == 0x80000106
        assert port.get_param(width) == 1624
    finally:
        port.stop_grabbing()
        port.close()


def test_from_recording_mvcr_accepts_null_values_and_idle_only_states():
    port = from_recording(MVCR_RECORDING)
    port.open(DeviceIdentity("serial", "00DB2156580"))
    try:
        assert port.get_param(EXPOSURE) == 799.0
        assert port.describe_param(TRIGGER_PERIOD).min == 32
        with pytest.raises(PortError) as exc_info:
            port.get_param(Binding("genicam", "RunningMode", "enum"))  # value: null при rc=0
        assert exc_info.value.kind == "other"
    finally:
        port.close()


def test_from_recording_rejects_unknown_schema_version_without_echoing_it(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 7777}', encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:  # не KeyError: версия проверяется первой
        from_recording(bad)
    assert "schema_version" in str(exc_info.value)
    assert "7777" not in str(exc_info.value)
