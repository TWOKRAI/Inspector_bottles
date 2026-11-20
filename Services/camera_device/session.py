# -*- coding: utf-8 -*-
"""Сеанс прибора `DeviceSession` (Task 2.1): поток-владелец, жизненный цикл, ошибки кадра, сторож.

Все вызовы порта и `DeviceSdk` (`acquire`, `enum_devices`, `open`, `start_grabbing`, `get_frame`,
`stop_grabbing`, `close`, `release`) идут ТОЛЬКО из потока-владельца: один владелец на цикл
`open -> close`, новый `start()` после остановки — новый поток. Потоки владельца и сторожа — воркеры `WorkerManager`
процесса (параметр `workers`; `worker_prefix` уникален на сеанс в менеджере).

Состояния: `idle` (до первого `start`), `opening`, `grabbing`, `stopping`, `closed` (покой после остановки),
`busy`, `not_found`, `error` (отказ; автопереподключения нет, ADR-CR-009). Переходы — только
compare-and-set под замком состояния; `on_state`, `on_stall`, `on_timing` зовутся вне замка.
`on_state` приходит из потока, сменившего состояние (вызывающего или владельца), поэтому из РАЗНЫХ потоков и
может прийти не по порядку: истина — свойство `state`, потребитель при событии перечитывает его.

Свойство для вызывающего: задержка исполнения команды ≤ таймаута кадра (≤ 500 мс): `stop()` ждёт выхода
владельца не дольше `timeout + timeout_ms/1000`, потому что `get_frame` не будится `close`. GigE `open`
(1–3 с) держит командный поток — допустимо при Р1. Поток исполнения команд фреймворка один, поэтому
блокирующие `start(timeout)` (до `timeout`; после того как владелец перешёл к `start_grabbing` — ещё до
`watchdog_s`) и `stop(timeout)` (до `timeout + 0,5 с`) задерживают приём команд
процесса.

Ящик владельца (Task 2.4a): другие потоки не трогают порт, а кладут команды в ящик цикла (`submit`, `call`,
`apply`); владелец опрашивает ящик после КАЖДОГО возврата `get_frame` (кадр, `None`, `PortError`), поэтому
команда ждёт не дольше `timeout_ms` (а при зависании `get_frame` — до его возврата). `apply` не блокирует и
сливает правки полей в одну команду `_drain`; перезахват порта идёт ВНУТРИ `grabbing`: `state` не меняется,
`on_state` не зовётся. `apply` принимается и в `opening` (исполняется сразу после входа в `grabbing`).

Слой: stdlib, `.interface`/`.params`/`.profiles` и публичный `multiprocess_framework.modules.worker_module`;
без `multiprocess_prototype` и вендоров.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig, WorkerType

from .interface import DeviceIdentity, DevicePort, DeviceSdk, PortError, RawFrame
from .params import Step
from .profiles import ProfileRunner, ProfileState

logger = logging.getLogger("camera_device.session")

# Подряд идущих ошибок `get_frame` до перехода в `error`.
MAX_CONSECUTIVE_ERRORS = 3
# Состояния отказа: `device_held` ещё может быть истинным, пока владелец закрывает порт.
_FAILED = frozenset({"busy", "not_found", "error"})
# Вызовы порта, для которых зовётся `on_timing` (секунды).
_TIMED = frozenset({"open", "stop_grabbing", "get_frame"})


# Занятые имена воркеров по менеджеру: второй сеанс с тем же `worker_prefix` запустил бы цель первого.
_CLAIMS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


class _StartCmd:
    """Команда `start` одного цикла: итог владельца и решение «откат или фиксация» (под замком сеанса)."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result = False
        self.cancelled = False  # вызывающий истёк по сроку: владелец откатывает цикл
        self.committed = False  # владелец перешёл к `start_grabbing`: откат уже невозможен

    def finish(self, result: bool) -> None:
        if not self.done.is_set():
            self.result = result
            self.done.set()


class _Cmd:
    """Команда ящика владельца: `fn` исполняет ТОЛЬКО поток-владелец; «исполнить или отменить» решает замок сеанса.

    `error` — текст отказа (`None` — успех, ответ в `result`); `cancelled` — вызывающий истёк по сроку до исполнения;
    `committed` — владелец взял команду на исполнение, отмена уже невозможна (модель `_StartCmd`).
    """

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.fn = fn
        self.done = threading.Event()
        self.result: Any = None
        self.error: str | None = None
        self.cancelled = False
        self.committed = False


