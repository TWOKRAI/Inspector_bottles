# -*- coding: utf-8 -*-
"""Hazard-тесты фейка порта (Task 1.5, автор — исполнитель): то, что слепой тестер не уместил в лимит.

Ожидаемые значения — литералы из DESIGN задачи 1.5, не вычисляются из кода под тестом.
"""

from __future__ import annotations

import ast
import json
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


def test_write_while_grabbing_to_non_live_node_is_denied_and_value_kept():
    port = make_port()
    port.open(IDENT)
    port.start_grabbing()
    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_MODE, "On")
    assert exc_info.value.kind == "access"
    assert exc_info.value.code == 0x80000106
    assert port.get_param(TRIGGER_MODE) == "Off"
    port.stop_grabbing()
    port.close()


def test_live_write_to_exposure_while_grabbing_is_floor_coerced():
    port = make_port()
    port.open(IDENT)
    port.start_grabbing()
    port.set_param(EXPOSURE, 2000.5)  # live только у ExposureTime
    assert port.get_param(EXPOSURE) == 2000.0
    port.stop_grabbing()
    port.close()


def test_closed_node_check_precedes_neter_after_stop():
    port = make_port(neter_after_stop=True)
    port.open(IDENT)
    port.start_grabbing()
    port.stop_grabbing()
    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_SOURCE, "Software")  # TriggerMode == Off: узел закрыт
    assert exc_info.value.kind == "access"
    assert exc_info.value.code == 0x80020106
    port.close()


@pytest.mark.parametrize("grabbing", [False, True])
def test_open_while_already_open_is_other_error_and_port_stays_usable(grabbing):
    port = make_port()
    port.open(IDENT)
    if grabbing:
        port.start_grabbing()
    with pytest.raises(PortError) as exc_info:
        port.open(IDENT)
    assert exc_info.value.kind == "other"
    assert port.get_param(EXPOSURE) == 10000.0  # состояние не сброшено
    if grabbing:
        assert port.get_frame(100).frame_num == 1  # захват продолжается
    port.stop_grabbing()
    port.close()


_FORBIDDEN_ROOTS = ("Services.code_reader", "Services.hikvision_camera")
_FORBIDDEN_NAMES = ("code_reader", "hikvision_camera")


def _is_forbidden(module: str) -> bool:
    return any(module == root or module.startswith(root + ".") for root in _FORBIDDEN_ROOTS)


def _vendor_import_violations(source: str, package: str = "Services.camera_device") -> list[str]:
    """Импорты вендорских пакетов: `import Services.code_reader...`, `from Services.hikvision_camera... import`,
    `from Services import code_reader|hikvision_camera` и относительные формы тех же.

    `package` — пакет файла-источника (для разрешения `from ..code_reader import x`).
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if _is_forbidden(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                base_parts = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                module = ".".join([*base_parts, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if _is_forbidden(module):
                found.append(module)
            elif module == "Services":
                found.extend(f"Services.{a.name}" for a in node.names if a.name in _FORBIDDEN_NAMES)
    return found


def test_layer_detector_finds_vendor_imports_in_synthetic_sources():
    # позитивный контроль: без него тест слоёв ниже вакуумен
    assert _vendor_import_violations("from Services.hikvision_camera.sdk import structures") == [
        "Services.hikvision_camera.sdk"
    ]
    assert _vendor_import_violations("import Services.code_reader.core") == ["Services.code_reader.core"]
    assert _vendor_import_violations("from Services import code_reader") == ["Services.code_reader"]
    assert _vendor_import_violations("from Services.camera_device import interface\nimport json") == []
    # относительные формы из Services/camera_device/x.py (пакет Services.camera_device)
    assert _vendor_import_violations("from ..code_reader import driver", "Services.camera_device") == [
        "Services.code_reader"
    ]
    assert _vendor_import_violations("from .. import hikvision_camera", "Services.camera_device") == [
        "Services.hikvision_camera"
    ]
    # из подпакета Services/camera_device/testing/x.py: уровень 3 -> Services
    assert _vendor_import_violations("from ... import code_reader", "Services.camera_device.testing") == [
        "Services.code_reader"
    ]
    assert _vendor_import_violations("from . import interface", "Services.camera_device") == []


def test_core_package_does_not_import_vendor_packages():
    core = REPO_ROOT / "Services" / "camera_device"
    files = [p for p in core.rglob("*.py") if "recordings" not in p.relative_to(core).parts]
    assert len(files) >= 6  # обход действительно что-то нашёл
    for path in files:
        package = ".".join(path.parent.relative_to(REPO_ROOT).parts)
        assert _vendor_import_violations(path.read_text(encoding="utf-8"), package) == [], str(path)


def _write_recording(tmp_path, nodes, *, bom=False):
    path = tmp_path / "rec.json"
    text = json.dumps({"schema_version": 1, "vendor": "t", "sdk_version": None, "states": ["idle"], **nodes})
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


_TRIGGER_NODES = {
    "nodes": {
        "TriggerMode": {
            "type": "enum", "min": None, "max": None, "inc": None, "entries": ["Off", "On"],
            "idle": {"value": "Off", "access": "RW", "rc": "0x00000000"},
            "grabbing": {"value": "Off", "access": "RO", "rc": "0x00000000"},
        },
        "TriggerSource": {
            "type": "enum", "min": None, "max": None, "inc": None, "entries": ["Line0", "Software"],
            "idle": {"value": "Line0", "access": "NA", "rc": "0x80020106"},
            "grabbing": {"value": "Line0", "access": "NA", "rc": "0x80020106"},
        },
    }
}  # fmt: skip


def test_loader_accepts_utf8_bom(tmp_path):
    port = from_recording(_write_recording(tmp_path, _TRIGGER_NODES, bom=True))
    port.open(IDENT)
    assert port.get_param(TRIGGER_MODE) == "Off"
    port.close()


def test_loader_without_nodes_key_is_value_error_naming_nodes(tmp_path):
    path = tmp_path / "nonodes.json"
    path.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        from_recording(path)
    assert "nodes" in str(exc_info.value)


def test_node_opened_by_parent_stays_readable_while_grabbing_when_record_says_na(tmp_path):
    port = from_recording(_write_recording(tmp_path, _TRIGGER_NODES))
    port.open(IDENT)
    port.set_param(TRIGGER_MODE, "On")  # открывает TriggerSource
    port.start_grabbing()
    assert port.get_param(TRIGGER_SOURCE) == "Line0"  # не закрывается снова из-за grabbing.access == NA
    with pytest.raises(PortError) as exc_info:
        port.set_param(TRIGGER_SOURCE, "Software")  # при захвате без live запись отказана
    assert exc_info.value.code == 0x80000106
    port.stop_grabbing()
    port.close()
