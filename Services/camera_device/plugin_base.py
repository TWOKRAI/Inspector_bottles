# -*- coding: utf-8 -*-
"""CameraDevicePlugin — источник кадров ядра камеры: сеанс `DeviceSession` -> слот кадра -> item -> дерево.

Порт одного прибора держит поток-владелец сеанса (Task 2.1): `take_device -> session.start(timeout)`,
`release_device -> session.stop(timeout)`, `get_status.state <- session.state`. `on_frame` кладёт кадр в слот
для `produce()` (потеря кадра допустима). Уровни и события в дерево — Task 2.3b (ниже).

Task 2.3a: база для вендорских плагинов. Хуки: `create_port(self)` (по умолчанию — модульная `create_port(driver)`,
знает только `"fake"`) и `bindings(self)` (по умолчанию `FAKE_BINDINGS`); порт создаётся один раз в
`_ensure_session`, SDK берётся как `port.sdk`. Идентичность прибора, таймаут и сторож берутся из register'а.

Task 2.3b: наблюдаемость средствами framework. Уровни (`fps`, `frames`, `errors`, `dropped`, `pending`,
`param_errors_count`) — `ctx.declare_metric` + `ctx.publish_metric` (`frames` на учтённый кадр, остальные — окном
`_TICK_S` из `produce()`). События (`state`, `device`, `device_held`, `profile`, `params`, `params_status`,
`param_errors`, `last_error`, `capabilities`, `ts`) — один `state_proxy.merge` в `processes.<p>.state.plugins.<name>`
ТОЛЬКО при смене (`_sync_events`: из `on_state` и из окна). Инциденты — `ctx.health.report_error` (переход в
`busy`/`not_found`/`error` вместе с `degraded`, новый ключ `param_errors`, `on_stall` вместе с
`flight_dump("owner_stall")`). Замеры сеанса: `open` -> `open_ms`,
`apply` -> `apply` (секунды), `get_frame` агрегируется окном в одну запись `get_frame_ms` (среднее за окно).
Логгер сеанса `camera_device.session` пробрасывается в `ctx.log_*` (`_SessionLogBridge`): стандартный `logging` в файлы
framework не попадает.
При КАЖДОМ `take_device` план run/rest строится из register'а (`params.build_plan`) и передаётся сеансу через
`set_cycle` (идущий цикл не меняется). Уровни публикуются через `ctx.declare_metric` + `ctx.publish_metric` (путь
`processes.<p>.state.plugins.camera_device.<имя>`), без прямого `merge`; прямой `state_proxy.merge` — только у
событий (см. Task 2.3b выше), уровни им не пишутся.
Item по Р10: `frame`, `camera_id`, `seq_id`, `frame_id`, `timestamp` (monotonic) + `device_id`, `ts` (wall),
`pixel_format`, `source_format`, `width`, `height`, `device_frame_num`. Цветные источники (rgb8, bgr8, bayer_*8) уходят
BGR h x w x 3 (`pixel_format="bgr8"`, `source_format` — формат прибора); mono8 — h x w; прочие форматы кадр отбрасывают.

Task 2.4b: правка поля из GUI (`register_update` -> `RegistersManager.set_field_value`) доходит до прибора по Р12.
В `configure` плагин подписывается на каждое поле из `bindings()` (`ctx.registers.subscribe`; без `ctx.registers` —
один WARNING и подписки нет), в `shutdown` снимает те же колбэки. Колбэк исполняется в потоке вызывающего (системный
поток процесса) и порт не трогает: политика поля — `FieldMeta.apply` (`config`/`None` — ничего), шаг поля строит
`params.build_plan` из значений register'а, `DeviceSession.apply` ставит его в ящик владельца (неблокирующе).
Прямая запись `self._reg.x = v` колбэки не будит: править только через `set_field_value`.

Task 2.3c: команды Р7 без порта и ящика (раздел «Команды Р7» ниже): `reset_stats`, `read_params`, `apply_params`; модели
аргументов — `commands.py`, `timeout_s` читают `take_device`/`release_device`. Счётчики охраняет `_stats_lock`.

Task 2.3d: команды Р7 с портом: `list_devices`, `describe_params`, `trigger_software`. Порт создаётся отдельно от
сеанса (`_ensure_port`, без сеанса, моста логов и воркеров); порт и SDK зовёт только тот поток, который их держит:
владелец через `session.call` (срок `_CALL_TIMEOUT_S`), а `list_devices` без владельца — поток команды (`acquire`
-> `enum_devices` -> `release`). Каждая команда с `call` блокирует приём команд процесса до срока.

Слой: Services -> framework; плагин не импортирует `multiprocess_prototype` и вендорские драйверы.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

import numpy as np
from pydantic import ValidationError

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from .commands import ApplyParamsArgs, ReleaseDeviceArgs, TakeDeviceArgs
from .interface import Binding, DeviceIdentity, DevicePort, PortError, RawFrame
from .params import Step, build_plan
from .registers_base import CameraDeviceRegisters
from .session import DeviceSession, describe_error

# Срок ответа владельца на команду через `session.call`, с: больше `timeout_ms/1000` и обычного перезахвата на фейке.
# Команда блокирует системный поток процесса до срока; худший случай — срок + `watchdog_s` (владелец взял `fn` и завис).
_CALL_TIMEOUT_S = 2.0
# Каналов на пиксель для принимаемых 8-битных форматов; `bayer_*8` — один канал (дебайер — в `_frame_array`).
_CHANNELS = {"mono8": 1, "rgb8": 3, "bgr8": 3, "bayer_rg8": 1, "bayer_bg8": 1, "bayer_gr8": 1, "bayer_gb8": 1}
# Дебайер: имя формата (GenICam) -> имя константы OpenCV. Имена OpenCV инвертированы
# относительно GenICam (замер cv2 4.13.0, RGGB, красная сцена): bayer_rg8 -> COLOR_BayerBG2BGR и так далее.
_DEBAYER_CODE = {
    "bayer_rg8": "COLOR_BayerBG2BGR",
    "bayer_bg8": "COLOR_BayerRG2BGR",
    "bayer_gr8": "COLOR_BayerGB2BGR",
    "bayer_gb8": "COLOR_BayerGR2BGR",
}
# Окно публикации уровней, агрегата замеров и сверки событий, с (в тестах подменяется).
_TICK_S = 1.0
# Состояния отказа сеанса: инцидент `report_error` и `health.degraded`.
_FAILED = frozenset({"busy", "not_found", "error"})
# Профиль, записанный/записываемый в прибор, по состоянию сеанса; остальные состояния — `None`.
_PROFILE_OF_STATE = {"opening": "run", "grabbing": "run", "stopping": "rest", "closed": "rest"}
# Поля-словари события: ушедшие ключи удаляются из дерева (`merge` их не снимает).
_DICT_EVENTS = ("params", "params_status", "param_errors")
_MISSING = object()
# Отказ команд с портом, когда владельца нет в `grabbing` (литерал `session.call` и Р7).
_NOT_GRABBING = "сеанс не в захвате"
# Группа триггера в плане rest: привязки только `trigger_*`, иначе `build_plan` потребует значения остальных полей.
_TRIGGER_PREFIX = "trigger_"


class CameraDeviceError(RuntimeError):
    """Инцидент плагина камеры для `ctx.health.report_error`: текст без значений рецепта."""


class _SessionLogBridge(logging.Handler):
    """Строки логгера сеанса (`camera_device.session`, стандартный `logging`) -> `ctx.log_*` (файлы framework)."""

    def __init__(self, ctx: PluginContext) -> None:
        super().__init__(logging.INFO)
        self._ctx = ctx

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            if record.levelno >= logging.ERROR:
                self._ctx.log_error(text)
            elif record.levelno >= logging.WARNING:
                self._ctx.log_warning(text)
            else:
                self._ctx.log_info(text)
        except Exception:  # noqa: BLE001 — запись лога не должна ронять поток сеанса
            self.handleError(record)


def create_port(driver: str) -> DevicePort:
    """Порт по имени драйвера. Сейчас только `"fake"`; реестр драйверов — Task 5.1."""
    if driver == "fake":
        from .testing.fake_port import make_port  # ленивый импорт: ядро не тянет фейк без нужды

        return make_port(frame_period_s=0.02)  # ~50 кадров/с; без периода фейк отдаёт кадры без пауз
    raise ValueError(f"неизвестный драйвер: {driver}")


def _validation_text(exc: ValidationError) -> str:
    """Текст отказа модели из `loc` и `msg`; введённое значение (`input`) не берётся — ни в ответ, ни в журнал."""
    parts = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        where = ".".join(str(part) for part in error["loc"])
        parts.append(f"{where}: {error['msg']}" if where else error["msg"])
    return "; ".join(parts)


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
        reset_stats    — обнулить счётчики кадров и окно fps
        read_params    — снимок параметров прибора последнего цикла
        apply_params   — записать пакет полей register'а (на прибор — колбэком подписки)
        list_devices   — перечислить приборы (владельцем при захвате, иначе потоком команды)
        describe_params — границы, шаг, имена enum и доступ узлов (нужен захват)
        trigger_software — программный триггер (нужен захват и capability `software_trigger`)
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
        "reset_stats": "cmd_reset_stats",
        "read_params": "cmd_read_params",
        "apply_params": "cmd_apply_params",
        "list_devices": "cmd_list_devices",
        "describe_params": "cmd_describe_params",
        "trigger_software": "cmd_trigger_software",
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
        self._events_lock = threading.Lock()  # сверка событий: снимок сеанса, инциденты и `merge` — одним куском
        self._published: dict = {}  # что уже в дереве; `merge` — только отличия
        self._seen_state: str | None = None
        self._reported_param_errors: set[str] = set()
        # счётчики `_frames`/`_dropped`/`_item_error`, окно fps и `reg.frames`: `produce()` (поток процесса) и
        # `reset_stats` (системный поток). Короткий: `publish_metric` и логи — вне замка. `self._lock` слота не годится
        self._stats_lock = threading.Lock()
        self._timing_lock = threading.Lock()  # `on_timing("get_frame")` приходит из потока-владельца на каждый кадр
        self._get_frame_n = 0
        self._get_frame_sum = 0.0
        self._tick_t0 = time.monotonic()
        self._tick_frames = 0
        self._log_bridge: _SessionLogBridge | None = None
        # (менеджер, поле, колбэк) для `unsubscribe`; повторный `configure` список не обнуляет (старые снимаются)
        self._subscriptions: list[tuple[Any, str, Callable[[Any], None]]] = getattr(self, "_subscriptions", [])
        self._plan_lock = threading.Lock()  # `_seen_values`: колбэки подписки идут из разных потоков
        self._seen_values: dict[str, Any] = {}  # значения привязанных полей, из которых построен идущий план run
        self._identity(warn=True)  # отказ рецепта — здесь, а не в take_device
        if self._reg.watchdog_s <= self._reg.timeout_ms / 1000.0:
            raise ValueError("watchdog_s должен быть больше timeout_ms/1000")
        for level in ("fps", "frames", "errors", "dropped", "pending", "param_errors_count"):
            ctx.declare_metric(level)
        self._subscribe_fields()

    # ------------------------------------------------------------------ #
    # Живая правка (Task 2.4b)
    # ------------------------------------------------------------------ #

    def _subscribe_fields(self) -> None:
        """Подписка на поля из `bindings()`; прежние подписки этого плагина снимаются (повторный `configure`)."""
        self._unsubscribe_fields()
        registers = self._ctx.registers
        if registers is None:
            self._ctx.log_warning("CameraDevicePlugin: нет RegistersManager, живая правка полей отключена")
            return
        for field in self.bindings():
            callback = functools.partial(self._on_field_update, field)  # свой объект на поле и на configure
            registers.subscribe(self.name, field, callback)
            self._subscriptions.append((registers, field, callback))

    def _unsubscribe_fields(self) -> None:
        """Снять подписки `_subscribe_fields`; повторный вызов — пустая операция."""
        subscriptions, self._subscriptions = self._subscriptions, []
        for registers, field, callback in subscriptions:  # менеджер тот, на котором подписались (ctx мог смениться)
            registers.unsubscribe(self.name, field, callback)

    def _changed_steps(self, field: str, before: Any, value: Any, retry: bool) -> tuple[list[Step], str]:
        """Шаги плана `run`, которые меняет правка поля: его собственный и шаги потомков по `enabled_if`.

        Сравниваются два полных плана при прочих равных значениях register'а: со старым и с новым значением поля.
        Смена родителя (`trigger_source`) включает или выключает потомка (`trigger_period_ms`): без этого сеанс
        переписал бы потомка в закрытый узел при перезахвате без `restart_regrab`. Шаг, остающийся `skip`, не меняется.
        `retry` — у поля есть отказ записи (`param_errors`): тот же шаг пишется повторно, даже если значение то же.
        Возврат: шаги (пусто — прибор не трогать) и причина для лога.
        """
        reg, bindings = self._reg, self.bindings()
        values = reg.model_dump()
        new = build_plan(type(reg), {**values, field: value}, bindings)
        own = next((step for step in new if step.field == field), None)
        if before is _MISSING:  # поле не входило в план, из которого строился цикл: только его собственный шаг
            steps = [] if own is None or own.skip is not None else [own]
        else:
            old = {step.field: step for step in build_plan(type(reg), {**values, field: before}, bindings)}
            steps = [step for step in new if old.get(step.field) != step and self._needs_apply(step, old)]
        if retry and own is not None and own.skip is None and own not in steps:
            steps.insert(0, own)
        if steps:
            return steps, ""
        return [], "нет шага" if own is None else own.skip or "значение не изменило план"

    @staticmethod
    def _needs_apply(step: Step, old: dict[str, Step]) -> bool:
        """Шаг пишется в прибор, либо он стал `skip` (сеанс заменит им прежний шаг в `run`); `skip` -> `skip` — нет."""
        if step.skip is None:
            return True
        before = old.get(step.field)
        return before is not None and before.skip is None

    def _apply_policy(self, field: str) -> str | None:
        """`FieldMeta.apply` поля register'а (`live` | `restart` | `config` | `None`)."""
        meta = type(self._reg).get_all_fields_meta().get(field)
        return None if meta is None else meta.apply

    def _on_field_update(self, field: str, value: Any) -> None:
        """Колбэк подписки (поток вызывающего `set_field_value`): порт не трогает, не блокирует, не бросает."""
        try:
            policy = self._apply_policy(field)
            session = self._session
            with self._plan_lock:
                before = self._seen_values.get(field, _MISSING)
                self._seen_values[field] = value
            if policy in (None, "config") or session is None:
                return  # сеанса нет: значение register'а войдёт в план следующего `take_device`
            steps, reason = self._changed_steps(field, before, value, field in session.param_errors)
            if not steps:
                self._ctx.log_info(f"CameraDevicePlugin: apply field={field} skip={reason}")
                return
            session.apply(steps, policy)  # политика вызвавшего поля — и у шагов его потомков
        except Exception as exc:  # noqa: BLE001 — колбэк идёт в системном потоке процесса: исключение наружу не выпускается
            self._ctx.health.report_error(exc, context="camera_device.live_apply", throttle=30.0)

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

    def software_trigger_binding(self) -> Binding:
        """Узел программного триггера для `trigger_software`. Вендор переопределяет, если узел называется иначе."""
        return Binding("genicam", "TriggerSoftware", "command")

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
        self._unsubscribe_fields()
        try:
            self.cmd_release_device({})
        finally:  # отказ release не оставляет мост на общем логгере
            bridge, self._log_bridge = self._log_bridge, None
            if bridge is not None:
                logging.getLogger("camera_device.session").removeHandler(bridge)

    def readiness(self, ctx: PluginContext) -> list[dict]:
        """Причина неготовности по состоянию сеанса камеры (Task 2.2c). Только чтение полей.

        Зовётся из потока снимка готовности (~2 Гц): БЕЗ замков (`_lock`, `_session_lock`,
        `session._lock`, `_profile.lock`), без IO, без `_ensure_session`. Читает один голый
        атрибут сеанса — `state` (`params*` берут замок, `last_error` несёт серийные номера и
        пути). `device_held` не читается: он не меняет ответ (пара `closed` + `device_held=True`
        — это `closed`), а лишнее чтение — лишняя гонка. Текст причины — литерал.
        """
        session = getattr(self, "_session", None)
        st = "idle" if session is None else session.state
        if st == "grabbing":
            return []
        if st == "opening":
            return [{"severity": "check_function", "reason": "камера открывается"}]
        if st == "stopping":
            return [{"severity": "out_of_spec", "reason": "камера останавливается"}]
        if st == "busy":
            return [{"severity": "failure", "reason": "камера занята"}]
        if st == "not_found":
            return [{"severity": "failure", "reason": "камера не найдена"}]
        if st == "error":
            return [{"severity": "failure", "reason": "ошибка камеры"}]
        if st in ("idle", "closed"):
            if self._reg.auto_start:
                return [{"severity": "check_function", "reason": "камера не запущена"}]
            return []
        return [{"severity": "failure", "reason": "состояние камеры неизвестно"}]

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
        self._sync_events()

    def _on_stall(self, call: str, seconds: float) -> None:
        """Сторож сеанса: вызов порта завис. Инцидент, затем дамп кольца (запись обязана в него попасть)."""
        self._ctx.health.report_error(
            CameraDeviceError(f"вызов порта {call} завис на {seconds:.1f} с"), context="camera_device.stall"
        )
        self._ctx.flight_dump("owner_stall", call=call, seconds=round(seconds, 1))

    def _on_timing(self, name: str, seconds: float) -> None:
        """Замер вызова порта (секунды). `get_frame` идёт на каждый кадр — копится, пишется окном (`_tick`)."""
        if name == "get_frame":
            with self._timing_lock:
                self._get_frame_n += 1
                self._get_frame_sum += seconds
        elif name == "open":
            self._ctx.record_timing("open_ms", seconds)
        elif name in ("apply", "regrab"):
            self._ctx.record_timing("regrab_ms" if name == "regrab" else "apply", seconds)
            # Правка применена потоком-владельцем: дерево не ждёт окна `produce()` (в паузе процесса его нет вовсе).
            # Только в `grabbing`: запись плана `run` при открытии покрывает `on_state(grabbing)`, лишних `merge` нет.
            session = self._session
            if session is not None and session.state == "grabbing":
                self._sync_events()

    def _tick(self) -> None:
        """Раз в `_TICK_S`: уровни, агрегат замера `get_frame`, сверка событий."""
        now = time.monotonic()
        with self._stats_lock:  # чтение счётчиков и сдвиг окна — одним куском: сброс между ними оставил бы старое число
            elapsed = now - self._tick_t0
            if elapsed < _TICK_S:
                return
            frames, dropped, window_frames = self._frames, self._dropped, self._tick_frames
            self._tick_t0, self._tick_frames = now, frames
        ctx, session = self._ctx, self._session
        if elapsed > 0:
            ctx.publish_metric("fps", (frames - window_frames) / elapsed)
        ctx.publish_metric("frames", frames)  # и без кадров: уровень виден с нулём, а не отсутствует
        ctx.publish_metric("errors", session.errors if session is not None else 0)
        ctx.publish_metric("dropped", dropped)
        ctx.publish_metric("pending", 0 if self._slot is None else 1)
        ctx.publish_metric("param_errors_count", len(session.param_errors) if session is not None else 0)
        with self._timing_lock:
            count, total = self._get_frame_n, self._get_frame_sum
            self._get_frame_n, self._get_frame_sum = 0, 0.0
        if count:
            ctx.record_timing("get_frame_ms", total / count)
        self._sync_events()

    def _sync_events(self) -> None:
        """Перечитать сеанс и опубликовать ОТЛИЧИЯ одним `merge`; инциденты — по смене, а не на каждый вызов.

        Зовётся из `on_state` (потоки вызывающего и владельца, не по порядку) и из окна: истина — свойства сеанса.
        `params`/`params_status`/`param_errors` берут замок профиля — из потока кадра не читаются.
        """
        session = self._session
        if session is None:
            return
        try:
            with self._events_lock:
                state = session.state
                param_errors = session.param_errors
                last_error = session.last_error
                self._report_incidents(state, last_error, param_errors)
                device = session.device
                snapshot = {
                    "state": state,
                    "device": None
                    if device is None
                    else {"kind": device.kind, "value": device.value, "name": device.name},
                    "device_held": session.device_held,
                    # rest в прибор пишется только после открытия: при отказе открытия (device None) профиля нет
                    "profile": _PROFILE_OF_STATE.get(state) if device is not None else None,
                    "params": session.params,
                    "params_status": session.params_status,
                    "param_errors": param_errors,
                    "last_error": last_error,
                    "capabilities": sorted(self._port.capabilities) if self._port is not None else [],
                }
                self._publish_events(snapshot)
        except Exception as exc:  # noqa: BLE001 — сбой публикации не должен ронять колбэк сеанса или `produce()`
            self._ctx.health.report_error(exc, context="camera_device.events", throttle=30.0)

    def _report_incidents(self, state: str, last_error: str | None, param_errors: dict) -> None:
        """Инцидент на переход в отказ и на каждый НОВЫЙ ключ `param_errors`; выход из отказа снимает `degraded`."""
        health = self._ctx.health
        previous, self._seen_state = self._seen_state, state
        if state != previous:
            if state in _FAILED:
                health.report_error(CameraDeviceError(f"{state}: {last_error or ''}"), context="camera_device.session")
                health.degraded(f"camera_device: {state}")
            elif previous in _FAILED:
                health.set_status("ok")
        for field, text in param_errors.items():
            if field not in self._reported_param_errors:
                health.report_error(CameraDeviceError(f"{field}: {text}"), context="camera_device.param")
        self._reported_param_errors = set(param_errors)

    def _publish_events(self, snapshot: dict) -> None:
        """Один `merge` отличий от уже опубликованного (под `_events_lock`); ушедшие ключи словарей — `delete`."""
        proxy = self._ctx.state_proxy
        if proxy is None:
            return
        changed = {key: value for key, value in snapshot.items() if self._published.get(key, _MISSING) != value}
        if not changed:
            return
        base = f"processes.{self._ctx.process_name}.state.plugins.{self.name}"
        for key in _DICT_EVENTS:
            for gone in (self._published.get(key) or {}).keys() - snapshot[key].keys():
                proxy.delete(f"{base}.{key}.{gone}")
        changed["ts"] = time.time()
        proxy.merge(base, changed)
        self._published = snapshot

    def produce(self) -> list[dict]:
        """Забрать кадр из слота в item. Пусто — норма. Не блокирует."""
        session = self._session
        # Сеанс при отказе снимает `device_held` без `on_state` (session.py): дереву не ждать окна `_TICK_S`.
        # Проверка — два чтения без замков; `merge` только если снимок действительно изменился (держит diff).
        if session is not None and self._published.get("device_held") is True and not session.device_held:
            self._sync_events()
        self._tick()
        with self._lock:
            slot, self._slot = self._slot, None
        if slot is None:
            return []
        try:
            item = self._build_item(*slot)
        except ValueError as exc:  # битый кадр отбрасывается: `produce()` не бросает, счётчик кадров не растёт
            self._drop_frame(str(exc))
            return []
        with self._stats_lock:  # пара «инкремент + запись поля»: сброс между ними вернул бы счётчик
            self._frames += 1
            self._reg.frames = self._frames
            frames = self._frames
        self._ctx.publish_metric("frames", frames)
        return [item]

    def _drop_frame(self, error: str) -> None:
        with self._stats_lock:
            self._dropped += 1
            new_reason = error != self._item_error
            self._item_error = error
        if new_reason:  # один журнал на причину, не на кадр (50 кадров/с)
            self._ctx.log_error(f"CameraDevicePlugin: кадр отброшен: {error}")

    @staticmethod
    def _frame_array(raw: RawFrame) -> np.ndarray:
        """Массив кадра по `pixel_format`: цветные (rgb8, bgr8, bayer_*8) -> (h, w, 3) BGR; mono8 -> (h, w).

        Raises:
            ValueError: формат не поддержан (bayer 10/12, mono16 и прочее), длина буфера не сходится с размером
                или дебайер отказал.
        """
        channels = _CHANNELS.get(raw.pixel_format)
        if channels is None:
            raise ValueError(f"неподдерживаемый pixel_format {raw.pixel_format}")
        expected = raw.height * raw.width * channels
        if len(raw.data) != expected:
            raise ValueError(f"длина буфера {len(raw.data)} не равна {expected} для {raw.pixel_format}")
        shape = (raw.height, raw.width, 3) if channels == 3 else (raw.height, raw.width)
        frame = np.frombuffer(raw.data, dtype=np.uint8).reshape(shape)
        if raw.pixel_format == "rgb8":
            return np.ascontiguousarray(frame[..., ::-1])  # вид с отрицательным шагом не contiguous: копия обязательна
        if raw.pixel_format.startswith("bayer_"):
            import cv2  # ленивый импорт: ядро без дебайера не тянет cv2

            try:
                return cv2.cvtColor(frame, getattr(cv2, _DEBAYER_CODE[raw.pixel_format]))
            except cv2.error as exc:  # `produce()` ловит только ValueError
                raise ValueError(f"дебайер {raw.pixel_format} не удался: {exc}") from exc
        return frame.copy()

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
            "pixel_format": "bgr8" if frame.ndim == 3 else raw.pixel_format,  # цветные источники уходят как BGR
            "source_format": raw.pixel_format,
            "width": raw.width,
            "height": raw.height,
            "device_frame_num": raw.frame_num,
        }

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def _ensure_port(self) -> DevicePort:
        """Порт плагина: создаётся один раз хуком `create_port()`; сеанс, мост логов и воркеры не создаются."""
        with self._session_lock:
            return self._port_locked()

    def _port_locked(self) -> DevicePort:
        """Порт при уже взятом `_session_lock` (`Lock` не реентерабелен: из-под замка зовётся только этот вариант)."""
        if self._port is None:
            self._port = self.create_port()  # сразу в атрибут; отказ `create_port` оставляет `None`: повтор возможен
        return self._port

    def _ensure_session(self) -> DeviceSession:
        with self._session_lock:
            if self._session is not None:
                return self._session
            port = self._port_locked()
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
                on_stall=self._on_stall,
                on_timing=self._on_timing,
            )
            self._attach_log_bridge()
            self._session = session  # порт уже в `self._port`; отказ `DeviceSession` сеанса не оставляет
        return session

    def _attach_log_bridge(self) -> None:
        """Строки `camera_device.session` -> журнал framework; уровень INFO ставится, только если не задан явно."""
        if self._log_bridge is not None:  # второй мост тому же плагину удвоил бы каждую строку
            return
        session_logger = logging.getLogger("camera_device.session")
        if session_logger.level == logging.NOTSET:
            session_logger.setLevel(logging.INFO)
        self._log_bridge = _SessionLogBridge(self._ctx)
        session_logger.addHandler(self._log_bridge)

    def cmd_take_device(self, data: dict) -> dict:
        """Открыть прибор и начать захват. Отказ — `status: error`, не исключение. `timeout_s` — срок `start`."""
        try:
            args = TakeDeviceArgs.model_validate(data or {})
        except ValidationError as exc:
            return {"status": "error", "device_state": self._reg.device_state, "error": _validation_text(exc)}
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
            if session.set_cycle(ident, run, rest):
                with self._plan_lock:  # из этих значений построен план run цикла: основа сравнения для живой правки
                    values = self._reg.model_dump()
                    self._seen_values = {field: values[field] for field in self.bindings() if field in values}
        except Exception as exc:  # noqa: BLE001 — контракт 1.8: отказ команды = status error, исключение наружу не идёт
            # хук вендора (`create_port`, `port.sdk`) может бросить что угодно: PortError, ImportError, OSError
            text = str(exc) if isinstance(exc, ValueError) else describe_error(exc)  # без значений рецепта
            # `describe_error` отдаёт только тип (`ImportError`, `OSError`): какая DLL — видно по следу в журнале
            detail = "" if isinstance(exc, ValueError) else f"\n{traceback.format_exc()}"
            self._ctx.log_error(f"CameraDevicePlugin: take_device отклонён: {text}{detail}")
            return {"status": "error", "device_state": self._reg.device_state, "error": text}
        t0 = time.monotonic()
        ok = session.start(args.timeout_s)
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
        """Остановить захват, закрыть прибор и отпустить SDK. `timeout_s` — срок `stop`."""
        try:
            args = ReleaseDeviceArgs.model_validate(data or {})
        except ValidationError as exc:
            return {"status": "error", "device_state": self._reg.device_state, "error": _validation_text(exc)}
        session = self._session
        if session is None:
            return {"status": "ok", "device_state": self._reg.device_state}
        session.stop(args.timeout_s)
        released = not session.device_held
        result: dict = {"status": "ok" if released else "error", "device_state": session.state}
        if not released:
            result["error"] = "поток-владелец ещё закрывает прибор"
        return result

    # ------------------------------------------------------------------ #
    # Команды Р7: 2.3c — без порта и ящика владельца, блокирующих вызовов нет; 2.3d (ниже) — через порт и ящик
    # ------------------------------------------------------------------ #

    def cmd_reset_stats(self, data: dict) -> dict:
        """Обнулить `frames` (счётчик, поле register'а, метрика), `dropped`, причину отброса и окно `fps`.

        НЕ сбрасываются: `errors` сеанса (счётчик жизни сеанса) и `seq_id` (Р10).
        """
        with self._stats_lock:
            self._frames = 0
            self._reg.frames = 0
            self._dropped = 0
            self._item_error = ""
            self._tick_frames = 0  # иначе следующее окно даст отрицательный `fps`
            self._tick_t0 = time.monotonic()
        self._ctx.publish_metric("frames", 0)  # дерево не ждёт окна `_TICK_S`
        self._ctx.log_info("CameraDevicePlugin: reset_stats")
        return {"success": True}

    def cmd_read_params(self, data: dict) -> dict:
        """Снимок `params` и `param_errors` последнего цикла сеанса (не живое чтение: порт не зовётся)."""
        session = self._session
        if session is None:
            return {"success": True, "params": {}, "param_errors": {}}
        return {"success": True, "params": session.params, "param_errors": session.param_errors}

    def cmd_apply_params(self, data: dict) -> dict:
        """Записать пакет `{поле: значение}` в register; на прибор значение доходит колбэком подписки 2.4b.

        Порядок проверок (всё до первой записи): модель -> `ctx.registers` -> поле из `bindings()` -> не `readonly` и
        хватает прав (`FieldMeta.can_modify(0)`, как у `set_field_value`) -> пробная запись всего пакета на копии
        register'а. `session.apply` отсюда не зовётся (удвоение с колбэком).
        `applied` = «принято register'ом»; результат на приборе приходит позже (`read_params` -> `param_errors`).
        """
        try:
            args = ApplyParamsArgs.model_validate(data)
        except ValidationError as exc:
            return self._apply_refused(_validation_text(exc))
        registers = self._ctx.registers
        if registers is None:
            return self._apply_refused("нет RegistersManager")
        params = args.params
        try:
            bindings = self.bindings()
        except Exception as exc:  # noqa: BLE001 — хук вендора: контракт 1.8, исключение наружу не идёт
            error = describe_error(exc)
            self._ctx.log_error(f"CameraDevicePlugin: apply_params: bindings() отказал: {error}")
            return self._apply_refused(error)
        for field in params:
            if field not in bindings:  # у `*_managed`, `timeout_ms` и т. п. нет подписки на прибор: `applied` солгал бы
                return self._apply_refused(f"поле не параметр прибора: {field!r}")
        fields_meta = type(self._reg).get_all_fields_meta()
        for field in params:
            meta = fields_meta.get(field)
            if meta is None:
                continue
            # проба на копии права не проверяет, а `set_field_value` — да (`access_level=0`): пакет писался бы частично
            if meta.readonly:  # свой текст: «Недостаточно прав доступа» register'а вводит в заблуждение
                return self._apply_refused(f"поле только для чтения: {field}")
            if not meta.can_modify(0):
                return self._apply_refused(f"недостаточно прав для поля: {field}")
        ok, error = self._reg.model_copy(deep=True).apply_values(params)  # проба всего пакета: всё или ничего
        if not ok:
            return self._apply_refused(error or "значение отвергнуто")
        applied: list[str] = []
        for field, value in params.items():  # порядок словаря: зависимые поля работают только в нём
            ok, error = registers.set_field_value(self.name, field, value)
            if not ok:  # остаточный случай: между пробой и записью значение register'а изменил другой писатель
                self._log_apply(applied, False)
                return {"success": False, "error": error or "значение отвергнуто", "applied": applied}
            applied.append(field)
        self._log_apply(applied, True)
        session = self._session
        on_device = (
            session is not None
            and session.state in ("opening", "grabbing")
            and any(self._apply_policy(field) in ("live", "restart") for field in applied)
        )
        return {"success": True, "applied": applied, "on_device": on_device}

    def _apply_refused(self, error: str) -> dict:
        """Отказ `apply_params` до первой записи."""
        self._log_apply([], False)
        return {"success": False, "error": error}

    def _log_apply(self, fields: list[str], ok: bool) -> None:
        """INFO `apply_params`: имена записанных полей и итог, без значений."""
        self._ctx.log_info(f"CameraDevicePlugin: apply_params fields={fields} ok={ok}")

    # --- Команды Р7 с портом (Task 2.3d): порт зовёт тот поток, который его держит ---

    def _port_or_refusal(self) -> DevicePort | dict:
        """Порт либо ответ-отказ (`dict`): `ValueError` — свой текст, как в `take_device`, прочее — `describe_error`."""
        try:
            return self._ensure_port()
        except Exception as exc:  # noqa: BLE001 — контракт 1.8: отказ команды — ответ, исключение наружу не идёт
            text = str(exc) if isinstance(exc, ValueError) else describe_error(exc)
            detail = "" if isinstance(exc, ValueError) else f"\n{traceback.format_exc()}"
            self._ctx.log_error(f"CameraDevicePlugin: порт не создан: {text}{detail}")
            return {"success": False, "error": text}

    def _call_owner(self, fn: Callable[[], Any]) -> tuple[bool, Any]:
        """`fn` в потоке-владельце: `(True, результат)` либо `(False, текст отказа)`. Блокирует до `_CALL_TIMEOUT_S`."""
        session = self._session
        if session is None:
            return False, _NOT_GRABBING
        return session.call(fn, _CALL_TIMEOUT_S)

    def cmd_list_devices(self, data: dict) -> dict:
        """Перечислить приборы: `{"success": True, "devices": [{"kind", "value", "name"}]}`.

        Перечисление исполняет тот, кто держит SDK; путь — по `session.device_held`, а не по `state` (`stop()` на
        отказном состоянии ставит `closed` СРАЗУ, пока владелец ещё закрывает порт):
          * владельца нет -> поток команды: `acquire`, затем `enum_devices` и `release` (в `finally`, только после
            успешного `acquire`), без handle и без сеанса;
          * владелец есть -> `session.call(enum_devices)`; не `grabbing` (`opening`, `stopping`, отказ при живом
            владельце) `call` отвечает `"сеанс не в захвате"`, порт не вызывается.
        Остаточный риск: между проверкой `device_held` и `acquire` команда не конкурирует с `start()` только пока оба
        идут из системного потока (`cmd_take_device`); `start()` из другого потока не проверялся.
        """
        port = self._port_or_refusal()
        if isinstance(port, dict):
            return port
        session = self._session
        t0 = time.monotonic()
        path = "command" if session is None or not session.device_held else "owner"
        try:
            if path == "command":
                devices = self._enumerate_here(port)
            else:
                ok, result = self._call_owner(lambda: port.sdk.enum_devices())
                if not ok:
                    self._ctx.log_info(f"CameraDevicePlugin: list_devices path={path} error={result}")
                    return {"success": False, "error": result}
                devices = result
        except Exception as exc:  # noqa: BLE001 — отказ `acquire`/`enum_devices`/`release` (обычно `PortError`) — ответ
            error = describe_error(exc)
            self._ctx.log_error(f"CameraDevicePlugin: list_devices path={path} отказ: {error}")
            return {"success": False, "error": error}
        ms = int((time.monotonic() - t0) * 1000)
        self._ctx.log_info(f"CameraDevicePlugin: list_devices path={path} n={len(devices)} ms={ms}")
        return {
            "success": True,
            "devices": [{"kind": d.kind, "value": d.value, "name": d.name} for d in devices],
        }

    @staticmethod
    def _enumerate_here(port: DevicePort) -> list[DeviceIdentity]:
        """Перечисление потоком команды, пока владельца нет; `release` стартует только после успешного `acquire`."""
        sdk = port.sdk
        sdk.acquire()
        try:
            return sdk.enum_devices()
        finally:
            sdk.release()

    def cmd_describe_params(self, data: dict) -> dict:
        """Описание узлов по ВСЕМ привязкам `bindings()`: `{"success": True, "params_meta": {поле: {...} | None}}`.

        Снимок текущего состояния, нужен захват: границы и `access` у узлов зависят от соседних (у фейка `TriggerMode`
        при захвате `RO`). Один `session.call`: `port.describe_param` зовёт владелец. Нет capability `node_describe` ->
        пустая карта без вызова порта. Узел, давший `None` или `PortError`, -> `null`; остальные не падают.
        """
        port = self._port_or_refusal()
        if isinstance(port, dict):
            return port
        if "node_describe" not in port.capabilities:
            return {"success": True, "params_meta": {}}
        try:
            bindings = self.bindings()
        except Exception as exc:  # noqa: BLE001 — хук вендора: контракт 1.8, исключение наружу не идёт
            error = describe_error(exc)
            self._ctx.log_error(f"CameraDevicePlugin: describe_params: bindings() отказал: {error}")
            return {"success": False, "error": error}
        t0 = time.monotonic()
        ok, result = self._call_owner(lambda: {field: self._describe_node(port, b) for field, b in bindings.items()})
        if not ok:
            self._ctx.log_info(f"CameraDevicePlugin: describe_params error={result}")
            return {"success": False, "error": result}
        ms = int((time.monotonic() - t0) * 1000)
        self._ctx.log_info(f"CameraDevicePlugin: describe_params n={len(result)} ms={ms}")
        return {"success": True, "params_meta": result}

    @staticmethod
    def _describe_node(port: DevicePort, binding: Binding) -> dict | None:
        """Описание узла словарём (`entries` — список: Dict at Boundary); отказ узла -> `None`. Зовёт владелец."""
        try:
            info = port.describe_param(binding)
        except PortError:
            return None
        if info is None:
            return None
        entries = None if info.entries is None else list(info.entries)
        return {"min": info.min, "max": info.max, "inc": info.inc, "entries": entries, "access": info.access}

    def cmd_trigger_software(self, data: dict) -> dict:
        """Программный триггер: `port.execute(software_trigger_binding())` потоком-владельцем; ~2 Гц (после 1.0).

        Порядок: порт -> capability `software_trigger` (статична на жизнь порта, вызова порта нет) -> захват -> `call`.
        """
        port = self._port_or_refusal()
        if isinstance(port, dict):
            return port
        if "software_trigger" not in port.capabilities:
            return {"success": False, "error": "нет capability software_trigger"}
        ok, result = self._call_owner(lambda: port.execute(self.software_trigger_binding()))
        self._ctx.log_info(f"CameraDevicePlugin: trigger_software ok={ok}")
        return {"success": True} if ok else {"success": False, "error": result}

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