class _Box:
    """Ящик одного цикла: очередь команд; `closed` ставит владелец при выходе, оба поля — под замком сеанса."""

    def __init__(self, closed: bool = False) -> None:
        self.cmds: deque[_Cmd] = deque()
        self.closed = closed


class _Hold:
    """Что владелец держит у порта сейчас (пишет и читает только он): по этому `_cleanup` решает, что закрывать."""

    def __init__(self) -> None:
        self.acquired = False
        self.opened = False
        self.grabbing = False


class _Call:
    """Текущий вызов порта для сторожа; `reported` — «уже сообщено» (один `on_stall` на вызов)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.t0 = time.perf_counter()
        self.reported = False


def describe_error(exc: BaseException) -> str:
    """Текст для `last_error`: тип, `kind`, `code` (для `PortError` ещё `str(exc)`); без значений рецепта."""
    if isinstance(exc, PortError):
        code = "" if exc.code is None else f" code=0x{exc.code:08X}"
        return f"{type(exc).__name__} kind={exc.kind}{code}: {exc}"
    return type(exc).__name__


class DeviceSession:
    """Сеанс одного прибора: владелец-поток держит порт, остальные потоки только ставят `start`/`stop`."""

    def __init__(
        self,
        port: DevicePort,
        sdk: DeviceSdk,
        ident: DeviceIdentity | None = None,
        *,
        timeout_ms: int = 500,
        watchdog_s: float = 5.0,
        on_frame: Callable[[RawFrame], None],
        workers: Any,
        worker_prefix: str = "camera_device",
        on_stall: Callable[[str, float], None] | None = None,
        on_state: Callable[[str, str], None] | None = None,
        on_timing: Callable[[str, float], None] | None = None,
        run: Sequence[Step] = (),
        rest: Sequence[Step] = (),
    ) -> None:
        if watchdog_s <= timeout_ms / 1000.0:
            raise ValueError("watchdog_s должен быть больше timeout_ms/1000")
        # Потоки владельца и сторожа — воркеры `WorkerManager` процесса (утиный интерфейс: create_worker,
        # start_worker, has_worker); сеанс сам потоков не создаёт. Имена должны быть уникальны в менеджере.
        self._workers = workers
        self._owner_name = f"{worker_prefix}_owner"
        self._wd_name = f"{worker_prefix}_watchdog"
        self._wd_stop = threading.Event()
        self._wd_thread: threading.Thread | None = None
        self._wd_started = threading.Event()
        self._port = port
        self._sdk = sdk
        self._ident = ident
        self._timeout_ms = timeout_ms
        self._watchdog_s = watchdog_s
        self._on_frame = on_frame
        self._on_stall = on_stall
        self._on_state = on_state
        self._on_timing = on_timing
        self._run = tuple(run)  # применяет Task 2.2
        self._rest = tuple(rest)

        self._lock = threading.Lock()  # состояние, _held, _cmd, _owner; не держится при join и ожидании
        self._state = "idle"
        self._held = False
        self._owner: threading.Thread | None = None
        self._cmd: _StartCmd | None = None
        self._stop_evt = threading.Event()
        self._exited = threading.Event()  # цикл вышел: создаётся в start() под замком, ставится владельцем
        self._exited.set()
        self._current: _Call | None = None
        self._cycle_t0 = 0.0
        self._errors = 0
        self._last_error: str | None = None
        self._device: DeviceIdentity | None = None
        self._profile = ProfileState()  # профили run/rest (Task 2.2); замок и данные принадлежат сеансу
        self._runner: ProfileRunner | None = None
        self._box = _Box(closed=True)  # ящик цикла: создаётся в start() под замком вместе с `_stop_evt`
        self._pending: dict[str, tuple[Step, str]] = {}  # слитые правки `apply`: поле -> (шаг, политика); под замком
        self._drain_queued = False  # в ящике уже лежит `_drain`; под замком
        self._hold = _Hold()
        self._stop_now: Callable[[], bool] = lambda: True  # стоп цикла или процесса (ставит владелец)
        self._regrab_failed = False  # перезахват отказал: цикл завершается (пишет и читает только владелец)

    # ------------------------------------------------------------------ #
    # Свойства
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> str:
        return self._state

    @property
    def errors(self) -> int:
        """Ошибки кадров за жизнь сеанса + отказы узлов профилей (не сбрасывается `start()`)."""
        return self._errors + self._profile.node_errors

    @property
    def params(self) -> dict:
        with self._profile.lock:
            return dict(self._profile.params)

    @property
    def params_status(self) -> dict:
        with self._profile.lock:
            return {k: dict(v) for k, v in self._profile.status.items()}

    @property
    def param_errors(self) -> dict:
        with self._profile.lock:
            return dict(self._profile.errors)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def device(self) -> DeviceIdentity | None:
        return self._device

    @property
    def device_held(self) -> bool:
        """Поток-владелец жив (снимается им при выходе, вместе с финальным состоянием)."""
        return self._held

    # ------------------------------------------------------------------ #
    # Команды (потоки вызывающих)
    # ------------------------------------------------------------------ #

    def set_cycle(self, ident: DeviceIdentity | None, run: Sequence[Step], rest: Sequence[Step]) -> bool:
        """Заменить идентичность прибора и план run/rest для СЛЕДУЮЩЕГО цикла (один сеттер на весь цикл).

        Под замком сеанса (тем же, что у `start()`): пока поток-владелец жив (`device_held`), цикл не меняется
        и возвращается `False` без исключения; иначе — `True`. `timeout_ms` и `watchdog_s` не меняются.
        """
        with self._lock:
            if self._held:
                return False
            self._ident = ident
            self._run = tuple(run)
            self._rest = tuple(rest)
            return True

    def start(self, timeout: float = 5.0) -> bool:
        """Начать захват: `True` — захват идёт.

        Из `stopping`, из потока владельца и при живом владельце — `False` сразу, без очереди.
        """
        if threading.current_thread() is self._owner:
            return False
        pending: list[tuple[str, str]] = []
        creator = False
        prev: threading.Thread | None = None
        with self._lock:
            state = self._state
            if state == "grabbing":
                return True
            if state == "stopping":
                return False
            if state == "opening":
                cmd = self._cmd
            elif self._held:  # busy/not_found/error/closed при живом владельце: автопереподключения нет
                return False
            else:
                cmd = self._cmd = _StartCmd()
                creator = True
                self._stop_evt = threading.Event()
                self._exited = threading.Event()
                self._box = _Box()
                self._pending.clear()
                self._drain_queued = False
                self._last_error = None  # успешный захват после неудачного не показывает старую ошибку
                self._held = True
                self._cycle_t0 = time.monotonic()
                self._set_locked("opening", pending)
                prev = self._owner
        self._fire_states(pending)
        assert cmd is not None
        if creator and not self._launch_owner(prev, cmd):
            return False
        if cmd.done.wait(timeout):
            return cmd.result
        with self._lock:
            if cmd.done.is_set():
                return cmd.result
            if not creator:
                return False  # свой срок joiner'а: чужой цикл не отменяется
            if not cmd.committed:
                cmd.cancelled = True  # владелец откатит цикл после open / _apply_run
                return False
        # Владелец уже зовёт `start_grabbing`: ждём итог не дольше `watchdog_s` (дольше — зависание, его ловит сторож).
        if cmd.done.wait(self._watchdog_s):
            return cmd.result
        with self._lock:
            if cmd.done.is_set():
                return cmd.result
            cmd.cancelled = True  # владелец, вернувшись из `start_grabbing`, откатит цикл
            return False

    def stop(self, timeout: float = 2.0) -> None:
        """Остановить захват; не отбрасывается. `timeout` — только срок ожидания вызывающего."""
        pending: list[tuple[str, str]] = []
        with self._lock:
            state = self._state
            if state in ("idle", "closed", "stopping"):
                return
            exited = self._exited
            if state in _FAILED:
                self._set_locked("closed", pending)  # порт не зовётся: владелец уже закрывает его сам
            else:
                self._set_locked("stopping", pending)
                self._stop_evt.set()
        self._fire_states(pending)
        if threading.current_thread() is self._owner:
            return  # из on_frame: самосоединения нет, владелец сам завершит цикл
        exited.wait(timeout + self._timeout_ms / 1000.0)  # событие цикла, а не Thread: владелец мог ещё не стартовать

    # ------------------------------------------------------------------ #
    # Ящик владельца (Task 2.4a): команды из других потоков, исполняет только владелец
    # ------------------------------------------------------------------ #

    def submit(self, fn: Callable[[], Any]) -> bool:
        """Положить `fn` в ящик владельца; не блокирует, срока нет. `False` — не поставлено (не `grabbing`/ящик закрыт).

        Результат и исключение `fn` пропадают (для ответа — `call`); `fn` исполняется потоком-владельцем вне замка.
        """
        return self._enqueue(fn) is not None

    def call(self, fn: Callable[[], Any], timeout: float) -> tuple[bool, Any]:
        """`fn` в потоке-владельце и ожидание ответа: `(True, результат)` либо `(False, текст отказа)`.

        По сроку, пока владелец `fn` не взял, команда отменяется (не исполнится и позже), ответ `(False, "срок")`; если
        владелец уже исполняет `fn`, ждём ещё не дольше `watchdog_s`. Остановка отвечает `(False, "сеанс остановлен")`.
        Из потока владельца (например, из `on_frame`) — `(False, ...)` сразу: сам себя владелец не дождётся.
        Блокирующий: колбэк системного потока зовёт только `apply`.
        """
        if threading.current_thread() is self._owner:
            return False, "вызов из потока владельца"
        # В ящик идёт обёртка `_port_call("call", fn)`: она выставляет `_current`, и сторож видит зависший `fn`. Именно
        # здесь, а не в `_execute`: вложенный `_port_call` из `_drain` сбросил бы `_current` внешнего вызова.
        cmd = self._enqueue(lambda: self._port_call("call", fn))
        if cmd is None:
            return False, "сеанс не в захвате"
        if cmd.done.wait(timeout):
            return self._answer(cmd)
        with self._lock:
            if cmd.done.is_set():
                return self._answer(cmd)
            if not cmd.committed:
                cmd.cancelled = True  # владелец, дойдя до команды, пропустит её
                return False, "срок"
        # Владелец уже исполняет `fn`: отменить нельзя, ждём не дольше `watchdog_s` (дольше — зависание, ловит сторож).
        if cmd.done.wait(self._watchdog_s):
            return self._answer(cmd)
        return False, "срок"

    def apply(self, steps: Sequence[Step], policy: str) -> None:
        """Применить пакет правок полей к идущему захвату (`policy`: `live`/`restart`); не блокирует, из любого потока.

        Шаги сливаются в `_pending` по полю (последнее значение побеждает), в ящик ставится ОДНА команда `_drain`;
        порт трогает только владелец. Принимается в `opening` (владелец исполнит `_drain` сразу после входа в
        `grabbing`, до первого `get_frame`) и в `grabbing`. В `stopping`/`closed`/отказе или при закрытом ящике правка
        не принимается: значение register'а попадёт в прибор планом `run` следующего цикла.
        """
        if policy not in ("live", "restart"):
            raise ValueError("policy должна быть live или restart")
        if not steps:
            return
        with self._lock:
            accepted = self._state in ("opening", "grabbing") and not self._box.closed
            if accepted:
                for step in steps:
                    self._pending[step.field] = (step, policy)
                if not self._drain_queued:
                    self._drain_queued = True
                    self._box.cmds.append(_Cmd(self._drain))
        if not accepted:
            logger.info("apply policy=%s: цикл не идёт, правка не принята (значения войдут в план run)", policy)

    def _enqueue(self, fn: Callable[[], Any]) -> _Cmd | None:
        with self._lock:
            if self._state != "grabbing" or self._box.closed:
                return None
            cmd = _Cmd(fn)
            self._box.cmds.append(cmd)
            return cmd

    @staticmethod
    def _answer(cmd: _Cmd) -> tuple[bool, Any]:
        return (True, cmd.result) if cmd.error is None else (False, cmd.error)

    # ------------------------------------------------------------------ #
    # Состояние
    # ------------------------------------------------------------------ #

    def _set_locked(self, new: str, pending: list[tuple[str, str]]) -> None:
        old = self._state
        if old != new:
            self._state = new
            pending.append((old, new))

    def _cas(self, expected: tuple[str, ...], new: str) -> bool:
        """Compare-and-set: `grabbing` не перезаписывает `stopping`; `on_state` — вне замка."""
        pending: list[tuple[str, str]] = []
        with self._lock:
            if self._state not in expected:
                return False
            self._set_locked(new, pending)
        self._fire_states(pending)
        return True

    def _fire_states(self, pending: list[tuple[str, str]]) -> None:
        for old, new in pending:
            ms = int((time.monotonic() - self._cycle_t0) * 1000)
            device_id = self._device.value if self._device is not None else ""
            logger.info("session state=%s->%s device_id=%s ms=%d", old, new, device_id, ms)
            self._notify(self._on_state, old, new)

    @staticmethod
    def _notify(callback: Callable | None, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 — колбэк плагина не должен ронять владельца или сторожа
            logger.exception("session: колбэк %s завершился исключением", getattr(callback, "__name__", callback))

    # ------------------------------------------------------------------ #
    # Поток-владелец
    # ------------------------------------------------------------------ #

    def _port_call(self, name: str, fn: Callable, *args):
        """Вызов порта/SDK с записью для сторожа и `on_timing` (секунды)."""
        call = _Call(name)
        self._current = call
        try:
            return fn(*args)
        finally:
            self._current = None
            if name in _TIMED:
                self._notify(self._on_timing, name, time.perf_counter() - call.t0)

    def _timing(self, name: str, seconds: float) -> None:
        self._notify(self._on_timing, name, seconds)

    def _fail(self, state: str, exc: BaseException) -> None:
        self._last_error = describe_error(exc)
        logger.error("session: %s", self._last_error)
        self._cas(("opening", "grabbing"), state)

    def _launch_owner(self, prev: threading.Thread | None, cmd: _StartCmd) -> bool:
        """Запустить воркер владельца. `start_worker` вернёт `True` без нового потока, пока прежний жив, поэтому
        сначала ждём его выхода (вне замка, не дольше `watchdog_s`). Отказ -> откат цикла: `error`, `held` снят."""
        reason = ""
        if prev is not None and prev is not threading.current_thread():
            prev.join(self._watchdog_s)
            if prev.is_alive():
                reason = "прежний поток-владелец не завершился"
        if not reason:
            try:
                self._ensure_workers()
                if not self._workers.start_worker(self._owner_name):
                    reason = "воркер владельца не запущен"
            except Exception as exc:  # noqa: BLE001 — отказ менеджера воркеров -> откат цикла
                reason = (
                    str(exc) if isinstance(exc, ValueError) else describe_error(exc)
                )  # текст ValueError — наш, без значений
        if not reason:
            return True
        self._last_error = reason
        logger.error("session: %s", reason)
        pending: list[tuple[str, str]] = []
        with self._lock:
            self._set_locked("error", pending)
            self._held = False
            self._exited.set()
            self._box.closed = True  # владелец не запускался: принятые в `opening` правки не исполнятся
            self._pending.clear()
            self._drain_queued = False
        self._fire_states(pending)
        cmd.finish(False)
        return False

    def _ensure_workers(self) -> None:
        """Лениво зарегистрировать воркеры: владелец (TASK на цикл) и сторож (LOOP, опрос).

        Имя занято другим сеансом -> `ValueError` (его ловит `_launch_owner`): `worker_prefix` уникален на сеанс.
        """
        try:
            claims = _CLAIMS.setdefault(self._workers, {})
        except TypeError:  # менеджер без weakref: проверка занятости недоступна
            claims = {}
        for name in (self._owner_name, self._wd_name):
            holder = claims.get(name)
            if holder is not None and holder() not in (None, self):
                raise ValueError("worker_prefix занят другим сеансом")
            claims[name] = weakref.ref(self)
        for name, target, mode in (
            (self._owner_name, self._owner_main, ExecutionMode.TASK),
            (self._wd_name, self._watchdog_main, ExecutionMode.LOOP),
        ):
            if not self._workers.has_worker(name):
                config = ThreadConfig(worker_type=WorkerType.SYSTEM, restart_on_failure=False, execution_mode=mode)
                self._workers.create_worker(name, target, config, auto_start=False)

    def _commit(self, cmd: _StartCmd, stop_evt: Callable[[], bool]) -> bool:
        """Решение «откат или фиксация» под замком: кто первый — тот решил."""
        with self._lock:
            if cmd.cancelled or stop_evt():
                return False
            cmd.committed = True
            return True

    def _enter_grabbing(self, cmd: _StartCmd, stop_evt: Callable[[], bool]) -> bool:
        """После `start_grabbing` под замком: отмена/стоп -> откат (`False`), иначе `grabbing` и итог `True`.

        Ответ `start()` всегда равен реальному состоянию: `True` только если цикл остался `grabbing`.
        """
        pending: list[tuple[str, str]] = []
        with self._lock:
            abort = cmd.cancelled or stop_evt()
            if not abort:
                self._set_locked("grabbing", pending)
            # Итог выставляется под тем же замком, что и решение: вызывающий по сроку (start) видит либо
            # `done`, либо ещё не принятое решение — но не «решено, итога нет» (иначе медленный on_state даёт
            # ответ False при state grabbing).
            cmd.finish(not abort)
        self._fire_states(pending)
        return not abort

    def _apply_run(self) -> None:
        """Профиль `run` между `open` и `start_grabbing` (владелец)."""
        self._runner.apply_plan(self._run)  # type: ignore[union-attr]

    def _apply_rest(self, grabbing: bool) -> bool:
        """Профиль `rest` после `stop_grabbing` до `close`; `False` — `open` ветки reopen упал, `close` не зовётся."""
        if not self._rest:
            return True
        direct = "restart_regrab" in self._port.capabilities or not grabbing  # H1: NETER снимает только close
        return self._runner.run_rest(self._rest, direct)  # type: ignore[union-attr]

    def _owner_main(self, worker_stop: threading.Event, pause: threading.Event) -> None:
        """TASK-воркер на цикл `open -> close`: поток-владелец порта. Стоп процесса (`worker_stop`) = стоп цикла."""
        self._owner = threading.current_thread()
        with self._lock:
            cmd, cycle_stop, exited, box = self._cmd, self._stop_evt, self._exited, self._box
        assert cmd is not None
        stop_evt = lambda: cycle_stop.is_set() or worker_stop.is_set()  # noqa: E731
        self._stop_now = stop_evt
        self._start_watchdog()
        hold = self._hold = _Hold()
        self._regrab_failed = False
        run_applied = failed = False
        self._profile.reset()  # начало run каждого start(): params / params_status / param_errors заново
        try:
            self._port_call("acquire", self._sdk.acquire)
            hold.acquired = True
            ident = self._resolve_ident()
            self._port_call("open", self._port.open, ident)
            hold.opened = True
            self._device = ident
            self._runner = ProfileRunner(self._port, ident, self._profile, logger, self._timing, self._port_call)
            self._apply_run()
            run_applied = True
            if self._commit(cmd, stop_evt):
                self._port_call("start_grabbing", self._port.start_grabbing)
                hold.grabbing = True
                if self._enter_grabbing(cmd, stop_evt):
                    failed = not self._grab_loop(stop_evt, box)
        except PortError as exc:
            failed = True
            self._fail(_failed_state(exc, opening=not hold.opened), exc)
        except Exception as exc:  # noqa: BLE001 — любой отказ владельца -> error, порт закрывается ниже
            failed = True
            self._fail("error", exc)
        finally:
            cmd.finish(False)  # no-op, если итог уже `True`
            self._close_box(box)  # до закрытия порта: оставшиеся команды получают ответ раньше, чем вернётся `stop()`
            # `rest` — только на открытом порту: стоп в окне перезахвата мог оставить порт закрытым
            self._cleanup(hold.grabbing, run_applied and not failed and hold.opened, hold.opened, hold.acquired)
            self._stop_watchdog()
            with self._lock:
                pending: list[tuple[str, str]] = []
                if self._state not in _FAILED:
                    self._set_locked("closed", pending)
                self._held = False  # снимается вместе с финальным состоянием
                exited.set()
            self._fire_states(pending)

    def _resolve_ident(self) -> DeviceIdentity:
        found = self._port_call("enum_devices", self._sdk.enum_devices)
        if self._ident is not None:
            found = [d for d in found if (d.kind, d.value) == (self._ident.kind, self._ident.value)]
        if not found:
            raise PortError("not_found", "enum_devices")
        return found[0]

    def _cleanup(self, grabbing: bool, apply_rest: bool, opened: bool, acquired: bool) -> None:
        """`stop_grabbing`, `rest`, `close`, `release` — каждый шаг независим: отказ одного не отменяет остальные."""
        steps: list[tuple[str, Callable]] = []
        if grabbing:
            steps.append(("stop_grabbing", self._port.stop_grabbing))
        if apply_rest:
            steps.append(("rest", self._apply_rest))
        if opened:
            steps.append(("close", self._port.close))
        if acquired:
            steps.append(("release", self._sdk.release))
        skip_close = False
        for name, fn in steps:
            if name == "close" and skip_close:
                continue  # reopen не удался: порт уже закрыт
            try:
                if name == "rest":
                    skip_close = fn(grabbing) is False
                else:
                    self._port_call(name, fn)
            except Exception as exc:  # noqa: BLE001 — остальные шаги закрытия обязаны выполниться
                logger.exception("session: %s при закрытии не удался", name)
                if self._last_error is None:
                    self._last_error = describe_error(exc)

    def _grab_loop(self, stop_evt: Callable[[], bool], box: _Box) -> bool:
        """Читать кадры до `stop_evt`; `False` — три ошибки подряд или отказ перезахвата (состояние уже `error`).

        Ящик опрашивается после КАЖДОГО возврата `get_frame` (кадр, `None`, `PortError`).
        """
        if not self._poll_box(box, stop_evt):  # правки, принятые в `opening`: до первого `get_frame`
            return False
        consecutive = 0
        while not stop_evt():
            raw = None
            try:
                raw = self._port_call("get_frame", self._port.get_frame, self._timeout_ms)
            except PortError as exc:
                self._errors += 1
                consecutive += 1
                self._last_error = describe_error(exc)
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    self._fail("error", exc)
                    return False
            else:
                consecutive = 0  # кадр и таймаут (None) — не ошибки
            if not self._poll_box(box, stop_evt):
                return False
            if raw is None:
                continue
            try:
                self._on_frame(raw)
            except Exception:  # noqa: BLE001 — исключение колбэка не ошибка порта, захват не останавливается
                logger.exception("session: on_frame завершился исключением")
        return True

    # ------------------------------------------------------------------ #
    # Ящик: исполнение команд владельцем
    # ------------------------------------------------------------------ #

    def _poll_box(self, box: _Box, stop_evt: Callable[[], bool]) -> bool:
        """Исполнить команды ящика (владелец, вне замка); `False` — перезахват отказал (состояние уже `error`).

        При запрошенном стопе команды не исполняются: их закроет `_close_box` ответом «сеанс остановлен».
        """
        while not stop_evt():
            with self._lock:
                if not box.cmds:
                    return True
                cmd = box.cmds.popleft()
                if cmd.cancelled:
                    continue  # вызывающий истёк по сроку: не исполняется и позже
                cmd.committed = True  # с этого момента `call` по сроку отменить команду не может
            self._execute(cmd)
            if self._regrab_failed:
                return False
        return True

    @staticmethod
    def _execute(cmd: _Cmd) -> None:
        """`fn` команды; исключение -> `error` команды, цикл продолжается."""
        try:
            cmd.result = cmd.fn()
        except Exception as exc:  # noqa: BLE001 — команда другого потока не роняет владельца
            cmd.error = describe_error(exc)
            logger.exception("session: команда ящика завершилась исключением")
        except BaseException:
            cmd.error = "команда прервана"
            raise
        finally:
            cmd.done.set()

    def _close_box(self, box: _Box) -> None:
        """Выход владельца: ящик закрывается под замком, оставшиеся команды получают «сеанс остановлен»."""
        with self._lock:
            box.closed = True
            left = list(box.cmds)
            box.cmds.clear()
            self._pending.clear()
            self._drain_queued = False
        for cmd in left:
            cmd.error = "сеанс остановлен"
            cmd.done.set()

    def _drain(self) -> None:
        """Команда `apply` (владелец): применить все накопленные правки.

        `live` при `live_write` — запись без остановки; остальное (`restart`, `live` без `live_write`) — ОДИН перезахват
        на пакет. Шаги пакета заменяют шаги тех же полей в плане `run` цикла: следующий перезахват их не откатывает.
        """
        with self._lock:
            batch = list(self._pending.values())
            self._pending.clear()
            self._drain_queued = False
        if not batch:
            return
        self._run = self._replace_in_run([step for step, _policy in batch])
        order = {step.field: i for i, step in enumerate(self._run)}  # родитель раньше потомка, как в плане
        live_write = "live_write" in self._port.capabilities
        live = [step for step, policy in batch if policy == "live" and live_write]
        regrab = [step for step, policy in batch if not (policy == "live" and live_write)]
        live.sort(key=lambda step: order[step.field])
        regrab.sort(key=lambda step: order[step.field])
        if live:
            t0 = time.perf_counter()
            self._runner.apply_plan(live)  # type: ignore[union-attr]
            self._log_apply(live, "live", t0)
        if regrab:
            self._regrab(regrab)

    def _replace_in_run(self, steps: Sequence[Step]) -> tuple[Step, ...]:
        """План `run` цикла, в котором шаги пакета заменили шаги тех же полей (новые поля — в конец)."""
        new = {step.field: step for step in steps}
        merged = [new.pop(step.field, step) for step in self._run]
        merged.extend(new.values())
        return tuple(merged)

    def _regrab(self, steps: Sequence[Step]) -> None:
        """Перезахват порта ВНУТРИ `grabbing` (`state`, `on_state` не меняются): `stop_grabbing`, запись, `start`.

        С `restart_regrab` пишутся шаги пакета в открытый порт; без неё — `close`, `open` и весь `run` цикла. Стоп
        запрошен до `start_grabbing` -> он не зовётся (порт закроет `_cleanup`). Отказ -> `_fail("error")`.
        """
        hold, stop = self._hold, self._stop_now
        t0 = time.perf_counter()
        try:
            if stop():
                return
            self._port_call("stop_grabbing", self._port.stop_grabbing)
            hold.grabbing = False
            if "restart_regrab" in self._port.capabilities:
                self._runner.apply_plan(steps)  # type: ignore[union-attr]
            else:
                self._port_call("close", self._port.close)
                hold.opened = False
                if stop():
                    return
                self._port_call("open", self._port.open, self._device)
                hold.opened = True
                if stop():
                    return
                self._runner.apply_plan(self._run)  # type: ignore[union-attr]
            if stop():
                return
            self._port_call("start_grabbing", self._port.start_grabbing)
            hold.grabbing = True
        except Exception as exc:  # noqa: BLE001 — любой отказ перезахвата: цикл завершается, `_cleanup` по `hold`
            self._regrab_failed = True
            self._fail("error", exc)
        else:
            self._log_apply(steps, "restart", t0)
        finally:
            self._timing("regrab", time.perf_counter() - t0)

    @staticmethod
    def _log_apply(steps: Sequence[Step], policy: str, t0: float) -> None:
        ms = int((time.perf_counter() - t0) * 1000)
        for step in steps:
            logger.info("apply field=%s policy=%s ms=%d", step.field, policy, ms)

    # ------------------------------------------------------------------ #
    # Сторож
    # ------------------------------------------------------------------ #

    def _start_watchdog(self) -> None:
        self._wd_stop = threading.Event()
        self._wd_started.clear()
        try:
            if self._workers.start_worker(self._wd_name):
                self._wd_started.wait(self._watchdog_s)
        except Exception:  # noqa: BLE001 — без сторожа захват работает, но зависание не будет замечено
            logger.exception("session: сторож не запущен")

    def _stop_watchdog(self) -> None:
        """Остановить сторожа и дождаться его выхода: иначе следующий `start_worker` вернёт `True` без потока."""
        self._wd_stop.set()
        thread = self._wd_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self._watchdog_s)

    def _watchdog_main(self, worker_stop: threading.Event, pause: threading.Event) -> None:
        """LOOP-воркер: один `on_stall(call, seconds)` на вызов порта, длящийся дольше `watchdog_s`; порт не зовёт."""
        self._wd_thread = threading.current_thread()
        stop = self._wd_stop
        self._wd_started.set()
        tick = min(0.05, self._watchdog_s / 4)
        while not (worker_stop.is_set() or stop.wait(tick)):
            call = self._current
            if call is None or call.reported:
                continue
            elapsed = time.perf_counter() - call.t0
            if elapsed >= self._watchdog_s:
                call.reported = True
                self._notify(self._on_stall, call.name, elapsed)


def _failed_state(exc: PortError, *, opening: bool) -> str:
    """`busy`/`not_found` — только отказ на открытии; прочие `PortError` — `error`."""
    if opening and exc.kind in ("busy", "not_found"):
        return exc.kind
    return "error"
