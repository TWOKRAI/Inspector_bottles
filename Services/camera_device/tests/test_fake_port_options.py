# -*- coding: utf-8 -*-
"""Тесты опций фейка порта для сеанса (Task 2.1, шаг 1; автор — исполнитель, до слепого тестера).

Опции: `open_delay_s`, `frame_period_s`, `get_frame_hang_s` (+ `arm_hang`), `get_frame_errors`, `get_frame_script`.
Ожидаемые значения — литералы из DESIGN задачи 2.1, не вычисляются из кода под тестом.
Тесты с ожиданием идут в daemon-потоке с дедлайном `join`: зависший фейк не вешает набор.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from Services.camera_device.interface import Binding, DeviceIdentity, PortError
from Services.camera_device.testing.fake_port import from_recording, make_port

REPO_ROOT = Path(__file__).resolve().parents[3]
MVCR_RECORDING = REPO_ROOT / "Services/camera_device/testing/recordings/mvcr_ID3013.json"
MVS_RECORDING = REPO_ROOT / "Services/camera_device/testing/recordings/mvs_MV-CS020-10GC.json"
IDENT = DeviceIdentity("serial", "FAKE-0001")


def _grabbing(**opts):
    port = make_port(**opts)
    port.open(IDENT)
    port.start_grabbing()
    return port


def _timed(fn, deadline: float = 2.0):
    """Вызвать `fn` в daemon-потоке; вернуть (результат, секунды). Не уложился в дедлайн — тест падает."""
    box: dict = {}

    def run() -> None:
        t0 = time.perf_counter()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается вызывающему тесту
            box["error"] = exc
        box["seconds"] = time.perf_counter() - t0

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box["result"], box["seconds"]


def test_умолчания_get_frame_мгновенный():
    port = _grabbing()
    frames, seconds = _timed(lambda: [port.get_frame(500), port.get_frame(500)])
    assert [f.frame_num for f in frames] == [1, 2]
    assert seconds < 0.1


def test_open_пишет_журнал_до_сна_и_занимает_open_delay():
    port = make_port(open_delay_s=0.3)
    worker = threading.Thread(target=lambda: port.open(IDENT), daemon=True)
    t0 = time.perf_counter()
    worker.start()
    deadline = time.monotonic() + 1.0
    while not [c for c in port.calls if c[0] == "open"] and time.monotonic() < deadline:
        time.sleep(0.005)
    assert [c[0] for c in port.calls] == ["open"]
    assert worker.is_alive(), "запись `open` должна появиться ДО сна"
    worker.join(1.0)
    assert not worker.is_alive()
    assert time.perf_counter() - t0 >= 0.3


def test_frame_period_большой_get_frame_ждёт_timeout_и_отдаёт_None():
    port = _grabbing(frame_period_s=10.0)
    frame, seconds = _timed(lambda: port.get_frame(100))
    assert frame is None
    assert 0.1 <= seconds < 0.4


def test_frame_period_малый_get_frame_ждёт_следующего_кадра():
    port = _grabbing(frame_period_s=0.05)
    frame, seconds = _timed(lambda: port.get_frame(500))
    assert frame is not None
    assert frame.frame_num == 1
    assert 0.04 <= seconds < 0.3


def test_frame_period_малый_кадр_внутри_timeout_никогда_не_отдаётся_как_None():
    # Грубые часы Windows (шаг 15,6 мс): сон мог закончиться раньше срока кадра по часам,
    # и get_frame отдавал None, хотя кадр наступал внутри timeout_ms. Настоящий SDK ждал бы кадр.
    port = _grabbing(frame_period_s=0.05)
    frames, _ = _timed(lambda: [port.get_frame(500) for _ in range(30)], deadline=10.0)
    assert [f is None for f in frames].count(True) == 0
    assert [f.frame_num for f in frames] == list(range(1, 31))


def test_hang_разовый_а_arm_hang_взводит_повторно():
    port = _grabbing(get_frame_hang_s=0.25)
    first, seconds = _timed(lambda: port.get_frame(10))  # timeout_ms игнорируется
    assert first is not None
    assert seconds >= 0.25
    second, seconds = _timed(lambda: port.get_frame(10))
    assert second is not None
    assert seconds < 0.1
    port.arm_hang(0.15)
    third, seconds = _timed(lambda: port.get_frame(10))
    assert third is not None
    assert 0.15 <= seconds < 0.4


def test_get_frame_errors_N_ошибок_затем_кадр_и_заново_после_start_grabbing():
    port = _grabbing(get_frame_errors=2)
    for _ in range(2):
        with pytest.raises(PortError) as exc_info:
            port.get_frame(10)
        assert (exc_info.value.kind, exc_info.value.where) == ("other", "get_frame")
    assert port.get_frame(10) is not None
    port.stop_grabbing()
    port.start_grabbing()  # счёт «первых N вызовов» идёт заново
    with pytest.raises(PortError):
        port.get_frame(10)


def test_get_frame_script_последовательность_затем_кадры():
    port = _grabbing(get_frame_script=("err", "none", "err", "none", "err"))
    seen: list[str] = []
    for _ in range(5):
        try:
            seen.append("none" if port.get_frame(10) is None else "frame")
        except PortError:
            seen.append("err")
    assert seen == ["err", "none", "err", "none", "err"]
    assert port.get_frame(10) is not None  # после сценария — обычные кадры


def test_get_frame_script_none_без_ожидания_и_frame_без_ожидания():
    port = _grabbing(frame_period_s=10.0, get_frame_script=("none", "frame"))
    results, seconds = _timed(lambda: [port.get_frame(500), port.get_frame(500)])
    assert results[0] is None
    assert results[1] is not None
    assert seconds < 0.1


def test_get_frame_errors_равно_script_из_err():
    by_count = _grabbing(get_frame_errors=3)
    by_script = _grabbing(get_frame_script=("err",) * 3)
    for port in (by_count, by_script):
        for _ in range(3):
            with pytest.raises(PortError):
                port.get_frame(10)
        assert port.get_frame(10) is not None


def test_журнал_по_прежнему_имя_args_thread_id():
    port = make_port(get_frame_script=("err", "none"))
    me = threading.get_ident()
    port.open(IDENT)
    port.start_grabbing()
    with pytest.raises(PortError):
        port.get_frame(10)
    port.get_frame(20)
    port.get_frame(30)
    port.stop_grabbing()
    port.close()
    assert [(name, args) for name, args, _ in port.calls] == [
        ("open", ("serial", "FAKE-0001")),
        ("start_grabbing", ()),
        ("get_frame", (10,)),
        ("get_frame", (20,)),
        ("get_frame", (30,)),
        ("stop_grabbing", ()),
        ("close", ()),
    ]
    assert {tid for _, _, tid in port.calls} == {me}


def test_неизвестный_шаг_сценария_отвергается():
    with pytest.raises(ValueError):
        make_port(get_frame_script=("err", "boom"))


def test_from_recording_принимает_те_же_опции():
    port = from_recording(MVCR_RECORDING, get_frame_errors=1, frame_period_s=0.01, open_delay_s=0.0)
    port.open(DeviceIdentity("serial", "00DB2156580"))
    port.start_grabbing()
    with pytest.raises(PortError):
        port.get_frame(10)
    assert port.get_frame(100) is not None


# --- read_offset (Task 2.2, шаг 1): чтение = записанное + смещение для числовых узлов ---------------------

TRIGGER_MODE = Binding("genicam", "TriggerMode", "enum")
TRIGGER_SOURCE = Binding("genicam", "TriggerSource", "enum")
PERIOD = Binding("genicam", "TriggerSelfTriggerPeriod", "int")
EXPOSURE = Binding("genicam", "ExposureTime", "float")


def _open_period(port) -> None:
    """Открыть закрытый узел периода: TriggerMode=On -> TriggerSource=SelfTrigger (правило родителей фейка)."""
    port.open(IDENT)
    port.set_param(TRIGGER_MODE, "On")
    port.set_param(TRIGGER_SOURCE, "SelfTrigger")


def test_read_offset_умолчание_чтение_равно_записи():
    port = make_port()
    _open_period(port)
    port.set_param(PERIOD, 40)
    port.set_param(EXPOSURE, 2000.0)
    assert port.get_param(PERIOD) == 40
    assert port.get_param(EXPOSURE) == 2000.0
    assert port.get_param(TRIGGER_MODE) == "On"


def test_read_offset_int_узел_записано_40_прочитано_41_внутреннее_значение_не_меняется():
    port = make_port(read_offset={"TriggerSelfTriggerPeriod": 1})
    _open_period(port)
    port.set_param(PERIOD, 40)
    assert port.get_param(PERIOD) == 41
    assert port.get_param(PERIOD) == 41  # смещение не накапливается: внутреннее значение осталось 40
    other = make_port()
    _open_period(other)
    other.set_param(PERIOD, 40)
    assert other._nodes["TriggerSelfTriggerPeriod"].value == 40 == port._nodes["TriggerSelfTriggerPeriod"].value


def test_read_offset_float_узел_из_записи_mvs():
    port = from_recording(MVS_RECORDING, read_offset={"ExposureTime": 1e-7})
    port.open(IDENT)
    port.set_param(EXPOSURE, 2000.0)  # inc=None: шага у узла нет
    assert port.get_param(EXPOSURE) == 2000.0 + 1e-7
    assert port._nodes["ExposureTime"].value == 2000.0


def test_read_offset_enum_узел_смещение_игнорируется():
    port = make_port(read_offset={"TriggerMode": 5, "TriggerSource": 1.5})
    port.open(IDENT)
    port.set_param(TRIGGER_MODE, "On")
    assert port.get_param(TRIGGER_MODE) == "On"


def test_read_offset_только_для_ключей_из_словаря():
    port = make_port(read_offset={"TriggerSelfTriggerPeriod": 1})
    _open_period(port)
    port.set_param(EXPOSURE, 2000.0)
    assert port.get_param(EXPOSURE) == 2000.0  # у ExposureTime смещения нет


def test_read_offset_журнал_get_param_по_прежнему_имя_args_thread_id():
    port = make_port(read_offset={"ExposureTime": 1.0})
    port.open(IDENT)
    port.get_param(EXPOSURE)
    assert [(name, args) for name, args, _ in port.calls] == [
        ("open", ("serial", "FAKE-0001")),
        ("get_param", ("ExposureTime",)),
    ]
    assert port.calls[1][2] == threading.get_ident()


def test_read_offset_from_recording_умолчание_пусто():
    port = from_recording(MVS_RECORDING)
    port.open(IDENT)
    port.set_param(EXPOSURE, 2000.0)
    assert port.get_param(EXPOSURE) == 2000.0
