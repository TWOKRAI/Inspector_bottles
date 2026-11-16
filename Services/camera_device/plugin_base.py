# -*- coding: utf-8 -*-
"""CameraDevicePlugin — источник кадров ядра камеры: сеанс `DeviceSession` -> слот кадра -> item -> дерево.

Порт одного прибора держит поток-владелец сеанса (Task 2.1): `take_device -> session.start(timeout)`,
`release_device -> session.stop(timeout)`, `get_status.state <- session.state`. `on_frame` кладёт кадр в слот
для `produce()` (потеря кадра допустима). Публикация метрик, `device_held`, `last_error` в дерево — Task 2.3b.

Task 2.3a: база для вендорских плагинов. Хуки: `create_port(self)` (по умолчанию — модульная `create_port(driver)`,
знает только `"fake"`) и `bindings(self)` (по умолчанию `FAKE_BINDINGS`); порт создаётся один раз в
`_ensure_session`, SDK берётся как `port.sdk`. Идентичность прибора, таймаут и сторож берутся из register'а.
При КАЖДОМ `take_device` план run/rest строится из register'а (`params.build_plan`) и передаётся сеансу через
`set_cycle` (идущий цикл не меняется). Публикация — `ctx.declare_metric("frames")` + `ctx.publish_metric`
(путь `processes.<p>.state.plugins.camera_device.frames`), без прямого `merge`.
Item по Р10: `frame`, `camera_id`, `seq_id`, `frame_id`, `timestamp` (monotonic) + `device_id`, `ts` (wall),
`pixel_format`, `width`, `height`, `device_frame_num`. Форма кадра — по `pixel_format` (rgb8/bgr8 — h x w x 3).

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

from .interface import Binding, DeviceIdentity, DevicePort, RawFrame
from .params import build_plan
from .registers_base import CameraDeviceRegisters
from .session import DeviceSession, describe_error

# Срок ожидания `start`/`stop` в командах плагина, с.
_START_TIMEOUT_S = 5.0
_STOP_TIMEOUT_S = 2.0
# Каналов на пиксель для 8-битных форматов; `bayer_*` — один канал (дебайер — не в ядре).
_CHANNELS = {"mono8": 1, "rgb8": 3, "bgr8": 3}
# Группа триггера в плане rest: привязки только `trigger_*`, иначе `build_plan` потребует значения остальных полей.
_TRIGGER_PREFIX = "trigger_"


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
        self._port: DevicePort | None = None
        self._session: DeviceSession | None = None
        self._session_lock = threading.Lock()  # ленивое создание сеанса: start() и команда из другого потока
        self._item_error = ""  # последняя причина отброшенного кадра (сборка item)
        self._dropped = 0
        self._identity(warn=True)  # отказ рецепта — здесь, а не в take_device
        if self._reg.watchdog_s <= self._reg.timeout_ms / 1000.0:
            raise ValueError("watchdog_s должен быть больше timeout_ms/1000")
        ctx.declare_metric("frames")

    # ------------------------------------------------------------------ #
    # Хуки вендора
    # ------------------------------------------------------------------ #

    def create_port(self) -> DevicePort:
        """Порт прибора; вызывается один раз при создании сеанса. Вендор переопределяет."""
        return create_port(self._reg.driver)

    def bindings(self) -> dict[str, Binding]:
        """Таблица привязки полей register'а к узлам прибора. Вендор переопределяет (`driver.BINDINGS`)."""
        from .testing.fake_port import FAKE_BINDINGS  # ленивый импорт: ядро не тянет фейк без нужды

        return FAKE_BINDINGS

    def _identity(self, *, warn: bool = False) -> DeviceIdentity | None:
        """Идентичность прибора по `device_select`; пустое поле -> `ValueError` с именем поля (без значения)."""
        reg = self._reg
        kind = reg.device_select
        if kind == "first":
            if warn:
                self._ctx.log_warning("device_select=first: прибор выбирается первым из перечисленных; задайте serial")
            return None
        if kind == "index":
            if warn and not reg.device_name:
                self._ctx.log_warning("device_select=index без device_name: порядок перечисления не обещан")
            return DeviceIdentity("index", str(reg.device_index), reg.device_name)
        value = getattr(reg, f"device_{kind}")
        if not value:
            raise ValueError(f"device_{kind} пуст")
        return DeviceIdentity(kind, value)

    def _plan(self) -> tuple[list, list]:
        """План run (весь register) и rest (только группа триггера из `rest_*`) по привязкам вендора."""
        reg = self._reg
        bindings = self.bindings()
        run = build_plan(type(reg), reg.model_dump(), bindings)
        rest_values = {
            "trigger_managed": reg.rest_managed,
            "trigger_mode": reg.rest_trigger_mode,
            "trigger_source": reg.rest_trigger_source,
            # период самотриггера в покое — тот же, что в run: у rest своего поля нет, а `SelfTrigger` его требует
            "trigger_period_ms": reg.trigger_period_ms,
        }
        rest_bindings = {k: b for k, b in bindings.items() if k.startswith(_TRIGGER_PREFIX)}
        return run, build_plan(type(reg), rest_values, rest_bindings)

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
        try:
            item = self._build_item(*slot)
        except ValueError as exc:  # битый кадр отбрасывается: `produce()` не бросает, счётчик кадров не растёт
            self._drop_frame(str(exc))
            return []
        self._frames += 1
        self._reg.frames = self._frames
        self._ctx.publish_metric("frames", self._frames)
        return [item]

    def _drop_frame(self, error: str) -> None:
        self._dropped += 1
        if error != self._item_error:  # один журнал на причину, не на кадр (50 кадров/с)
            self._ctx.log_error(f"CameraDevicePlugin: кадр отброшен: {error}")
        self._item_error = error

    @staticmethod
    def _frame_array(raw: RawFrame) -> np.ndarray:
        """Массив кадра по `pixel_format`: rgb8/bgr8 -> (h, w, 3), остальные 8-битные -> (h, w)."""
        channels = _CHANNELS.get(raw.pixel_format)
        if channels is None and raw.pixel_format.startswith("bayer_"):
            channels = 1
        if channels is None:
            raise ValueError(f"неподдерживаемый pixel_format {raw.pixel_format}")
        expected = raw.height * raw.width * channels
        if len(raw.data) != expected:
            raise ValueError(f"длина буфера {len(raw.data)} не равна {expected} для {raw.pixel_format}")
        shape = (raw.height, raw.width, 3) if channels == 3 else (raw.height, raw.width)
        return np.frombuffer(raw.data, dtype=np.uint8).reshape(shape).copy()

    def _build_item(self, seq: int, ts: float, mono: float, raw: RawFrame) -> dict:
        device = self._session.device if self._session is not None else None
        frame = self._frame_array(raw)
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
            port = self.create_port()
            session = DeviceSession(
                port,
                port.sdk,
                self._identity(),
                workers=self._ctx.worker_manager,
                worker_prefix=f"{self.name}_{self._reg.camera_id}",
                timeout_ms=self._reg.timeout_ms,
                watchdog_s=self._reg.watchdog_s,
                on_frame=self._on_frame,
                on_state=self._on_state,
                on_stall=lambda call, seconds: self._ctx.log_error(
                    f"CameraDevicePlugin: вызов порта {call} завис на {seconds:.1f} с"
                ),
            )
            self._port, self._session = port, session  # атрибут не залипает на неудачной попытке (объект порта при этом теряется без close(): SDK ещё не acquire'нут)
        return session

    def cmd_take_device(self, data: dict) -> dict:
        """Открыть прибор и начать захват. Отказ — `status: error`, не исключение."""
        workers = self._ctx.worker_manager
        if workers is None:
            return {"status": "error", "device_state": self._reg.device_state, "error": "нет менеджера воркеров"}
        if not (hasattr(workers, "has_worker") and hasattr(workers, "create_worker")):
            error = "worker_manager не поддерживает create_worker/has_worker"
            return {"status": "error", "device_state": self._reg.device_state, "error": error}
        try:
            session = self._ensure_session()
            ident = self._identity()
            run, rest = self._plan()
            # идущий цикл не меняется (повторный take_device при opening/grabbing — по-прежнему ok): результат не нужен
            session.set_cycle(ident, run, rest)
        except Exception as exc:  # noqa: BLE001 — контракт 1.8: отказ команды = status error, исключение наружу не идёт
            # хук вендора (`create_port`, `port.sdk`) может бросить что угодно: PortError, ImportError, OSError
            text = str(exc) if isinstance(exc, ValueError) else describe_error(exc)  # без значений рецепта
            self._ctx.log_error(f"CameraDevicePlugin: take_device отклонён: {text}")
            return {"status": "error", "device_state": self._reg.device_state, "error": text}
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
            "last_error": (session.last_error if session is not None else None) or self._item_error,
        }
