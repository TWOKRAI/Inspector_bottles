"""Task 0.4: зонд MVS (tools/mvs_probe.py) на FakeMvCamera.

Ожидаемые значения -- литералы из схемы recording-schema.md и из заголовков SDK
(0x80000106 = MV_E_GC_ACCESS, MvErrorDefine.h:55), не выводятся из кода зонда.
Фейк живёт в самом зонде: тест берёт его оттуда, инструмент не импортирует tests/.
"""

from __future__ import annotations

import inspect
import json
import threading
from pathlib import Path

import pytest

from Services.hikvision_camera.sdk.bindings import MvCamera
from Services.hikvision_camera.sdk.constants import MV_GIGE_DEVICE
from Services.hikvision_camera.sdk.structures import MV_CC_DEVICE_INFO
from Services.hikvision_camera.tools import mvs_probe


def run(argv: list[str], camera=None, capsys=None):
    """Запуск main на фейке; возвращает (код выхода, строки stdout, камера)."""
    cam = camera or mvs_probe.FakeMvCamera()
    rc = mvs_probe.main([*argv, "--fake"], backend=mvs_probe.FakeBackend(cam))
    lines = capsys.readouterr().out.splitlines() if capsys else []
    return rc, lines, cam


def names(cam) -> list[str]:
    return [n for n, _ in cam.calls]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- dump


def test_dump_fake_даёт_json_схемы(tmp_path, capsys):
    out = tmp_path / "t.json"
    rc, lines, _ = run(["--dump", "--out", str(out)], capsys=capsys)
    assert rc == 0
    assert lines[0] == "devices=1"  # перечислить до вопроса (feedback_a_probe_must_enumerate_before_it_asks)
    doc = read_json(out)
    assert doc["schema_version"] == 1
    assert doc["vendor"] == "mvs"
    assert doc["sdk_version"] == "0x04020003"
    assert doc["states"] == ["idle", "grabbing"]
    assert set(doc["device"]) == {"model", "serial"}
    nodes = doc["nodes"]
    assert list(nodes) == [
        "TriggerMode", "TriggerSource", "ExposureTime", "ExposureAuto", "Gain", "GainAuto",
        "AcquisitionFrameRate", "AcquisitionFrameRateEnable", "Width", "Height", "PixelFormat",
        "GevSCPSPacketSize", "GevSCPD", "DeviceSerialNumber", "DeviceModelName",
    ]  # fmt: skip
    exp = nodes["ExposureTime"]
    assert exp["type"] == "float"
    assert exp["min"] == 15.0
    assert exp["max"] == 9999500.0
    assert exp["inc"] is None
    assert exp["entries"] is None
    trig = nodes["TriggerMode"]
    assert trig["type"] == "enum"
    assert trig["entries"] == ["Off", "On"]
    assert trig["entry_values"] == [0, 1]
    assert nodes["Width"]["type"] == "int"
    assert (nodes["Width"]["min"], nodes["Width"]["max"], nodes["Width"]["inc"]) == (64, 4096, 8)
    assert nodes["AcquisitionFrameRateEnable"]["type"] == "bool"
    assert nodes["DeviceSerialNumber"]["type"] == "string"
    for name, node in nodes.items():
        for state in ("idle", "grabbing"):
            assert set(node[state]) == {"value", "access", "rc"}, (name, state)
    assert trig["idle"] == {"value": "Off", "access": "RW", "rc": "0x00000000"}
    assert nodes["DeviceSerialNumber"]["idle"]["value"] == "FAKE0001"
    # Width во время захвата заперт: доступ RO (так в GenICam при TLParamsLocked)
    assert nodes["Width"]["idle"]["access"] == "RW"
    assert nodes["Width"]["grabbing"]["access"] == "RO"


def test_dump_не_удался_старт_захвата_только_idle(tmp_path, capsys):
    out = tmp_path / "t.json"
    cam = mvs_probe.FakeMvCamera(start_rc=0x80000007)
    rc, _, _ = run(["--dump", "--out", str(out)], cam, capsys)
    assert rc == 0
    doc = read_json(out)
    assert doc["states"] == ["idle"]
    assert all("grabbing" not in node for node in doc["nodes"].values())


def test_dump_узла_нет_access_NI_и_код(tmp_path, capsys):
    out = tmp_path / "t.json"
    cam = mvs_probe.FakeMvCamera(missing=("GevSCPD",))
    rc, _, _ = run(["--dump", "--out", str(out)], cam, capsys)
    assert rc == 0
    node = read_json(out)["nodes"]["GevSCPD"]
    assert node["type"] is None
    assert node["idle"] == {"value": None, "access": "NI", "rc": "0x80000100"}


# --------------------------------------------------------------------------- только чтение


