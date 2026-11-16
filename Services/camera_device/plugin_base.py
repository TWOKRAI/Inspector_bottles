# -*- coding: utf-8 -*-
"""CameraDevicePlugin — источник кадров ядра камеры: сеанс `DeviceSession` -> слот кадра -> item -> дерево.

Порт одного прибора держит поток-владелец сеанса (Task 2.1): `take_device -> session.start(timeout)`,
`release_device -> session.stop(timeout)`, `get_status.state <- session.state`. `on_frame` кладёт кадр в слот
для `produce()` (потеря кадра допустима). До Task 2.3a сеанс создаётся с `ident=None`, `timeout_ms=500`,
`watchdog_s=5.0`. Публикация метрик, `device_held`, `last_error` в дерево — Task 2.3b.

`create_port()` знает только `"fake"`; SDK берётся как `port.sdk`. Публикация — `ctx.declare_metric("frames")`
+ `ctx.publish_metric` (путь `processes.<p>.state.plugins.camera_device.frames`), без прямого `merge`.
Item по Р10: `frame`, `camera_id`, `seq_id`, `frame_id`, `timestamp` (monotonic) + `device_id`, `ts` (wall),
`pixel_format`, `width`, `height`, `device_frame_num`.

Слой: Services -> framework; плагин не импортирует `multiprocess_prototype` и вендорские драйверы.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from .interface import DevicePort, RawFrame
from .registers_base import CameraDeviceRegisters
from .session import DeviceSession

# Срок ожидания `start`/`stop` в командах плагина, с.
_START_TIMEOUT_S = 5.0
_STOP_TIMEOUT_S = 2.0
# Таймаут кадра и срок сторожа сеанса до Task 2.3a.
_TIMEOUT_MS = 500
_WATCHDOG_S = 5.0


def create_port(driver: str) -> DevicePort:
    """Порт по имени драйвера. Сейчас только `"fake"`; реестр драйверов — Task 5.1."""
    if driver == "fake":
        from .testing.fake_port import make_port  # ленивый импорт: ядро не тянет фейк без нужды

        return make_port(frame_period_s=0.02)  # ~50 кадров/с; без периода фейк отдаёт кадры без пауз
    raise ValueError(f"неизвестный драйвер: {driver}")


@register_plugin(
    "camera_device",
    category="source",
    description="Источник кадров с прибора через порт камеры (ядро camera_device)",
)
class CameraDevicePlugin(ProcessModulePlugin):
    """Источник кадров: сеанс одного прибора, items по Р10.

    Команды:
        take_device    — открыть прибор и начать захват
        release_device — остановить захват и закрыть прибор
        get_status     — состояние и счётчик кадров
    """

    name = "camera_device"
    category = "source"

    register_class = CameraDeviceRegisters

    # Потоки сеанса — воркеры `WorkerManager` процесса (ctx.worker_manager).
    REQUIRES: tuple[str, ...] = ("manager:worker_manager",)

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
        self._slot: tuple[int, float, float, RawFrame] | None = None  # последний кадр; новый вытесняет старый
        self._seq = 0
        self._frames = 0
        self._session: DeviceSession | None = None
        self._session_lock = threading.Lock()  # ленивое создание сеанса: start() и команда из другого потока
        ctx.declare_metric("frames")

    def start(self, ctx: PluginContext) -> None:
        if self._reg.auto_start:
            self.cmd_take_device({})

    def shutdown(self, ctx: PluginContext) -> None:
        self.cmd_release_device({})

    # ------------------------------------------------------------------ #
    # Поток данных
    # ------------------------------------------------------------------ #

    def _on_frame(self, raw: RawFrame) -> None:
        """Колбэк сеанса (поток-владелец): кадр в слот, поток чтения не ждёт `produce()`."""
        with self._lock:
            self._seq += 1
            self._slot = (self._seq, time.time(), time.monotonic(), raw)

    def _on_state(self, old: str, new: str) -> None:
        # События приходят из разных потоков и могут опередить друг друга: истина — `session.state`.
        session = self._session
        self._reg.device_state = session.state if session is not None else new

    def produce(self) -> list[dict]:
        """Забрать кадр из слота в item. Пусто — норма. Не блокирует."""
        with self._lock:
            slot, self._slot = self._slot, None
        if slot is None:
            return []
        self._frames += 1
        self._reg.frames = self._frames
        self._ctx.publish_metric("frames", self._frames)
        return [self._build_item(*slot)]

    def _build_item(self, seq: int, ts: float, mono: float, raw: RawFrame) -> dict:
        device = self._session.device if self._session is not None else None
        # ponytail: только 8-битные одноканальные кадры (reshape по h x w); цветные форматы — вместе с драйверами.
        frame = np.frombuffer(raw.data, dtype=np.uint8).reshape(raw.height, raw.width).copy()
        return {
            "frame": frame,
            "camera_id": self._reg.camera_id,
            "device_id": device.value if device is not None else "",
            "seq_id": seq,
            "frame_id": seq,
            "timestamp": mono,
            "ts": ts,
            "pixel_format": raw.pixel_format,
            "width": raw.width,
            "height": raw.height,
            "device_frame_num": raw.frame_num,
        }

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def _ensure_session(self) -> DeviceSession:
        with self._session_lock:
            if self._session is not None:
                return self._session
            port = create_port(self._reg.driver)
            self._session = DeviceSession(
                port,
                port.sdk,
                None,
                workers=self._ctx.worker_manager,
                worker_prefix=f"{self.name}_{self._reg.camera_id}",
                timeout_ms=_TIMEOUT_MS,
                watchdog_s=_WATCHDOG_S,
                on_frame=self._on_frame,
                on_state=self._on_state,
                on_stall=lambda call, seconds: self._ctx.log_error(
                    f"CameraDevicePlugin: вызов порта {call} завис на {seconds:.1f} с"
                ),
            )
        return self._session

    def cmd_take_device(self, data: dict) -> dict:
        """Открыть прибор и начать захват. Отказ — `status: error`, не исключение."""
        workers = self._ctx.worker_manager
        if workers is None:
            return {"status": "error", "device_state": self._reg.device_state, "error": "нет менеджера воркеров"}
        if not (hasattr(workers, "has_worker") and hasattr(workers, "create_worker")):
            error = "worker_manager не поддерживает create_worker/has_worker"
            return {"status": "error", "device_state": self._reg.device_state, "error": error}
        session = self._ensure_session()
        t0 = time.monotonic()
        ok = session.start(_START_TIMEOUT_S)
        ms = int((time.monotonic() - t0) * 1000)
        device = session.device
        self._ctx.log_info(
            f"CameraDevicePlugin: take_device device_id={device.value if device else ''} ms={ms} ok={ok}"
        )
        result: dict = {"status": "ok" if ok else "error", "device_state": session.state}
        if not ok:
            result["error"] = session.last_error or session.state
        return result

    def cmd_release_device(self, data: dict) -> dict:
        """Остановить захват, закрыть прибор и отпустить SDK."""
        session = self._session
        if session is None:
            return {"status": "ok", "device_state": self._reg.device_state}
        session.stop(_STOP_TIMEOUT_S)
        released = not session.device_held
        result: dict = {"status": "ok" if released else "error", "device_state": session.state}
        if not released:
            result["error"] = "поток-владелец ещё закрывает прибор"
        return result

    def cmd_get_status(self, data: dict) -> dict:
        session = self._session
        state = session.state if session is not None else self._reg.device_state
        device = session.device if session is not None else None
        return {
            "status": "ok",
            "state": state,
            "device_state": state,
            "device_id": device.value if device is not None else "",
            "frames": self._frames,
            "last_error": (session.last_error if session is not None else None) or "",
        }
