# -*- coding: utf-8 -*-
"""Потеря связи по тишине выключена по умолчанию (решение владельца 2026-11-25, ADR-CAM-008).

Purpose:
    Закрепить умолчание: с register'ом без конфига пауза кадров свободного потока не считается потерей связи;
    рецепт, задавший `link_silence_s: 3.0`, правило включает. Порт — фейк, `DeviceSession` и `WorkerManager`
    настоящие; значения политики связи берутся из register'а так же, как их передаёт плагин
    (`plugin_base._ensure_session`). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device.params import Step
from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.camera_device.session import DeviceSession
from Services.camera_device.testing import fake_port
from Services.camera_device.testing.fake_port import FAKE_BINDINGS

__all__ = []

_GAP_S = 4.0  # дольше прежнего умолчания 3.0 с


def _call(fn: Callable[[], Any], deadline: float = 8.0) -> Any:
    """Вызвать `fn` в daemon-потоке; не вернулся за `deadline` — тест падает."""
    box: dict[str, Any] = {}

    def run() -> None:
        box["result"] = fn()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    return box.get("result")


def _await(pred: Callable[[], bool], message: str, deadline: float) -> None:
    end = time.monotonic() + deadline
    while not pred():
        assert time.monotonic() < end, f"не дождались за {deadline} с: {message}"
        time.sleep(0.01)


class _Rig:
    """Свободный поток (`trigger_mode Off`); `silent` глушит кадры, проба `get_param` при этом отвечает."""

    def __init__(self, registers: CameraDeviceRegisters) -> None:
        self.silent = threading.Event()
        self.states: list[str] = []
        self.frames: list[Any] = []
        port = fake_port.make_port(frame_period_s=0.01)
        original_get_frame = port.get_frame

        def get_frame(*args: Any, **kwargs: Any) -> Any:
            if self.silent.is_set():
                time.sleep(0.1)  # срок кадра сеанса, timeout_ms 100
                return None
            return original_get_frame(*args, **kwargs)

        port.get_frame = get_frame
        self.wm = WorkerManager("test_link_default_off")
        self.session = DeviceSession(
            port,
            port.sdk,
            None,
            timeout_ms=100,
            watchdog_s=5.0,
            on_frame=self.frames.append,
            on_state=lambda old, new: self.states.append(new),
            workers=self.wm,
            worker_prefix="camera_device_default_off",
            run=(Step("trigger_mode", FAKE_BINDINGS["trigger_mode"], "Off"),),
            reconnect=registers.reconnect,
            link_silence_s=registers.link_silence_s,
            reconnect_interval_s=registers.reconnect_interval_s,
        )

    def grab(self) -> None:
        assert _call(lambda: self.session.start(5.0)) is True
        _await(lambda: self.session.state == "grabbing" and len(self.frames) >= 2, "grabbing и кадры", 5.0)

    def close(self) -> None:
        stopper = threading.Thread(target=self.session.stop, args=(2.0,), daemon=True)
        stopper.start()
        stopper.join(5.0)
        self.wm.stop_all_workers(2.0)


@pytest.fixture
def make_rig() -> Iterator[Callable[[CameraDeviceRegisters], _Rig]]:
    rigs: list[_Rig] = []

    def make(registers: CameraDeviceRegisters) -> _Rig:
        rigs.append(_Rig(registers))
        return rigs[-1]

    yield make
    for rig in rigs:
        rig.close()


def test_default_config_silence_does_not_declare_lost(make_rig):
    """Умолчания register'а: 4 с без кадров — `grabbing`, связь не `lost`, после паузы кадры идут снова."""
    rig = make_rig(CameraDeviceRegisters())
    rig.grab()

    rig.silent.set()
    time.sleep(_GAP_S)

    assert rig.session.state == "grabbing"
    assert _call(rig.session.link, 2.0)["state"] != "lost"
    assert "error" not in rig.states
    assert "lost" not in rig.states

    seen = len(rig.frames)
    rig.silent.clear()
    _await(lambda: len(rig.frames) > seen, "кадры после паузы", 5.0)


def test_configured_silence_still_declares_lost(make_rig):
    """`link_silence_s: 3.0` из конфига: та же пауза — связь `lost`, без `reconnect` состояние `error`."""
    rig = make_rig(CameraDeviceRegisters(link_silence_s=3.0))
    rig.grab()

    rig.silent.set()
    _await(lambda: rig.session.state == "error", "state == error по тишине", 6.0)

    assert _call(rig.session.link, 2.0)["state"] == "lost"
    assert rig.session.last_error.startswith("тишина ")