@pytest.mark.parametrize("experiment", ["h1", "h2", "h5"])
def test_без_write_нет_ни_одного_Set(experiment, capsys):
    rc, lines, cam = run(["--experiment", experiment, "--seconds", "0"], capsys=capsys)
    assert rc == 0
    assert [n for n in names(cam) if n.startswith("MV_CC_Set") and n != "MV_CC_SetCommandValue"] == []
    assert "MV_CC_SetCommandValue" not in names(cam)
    assert any(line.startswith("skip write node=") for line in lines)


def test_dump_без_Set(tmp_path, capsys):
    _, _, cam = run(["--dump", "--out", str(tmp_path / "t.json")], capsys=capsys)
    assert not [n for n in names(cam) if n.startswith("MV_CC_Set")]


def test_write_без_orig_отказ_и_нет_Set(capsys):
    rc, lines, cam = run(["--experiment", "h1", "--write"], capsys=capsys)
    assert rc == 1
    assert not [n for n in names(cam) if n.startswith("MV_CC_Set")]


# --------------------------------------------------------------------------- исходные до записи


class OrderCam(mvs_probe.FakeMvCamera):
    """Фиксирует, был ли файл --orig на диске в момент первого MV_CC_Set*."""

    def __init__(self, orig_path: Path, **kw):
        super().__init__(**kw)
        self.orig_path = orig_path
        self.orig_at_first_set = None  # None: Set не было; False: файла не было; dict: содержимое

    def _journal(self, name, args):
        super()._journal(name, args)
        if name.startswith("MV_CC_Set") and self.orig_at_first_set is None:
            p = self.orig_path
            self.orig_at_first_set = json.loads(p.read_text(encoding="utf-8")) if p.exists() else False


