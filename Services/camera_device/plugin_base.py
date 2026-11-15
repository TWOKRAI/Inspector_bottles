# -*- coding: utf-8 -*-
"""CameraDevicePlugin — тонкий сквозной срез ядра камеры (Task 1.8): порт -> поток -> item -> дерево.

ponytail: поток чтения кадров и состояние (`closed|grabbing|error`) здесь ВРЕМЕННЫЕ. Их заменит сеанс
(Task 2.1): `take_device -> session.start`, `release_device -> session.stop`, `get_status.state <-
session.state`. Поэтому собственного сеанса и таблицы состояний здесь нет.

`create_port()` знает только `"fake"`; SDK берётся как `port.sdk`. Публикация — `ctx.declare_metric("frames")`
+ `ctx.publish_metric` (путь `processes.<p>.state.plugins.camera_device.frames`), без прямого `merge`.
Item по Р10: `frame`, `camera_id`, `seq_id`, `frame_id`, `timestamp` (monotonic) + `device_id`, `ts` (wall),
`pixel_format`, `width`, `height`, `device_frame_num`.

Слой: Services -> framework; плагин не импортирует `multiprocess_prototype` и вендорские драйверы.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from .interface import DeviceIdentity, DevicePort, PortError, RawFrame
from .registers_base import CameraDeviceRegisters

# Глубина очереди между потоком чтения и produce(): переполнение теряет старые кадры.
_QUEUE_LIMIT = 8
# Таймаут get_frame и срок ожидания потока при release, мс / с.
_GET_FRAME_TIMEOUT_MS = 100
_JOIN_TIMEOUT_S = 1.0
# Пауза потока между кадрами: фейк не блокируется в get_frame, живой драйвер ждёт сам.
_FRAME_INTERVAL_S = 0.02


def create_port(driver: str) -> DevicePort:
    """Порт по имени драйвера. Сейчас только `"fake"`; реестр драйверов — Task 5.1."""
    if driver == "fake":
        from .testing.fake_port import make_port  # ленивый импорт: ядро не тянет фейк без нужды

        return make_port()
    raise ValueError(f"неизвестный драйвер: {driver}")


@register_plugin(
    "camera_device",
    category="source",
    description="Источник кадров с прибора через порт камеры (ядро camera_device, срез Task 1.8)",
)
class CameraDevicePlugin(ProcessModulePlugin):
    """Источник кадров: порт одного прибора, поток чтения, items по Р10.

    Команды:
        take_device    — открыть прибор и начать захват
        release_device — остановить захват и закрыть прибор
        get_status     — состояние и счётчик кадров
    """

    name = "camera_device"
    category = "source"

    register_class = CameraDeviceRegisters

    inputs: list[Port] = []
    outputs: list[Port] = [
        Port(name="frame", dtype="image/gray", shape="(H, W)", description="Кадр прибора uint8"),
    ]

    commands: dict[str, str] = {
        "take_device": "cmd_take_device",
        "release_device": "cmd_release_device",
        "get_status": "cmd_get_status",
    }

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: CameraDeviceRegisters = self._init_register(ctx)
        self._lock = threading.Lock()
        self._queue: deque[tuple[int, float, float, RawFrame]] = deque(maxlen=_QUEUE_LIMIT)
        self._seq = 0
        self._frames = 0
        self._last_error = ""
        self._port: DevicePort | None = None
        self._device_id = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        ctx.declare_metric("frames")

    def start(self, ctx: PluginContext) -> None:
        if self._reg.auto_start:
            self.cmd_take_device({})

    def shutdown(self, ctx: PluginContext) -> None:
        self.cmd_release_device({})

    # ------------------------------------------------------------------ #
    # Поток данных
    # ------------------------------------------------------------------ #

    def produce(self) -> list[dict]:
        """Слить очередь в items. Пусто — норма. Не блокирует."""
        with self._lock:
            batch = list(self._queue)
            self._queue.clear()
        items = [self._build_item(seq, ts, mono, raw) for seq, ts, mono, raw in batch]
        if items:
            self._frames += len(items)
            self._reg.frames = self._frames
            self._ctx.publish_metric("frames", self._frames)
        return items

    def _build_item(self, seq: int, ts: float, mono: float, raw: RawFrame) -> dict:
        # ponytail: только 8-битные одноканальные кадры (reshape по h x w); цветные форматы — вместе с драйверами.
        frame = np.frombuffer(raw.data, dtype=np.uint8).reshape(raw.height, raw.width).copy()
        return {
            "frame": frame,
            "camera_id": self._reg.camera_id,
            "device_id": self._device_id,
            "seq_id": seq,
            "frame_id": seq,
            "timestamp": mono,
            "ts": ts,
            "pixel_format": raw.pixel_format,
            "width": raw.width,
            "height": raw.height,
            "device_frame_num": raw.frame_num,
        }

    def _grab_loop(self, port: DevicePort, stop: threading.Event) -> None:
        """Временный поток чтения кадров (ponytail: заменит сеанс 2.1)."""
        while not stop.is_set():
            try:
                raw = port.get_frame(_GET_FRAME_TIMEOUT_MS)
            except PortError as exc:
                with self._lock:
                    self._last_error = str(exc)
                self._reg.device_state = "error"
                self._ctx.log_error(f"CameraDevicePlugin: чтение кадра: {exc}")
                return
            if raw is not None:
                with self._lock:
                    self._seq += 1
                    self._queue.append((self._seq, time.time(), time.monotonic(), raw))
            stop.wait(_FRAME_INTERVAL_S)

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def cmd_take_device(self, data: dict) -> dict:
        """Открыть прибор и запустить поток чтения. Отказ — `status: error`, не исключение."""
        if self._port is not None:
            return {"status": "ok", "device_state": self._reg.device_state}
        t0 = time.monotonic()
        port = create_port(self._reg.driver)
        sdk_taken = False
        try:
            port.sdk.acquire()
            sdk_taken = True
            ident = self._pick_device(port)
            port.open(ident)
            port.start_grabbing()
        except PortError as exc:
            port.close()
            if sdk_taken:
                port.sdk.release()
            self._last_error = str(exc)
            self._reg.device_state = "error"
            self._ctx.log_error(f"CameraDevicePlugin: take_device не удался: {exc}")
            return {"status": "error", "device_state": "error", "error": str(exc)}
        self._port = port
        self._device_id = ident.value
        self._last_error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._grab_loop, args=(port, self._stop), name="camera_device-grab", daemon=True
        )
        self._thread.start()
        self._reg.device_state = "grabbing"
        ms = int((time.monotonic() - t0) * 1000)
        self._ctx.log_info(f"CameraDevicePlugin: take_device device_id={self._device_id} ms={ms}")
        return {"status": "ok", "device_state": "grabbing"}

    def _pick_device(self, port: DevicePort) -> DeviceIdentity:
        if self._reg.device_id:
            return DeviceIdentity("serial", self._reg.device_id)
        found = port.sdk.enum_devices()
        if not found:
            raise PortError("not_found", "enum_devices")
        return found[0]

    def cmd_release_device(self, data: dict) -> dict:
        """Остановить поток, закрыть прибор и отпустить SDK."""
        port, thread = self._port, self._thread
        if port is None:
            return {"status": "ok", "device_state": self._reg.device_state}
        self._stop.set()
        if thread is not None:
            thread.join(_JOIN_TIMEOUT_S)
            if thread.is_alive():
                self._last_error = "поток чтения не остановился за срок"
                self._ctx.log_error(f"CameraDevicePlugin: {self._last_error}")
                return {"status": "error", "device_state": self._reg.device_state, "error": self._last_error}
        port.stop_grabbing()
        port.close()
        port.sdk.release()
        self._port = None
        self._thread = None
        self._reg.device_state = "closed"
        return {"status": "ok", "device_state": "closed"}

    def cmd_get_status(self, data: dict) -> dict:
        return {
            "status": "ok",
            "device_state": self._reg.device_state,
            "device_id": self._device_id,
            "frames": self._frames,
            "last_error": self._last_error,
        }
