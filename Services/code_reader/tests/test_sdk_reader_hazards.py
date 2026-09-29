# -*- coding: utf-8 -*-
"""Авторские тесты опасных мест ``SdkCodeReader`` — то, чего слепой набор не видит.

1. ``stop()`` из ``on_frame``: поток захвата не может ждать сам себя (``join`` своего
   потока — RuntimeError, а ожидание под ``_life`` — взаимоблокировка).
2. ``get_frame`` висит дольше дедлайна ``stop()`` (SDK не уважил свой таймаут): ``stop()``
   обязан вернуться в срок и НЕ закрывать handle под идущим вызовом; закрыть должен сам
   поток, когда вызов вернётся, ровно один раз; повторный ``start()`` до этого — отказ,
   иначе второе открытие наложилось бы на живой первый handle.
3. Находки ревью 6.2 (итерация 1), по тесту на каждую: поздний кадр после ``stop()``,
   ``__notes__`` в тексте ошибки, внешний ``stop()`` против ``stop()`` из колбэка,
   ``start()`` при умирающем после сбоя потоке и из ``on_error``.

Всё, что может зависнуть, идёт в daemon-потоке с дедлайном (pytest-timeout не активен).
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from Services.code_reader.core.sdk_reader import SdkCodeReader
from Services.code_reader.sdk.api import RawFrame
from Services.code_reader.sdk.errors import SdkError


def _raw(trigger: int) -> RawFrame:
    return RawFrame(
        image=b"",
        width=1,
        height=1,
        pixel_type=0x01080001,
        trigger_index=trigger,
        frame_num=trigger,
        no_read_num=0,
        codes=(),
    )


class _Api:
    def __init__(self, frames=(), gate: threading.Event | None = None) -> None:
        self.entry = SimpleNamespace(ip="10.0.0.1", model="M", serial="S", info=None)
        self.frames = list(frames)
        self.gate = gate  # задан — get_frame висит, пока его не поднимут
        self.gate_result: RawFrame | None = None  # что вернёт get_frame, когда gate поднимут
        self.close_gate: threading.Event | None = None  # задан — close висит, пока его не поднимут
        self.calls: list[str] = []
        self.in_flight = 0
        self.closed_in_flight = False

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def enum_devices(self):
        return [self.entry]

    def open(self, entry):
        self.calls.append("open")
        return object()

    def start_grabbing(self, h):
        self.calls.append("start_grabbing")

    def get_frame(self, h, timeout_ms):
        self.in_flight += 1
        try:
            if self.gate is not None:
                self.gate.wait(10.0)
                return self.gate_result
            time.sleep(0.005)
            item = self.frames.pop(0) if self.frames else None
            if isinstance(item, BaseException):
                raise item
            return item
        finally:
            self.in_flight -= 1

    def stop_grabbing(self, h):
        self.calls.append("stop_grabbing")

    def close(self, h):
        self.closed_in_flight |= self.in_flight > 0
        if self.close_gate is not None:
            self.close_gate.wait(10.0)
        self.calls.append("close")


def _in_thread(fn, deadline: float):
    box: dict = {}

    def run():
        t0 = time.monotonic()
        box["result"] = fn()
        box["elapsed"] = time.monotonic() - t0

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), "вызов завис"
    return box


def _wait(pred, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end and not pred():
        time.sleep(0.005)
    return pred()


def test_stop_from_on_frame_does_not_deadlock_and_releases_once():
    api = _Api(frames=[_raw(1), _raw(2)])
    returned = threading.Event()
    reader: SdkCodeReader

    def on_frame(frame):
        reader.stop()
        returned.set()

    reader = SdkCodeReader(on_frame, api=api, timeout_ms=10)
    assert reader.start() is True
    assert returned.wait(3.0), "stop() из on_frame не вернулся (взаимоблокировка)"
    assert _wait(lambda: api.count("close") == 1)
    assert reader.state == "stopped"
    assert api.count("stop_grabbing") == 1
    time.sleep(0.05)
    assert api.count("close") == 1
    _in_thread(reader.stop, 3.0)  # второй stop — снаружи, ничего не зовёт
    assert api.count("close") == 1


def test_get_frame_hanging_past_deadline_is_not_closed_under_the_call():
    gate = threading.Event()
    api = _Api(gate=gate)
    reader = SdkCodeReader(lambda f: None, api=api, timeout_ms=50)
    try:
        assert reader.start() is True
        assert _wait(lambda: api.in_flight > 0)

        box = _in_thread(lambda: reader.stop(timeout=0.2), 3.0)
        assert box["elapsed"] <= 0.2 + 0.05 + 0.5
        assert api.count("close") == 0, "handle закрыт под идущим get_frame"
        assert reader.state == "stopped"

        # старый поток ещё держит handle — второе открытие недопустимо
        assert _in_thread(reader.start, 3.0)["result"] is False
        assert api.count("open") == 1

        gate.set()
        assert _wait(lambda: api.count("close") == 1)
        assert api.closed_in_flight is False
        assert api.count("stop_grabbing") == 1

        # поток вышел — новый start() открывает заново, на новое открытие своё закрытие
        api.gate = None
        assert _wait(lambda: _in_thread(reader.start, 3.0)["result"] is True)
        assert api.count("open") == 2
    finally:
        gate.set()
        _in_thread(reader.stop, 5.0)
    assert api.count("close") == 2


# --------------------------------------------------------------------------
# Ревью 6.2, итерация 1 (docs/reviews/2026-09-29_task-6.2-review.md)
# --------------------------------------------------------------------------

ERR = 0x80020001


def test_frame_returned_after_stop_deadline_is_not_delivered():
    """П.1: get_frame висит дольше дедлайна stop() и затем отдаёт КАДР, не None."""
    gate = threading.Event()
    api = _Api(gate=gate)
    api.gate_result = _raw(1)
    delivered = []
    reader = SdkCodeReader(delivered.append, api=api, timeout_ms=50)
    try:
        assert reader.start() is True
        assert _wait(lambda: api.in_flight > 0)
        _in_thread(lambda: reader.stop(timeout=0.05), 3.0)
        assert reader.state == "stopped"

        gate.set()
        assert _wait(lambda: api.count("close") == 1)
        time.sleep(0.05)
        assert delivered == [], "on_frame получил кадр после возврата stop()"
        assert reader.stats()["frames"] == 0
    finally:
        gate.set()
        _in_thread(reader.stop, 5.0)


def test_error_text_carries_notes_of_destroy_handle_failure():
    """П.2: отказ OpenDevice + отказ DestroyHandle через настоящий MvCodeReaderApi."""
    from Services.code_reader.sdk import api as api_mod

    class Lib:
        def __getattr__(self, name):
            def fn(*args):
                if name == "MV_CODEREADER_OpenDevice":
                    return 0x80020203
                if name == "MV_CODEREADER_DestroyHandle":
                    return 0x80000000
                return 0

            return fn

    class Api(api_mod.MvCodeReaderApi):
        def enum_devices(self):
            return [api_mod.DeviceEntry(ip="1.2.3.4", model="m", serial="s", info=api_mod.DEVICE_INFO())]

    errors: list[str] = []
    reader = SdkCodeReader(lambda f: None, errors.append, api=Api(lib=Lib()))
    assert reader.start() is False
    assert reader.state == "busy"
    assert "DestroyHandle" in reader.stats()["last_error"]
    assert any("DestroyHandle" in m for m in errors)


def test_stop_from_on_frame_racing_external_stop_does_not_wait_the_deadline():
    """П.3: внешний stop() ждал поток под _life, а stop() из on_frame ждал тот же _life."""
    stop_timeout, timeout_ms = 0.3, 10
    for i in range(20):
        api = _Api(frames=[_raw(1)])
        in_callback = threading.Event()
        reader: SdkCodeReader

        def on_frame(frame, reader_ref=lambda: reader):
            in_callback.set()
            time.sleep(0.02)  # внешний stop() успевает войти первым
            reader_ref().stop()

        reader = SdkCodeReader(on_frame, api=api, timeout_ms=timeout_ms)
        assert reader.start() is True
        assert in_callback.wait(3.0)
        box = _in_thread(lambda: reader.stop(timeout=stop_timeout), 3.0)
        assert box["elapsed"] < stop_timeout, f"прогон {i}: внешний stop() ждал {box['elapsed']:.3f} с"
        assert reader.stats()["errors"] == 0, f"прогон {i}: ложный _LATE_STOP"
        assert api.count("close") == 1


def test_start_while_failed_thread_still_releases_is_refused_and_keeps_error():
    """П.4a: поток умер после 3 ошибок и сидит в close; start() не должен отвечать True."""
    api = _Api(frames=[SdkError(ERR, "x")] * 3)
    api.close_gate = threading.Event()
    reader = SdkCodeReader(lambda f: None, api=api, timeout_ms=10)
    try:
        assert reader.start() is True
        assert _wait(lambda: "stop_grabbing" in api.calls)
        assert reader.state == "error"
        last = reader.stats()["last_error"]
        assert _in_thread(reader.start, 3.0)["result"] is False
        assert reader.state == "error"
        assert reader.stats()["last_error"] == last
        assert api.count("open") == 1
    finally:
        api.close_gate.set()
        _in_thread(reader.stop, 5.0)
    assert api.count("close") == 1


def test_start_from_on_error_on_final_failure_keeps_error_state():
    """П.4b: start() из on_error на финальном сбое не перетирает error и его причину."""
    api = _Api(frames=[SdkError(ERR, "x")] * 3)
    results: list = []
    reader: SdkCodeReader

    def on_error(message):
        if "подряд" in message:
            results.append(reader.start())

    reader = SdkCodeReader(lambda f: None, on_error, api=api, timeout_ms=10)
    assert reader.start() is True
    assert _wait(lambda: results)
    assert results == [False]
    assert reader.state == "error"
    assert "подряд" in reader.stats()["last_error"]
    assert api.count("open") == 1
    _in_thread(reader.stop, 5.0)