def test_write_сохраняет_исходные_до_записи(tmp_path, capsys):
    orig = tmp_path / "o.json"
    cam = OrderCam(orig)
    rc, _, _ = run(
        ["--experiment", "h1", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"], cam, capsys
    )
    assert rc == 0
    saved = cam.orig_at_first_set
    assert saved, "к первому MV_CC_Set* файл --orig уже должен лежать на диске"
    assert saved["schema_version"] == 1
    assert saved["states"] == ["idle"]
    assert list(saved["nodes"]) == ["TriggerMode"]  # только узлы, которые опыт будет писать
    assert saved["nodes"]["TriggerMode"]["idle"]["value"] == "Off"
    assert "grabbing" not in saved["nodes"]["TriggerMode"]


# --------------------------------------------------------------------------- H1


def test_h1_возвращает_исходное(tmp_path, capsys):
    orig = tmp_path / "o.json"
    argv = ["--experiment", "h1", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"]
    rc, lines, cam = run(argv, capsys=capsys)
    assert rc == 0
    node_lines = [ln for ln in lines if ln.startswith("node=TriggerMode ")]
    assert len(node_lines) == 1
    assert node_lines[0].startswith("node=TriggerMode rc=0x00000000 read=On ms=")
    assert " thread=MainThread" in node_lines[0]
    restore = [ln for ln in lines if ln.startswith("restore node=TriggerMode ")]
    assert len(restore) == 1
    assert restore[0].startswith("restore node=TriggerMode rc=0x00000000 read=Off")
    assert lines.index(node_lines[0]) < lines.index(restore[0])
    # итоговое значение в фейке равно значению из o.json
    assert read_json(orig)["nodes"]["TriggerMode"]["idle"]["value"] == "Off"
    assert cam.value("TriggerMode") == "Off"
    assert not any(ln.startswith("RESTORE MISMATCH") for ln in lines)
    # запись после StopGrabbing, возврат -- тоже после него (камера простаивает)
    n = names(cam)
    stop = n.index("MV_CC_StopGrabbing")
    sets = [i for i, x in enumerate(n) if x.startswith("MV_CC_Set")]
    assert len(sets) == 2 and min(sets) > stop
    assert n[-2:] == ["MV_CC_CloseDevice", "MV_CC_DestroyHandle"]


def test_h1_задержка_идёт_между_стопом_и_записью(tmp_path, capsys, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(mvs_probe.time, "sleep", sleeps.append)
    orig = tmp_path / "o.json"
    run(["--experiment", "h1", "--write", "--orig", str(orig), "--delay", "1.0", "--seconds", "0"], capsys=capsys)
    assert 1.0 in sleeps


# --------------------------------------------------------------------------- возврат


def test_restore_mismatch_код_2(tmp_path, capsys):
    orig = tmp_path / "o.json"
    cam = mvs_probe.FakeMvCamera(swallow=(("TriggerMode", 0),))  # запись Off принимается, но не ложится
    argv = ["--experiment", "h1", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"]
    rc, lines, _ = run(argv, cam, capsys)
    assert rc == 2
    assert "RESTORE MISMATCH node=TriggerMode want=Off got=On" in lines
    assert cam.value("TriggerMode") == "On"


def test_режим_restore_возвращает_из_файла(tmp_path, capsys):
    orig = tmp_path / "o.json"
    stuck = mvs_probe.FakeMvCamera(swallow=(("TriggerMode", 0),))
    argv = ["--experiment", "h1", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"]
    assert run(argv, stuck, capsys)[0] == 2
    # камера осталась в On; новый запуск только возврата тем же файлом
    cam = mvs_probe.FakeMvCamera(values={"TriggerMode": "On"})
    rc, lines, cam = run(["--restore", str(orig)], cam, capsys)
    assert rc == 0
    assert cam.value("TriggerMode") == "Off"
    assert any(ln.startswith("restore node=TriggerMode rc=0x00000000 read=Off") for ln in lines)
    assert "MV_CC_StartGrabbing" not in names(cam)


def test_restore_неизвестная_версия_схемы_текст_без_значения(tmp_path, capsys):
    bad = tmp_path / "o.json"
    bad.write_text(json.dumps({"schema_version": 77, "nodes": {}}), encoding="utf-8")
    rc, lines, cam = run(["--restore", str(bad)], capsys=capsys)
    assert rc == 1
    text = "\n".join(lines)
    assert "schema_version" in text
    assert "77" not in text
    assert not [n for n in names(cam) if n.startswith("MV_CC_Set")]


# --------------------------------------------------------------------------- H5


def test_h5_width_при_захвате_даёт_код(tmp_path, capsys):
    orig = tmp_path / "o.json"
    argv = ["--experiment", "h5", "--write", "--orig", str(orig), "--seconds", "0"]
    rc, lines, cam = run(argv, capsys=capsys)
    assert rc == 0  # запись отказала, restore прочитал значение == --orig: это не расхождение
    node_lines = [ln for ln in lines if ln.startswith("node=Width ")]
    assert len(node_lines) == 1
    assert node_lines[0].startswith("node=Width rc=0x80000106 read=2448 ms=")
    assert any(ln.startswith("restore node=Width rc=0x00000000 read=2448") for ln in lines)
    assert cam.value("Width") == 2448
    assert list(read_json(orig)["nodes"]) == ["Width"]
    n = names(cam)
    sets = [i for i, x in enumerate(n) if x.startswith("MV_CC_Set")]
    start, stop = n.index("MV_CC_StartGrabbing"), n.index("MV_CC_StopGrabbing")
    assert start < sets[0] < stop < sets[1]  # запись -- при захвате, возврат -- после StopGrabbing


# --------------------------------------------------------------------------- H2 и потоки


def test_h2_split_потоки_разные_и_присоединены(tmp_path, capsys):
    orig = tmp_path / "o.json"
    argv = ["--experiment", "h2", "--mode", "split", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"]
    rc, lines, cam = run(argv, capsys=capsys)
    assert rc == 0
    write_line = next(ln for ln in lines if ln.startswith("node=TriggerMode "))
    restore_line = next(ln for ln in lines if ln.startswith("restore node=TriggerMode "))
    assert write_line.endswith("thread=A-open")
    assert restore_line.endswith("thread=B-capture")
    assert cam.value("TriggerMode") == "Off"
    live = {t.name for t in threading.enumerate()}
    assert not live & {"A-open", "B-capture"}  # join до выхода


def test_h2_same_всё_в_главном_потоке(tmp_path, capsys):
    orig = tmp_path / "o.json"
    argv = ["--experiment", "h2", "--mode", "same", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"]
    rc, lines, _ = run(argv, capsys=capsys)
    assert rc == 0
    assert all(ln.endswith("thread=MainThread") for ln in lines if ln.startswith(("node=", "restore node=")))


def test_split_только_для_h2(capsys):
    rc, _, cam = run(["--experiment", "h1", "--mode", "split"], capsys=capsys)
    assert rc == 1
    assert "MV_CC_OpenDevice" not in names(cam)


def test_ошибка_в_потоке_не_теряется_и_возврат_идёт(tmp_path, capsys):
    orig = tmp_path / "o.json"
    cam = mvs_probe.FakeMvCamera(start_rc=0x80000007)
    argv = ["--experiment", "h2", "--mode", "split", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "0"]
    rc, lines, cam = run(argv, cam, capsys)
    assert rc == 1  # StartGrabbing отказал -> опыт не состоялся
    assert cam.value("TriggerMode") == "Off"  # запись до старта возвращена
    assert any(ln.startswith("restore node=TriggerMode") for ln in lines)


def test_сбой_при_захвате_стоп_до_возврата(tmp_path, capsys, monkeypatch):
    def boom(_seconds):
        raise RuntimeError("сбой посреди захвата")

    monkeypatch.setattr(mvs_probe.time, "sleep", boom)
    orig = tmp_path / "o.json"
    argv = ["--experiment", "h2", "--write", "--orig", str(orig), "--delay", "0", "--seconds", "1"]
    rc, lines, cam = run(argv, capsys=capsys)
    assert rc == 1
    assert cam.value("TriggerMode") == "Off"
    n = names(cam)
    sets = [i for i, x in enumerate(n) if x.startswith("MV_CC_Set")]
    assert len(sets) == 2
    assert n.index("MV_CC_StopGrabbing") < sets[1]  # возврат на простаивающей камере
    assert n[-2:] == ["MV_CC_CloseDevice", "MV_CC_DestroyHandle"]


# --------------------------------------------------------------------------- выбор камеры


def test_выбор_по_serial_и_ip(tmp_path, capsys):
    out = tmp_path / "t.json"
    assert run(["--dump", "--out", str(out), "--serial", "FAKE0001"], capsys=capsys)[0] == 0
    assert run(["--dump", "--out", str(out), "--ip", "192.168.1.10"], capsys=capsys)[0] == 0


def test_нет_такой_камеры_код_1_и_devices_первой_строкой(tmp_path, capsys):
    rc, lines, cam = run(["--dump", "--out", str(tmp_path / "t.json"), "--serial", "NOPE"], capsys=capsys)
    assert rc == 1
    assert lines[0] == "devices=1"
    assert "MV_CC_OpenDevice" not in names(cam)
    assert not (tmp_path / "t.json").exists()


def test_ip_и_серийник_из_структуры_SDK():
    info = MV_CC_DEVICE_INFO()
    info.nTLayerType = MV_GIGE_DEVICE
    gi = info.SpecialInfo.stGigEInfo
    gi.nCurrentIp = 0xC0A8010A
    for i, b in enumerate(b"K12345"):
        gi.chSerialNumber[i] = b
    for i, b in enumerate(b"MV-CS050"):
        gi.chModelName[i] = b
    entry = mvs_probe.entry_from_info(info)
    assert (entry.serial, entry.ip, entry.model) == ("K12345", "192.168.1.10", "MV-CS050")


# --------------------------------------------------------------------------- фейк == настоящий MvCamera


def _params(fn) -> list[str]:
    return [p for p in inspect.signature(fn).parameters if p != "self"]


def test_фейк_повторяет_сигнатуры_MvCamera():
    fake_methods = [n for n in dir(mvs_probe.FakeMvCamera) if n.startswith("MV_")]
    assert fake_methods, "в фейке нет ни одного MV_* метода"
    for name in fake_methods:
        real = getattr(MvCamera, name, None)
        assert real is not None, f"в MvCamera нет {name}"
        assert _params(getattr(mvs_probe.FakeMvCamera, name)) == _params(real), name


def test_всё_что_зонд_зовёт_есть_в_фейке_и_в_MvCamera():
    for name in mvs_probe.USED_CAMERA_METHODS:
        assert hasattr(MvCamera, name), name
        assert hasattr(mvs_probe.FakeMvCamera, name), name


def test_настоящий_MvCamera_читает_через_зонд_на_фейковой_DLL(monkeypatch):
    """Один тест на реальных объектах: read_node поверх настоящих обёрток MvCamera и фейковой DLL (без железа)."""
    from Services.hikvision_camera.sdk import bindings

    seen: list[str] = []

    class Func:
        def __init__(self, name):
            self.name, self.argtypes, self.restype = name, None, None

        def __call__(self, *args):
            seen.append(self.name)
            out = args[2]._obj  # byref(выходная структура)
            if self.name == "MV_XML_GetNodeInterfaceType":
                out.value = 2  # IFT_IInteger
            elif self.name == "MV_XML_GetNodeAccessMode":
                out.value = 4  # AM_RW
            elif self.name == "MV_CC_GetIntValueEx":
                out.nCurValue, out.nMax, out.nMin, out.nInc = 2448, 4096, 64, 8
            return 0

    class Dll:
        def __getattr__(self, name):
            return Func(name)

    monkeypatch.setattr(bindings, "_MvCamCtrldll", Dll())
    node = mvs_probe.read_node(MvCamera(), "Width")
    assert seen == ["MV_XML_GetNodeInterfaceType", "MV_XML_GetNodeAccessMode", "MV_CC_GetIntValueEx"]
    assert (node["type"], node["access"], node["value"]) == ("int", "RW", 2448)
    assert (node["min"], node["max"], node["inc"]) == (64, 4096, 8)
