# -*- coding: utf-8 -*-
"""Сеанс прибора `DeviceSession` (Task 2.1): поток-владелец, жизненный цикл, ошибки кадра, сторож.

Все вызовы порта и `DeviceSdk` (`acquire`, `enum_devices`, `open`, `start_grabbing`, `get_frame`,
`stop_grabbing`, `close`, `release`) идут ТОЛЬКО из потока-владельца: один владелец на цикл
`open -> close`, новый `start()` после остановки — новый поток. Потоки владельца и сторожа — воркеры `WorkerManager`
процесса (параметр `workers`; `worker_prefix` уникален на сеанс в менеджере).

Состояния: `idle` (до первого `start`), `opening`, `grabbing`, `stopping`, `closed` (покой после остановки),
`busy`, `not_found`, `error` (отказ), `lost` (связь с прибором потеряна, идёт переподключение; только при
`reconnect=True`). Без `reconnect` автопереподключения нет (ADR-CR-009); с ним (W2-a) поток-владелец сам повторяет
`open -> start_grabbing` каждые `reconnect_interval_s`, пока не будет стопа. Потеря связи: событие прибора
`disconnected` (`LinkEventSource`) или тишина `link_silence_s` (свободный поток — сразу, триггер — по пробе узла).
Переходы — только compare-and-set под замком состояния; `on_state`, `on_stall`, `on_timing` зовутся вне замка.
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
from typing import Any, Literal

from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig, WorkerType

from .interface import DeviceIdentity, DevicePort, DeviceSdk, LinkEventSource, PortError, RawFrame
from .params import Step
from .profiles import ProfileRunner, ProfileState

logger = logging.getLogger("camera_device.session")

# Подряд идущих ошибок `get_frame` до перехода в `error`.
MAX_CONSECUTIVE_ERRORS = 3
# Виды `PortError` пробы при тишине, означающие «прибора нет»; прочие (`access`, `range`, `other`) — прибор ответил.
_LINK_DEAD_KINDS = frozenset({"network", "closed", "timeout", "not_found", "busy"})
# Дроссель WARNING неудачных повторов, с.
_RETRY_WARN_S = 60.0
# Срез ожидания между попытками, с: стоп процесса (4,0 с) не ждёт паузу целиком.
_BACKOFF_SLICE_S = 0.1
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
        self.run_applied = False  # план `run` попытки записан: только тогда `rest` при выходе
        self.up = False  # попытка дошла до `grabbing`: отказ после этого — потеря связи, а не неудачный повтор


class _Outage:
    """Учёт одного отказа в цикле попыток (пишет и читает только владелец)."""

    def __init__(self, ever_grabbed: bool) -> None:
        self.ever_grabbed = ever_grabbed  # прибор уже брался в этом цикле: отказ — потеря связи (`lost`)
        self.t0 = time.monotonic()
        self.tries = 0  # повторы этого отказа (для строк лога; `attempts` в `link()` — за весь цикл)
        self.next_warn = self.t0 + _RETRY_WARN_S  # первая строка «прибора нет» — не раньше 60 с от начала отказа
        self.stack_logged = False  # первое не-`PortError` исключение уже записано со стеком


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
        reconnect: bool = False,
        link_silence_s: float = 0.0,
        reconnect_interval_s: float = 2.0,
        on_link: Callable[[], None] | None = None,
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
        # Связь и переподключение (W2-a): параметры читаются один раз здесь.
        self._reconnect = bool(reconnect)
        self._link_silence_s = float(link_silence_s)  # 0 — правило тишины выключено
        self._reconnect_interval_s = float(reconnect_interval_s)
        # `_reconnecting` пишется под `self._lock` (вместе с состоянием), читается голым (`reconnecting`, `apply`).
        self._reconnecting = False
        # Голые атрибуты для `link()`; пишет владелец (и `start()` под замком при новом цикле).
        self._link = "off"  # up | idle | silent | lost | off
        self._outages = 0
        self._attempts = 0
        self._last_outage_s: float | None = None
        self._lost_since: float | None = None
        # Только владелец: учёт отказа, «правка ящиком исполнена», «повтор ждёт первого кадра», план попытки.
        self._outage: _Outage | None = None
        # `on_link()` (владелец, вне замка): при переподключении сменился `attempts` или целая секунда `lost_for_s`.
        # Подписчик не ждёт своего окна (у источника в паузе или при `run fault` `produce()` не зовётся).
        self._on_link = on_link
        self._link_key: tuple[int, int | None] | None = None
        self._box_ran = False
        self._awaiting_frame = False
        self._attempt_run: tuple[Step, ...] = ()

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

    @property
    def reconnecting(self) -> bool:
        """Цикл попыток ждёт прибор (`lost` или отказ первой попытки при `reconnect`); голый атрибут, без замка."""
        return self._reconnecting

    def link(self) -> dict:
        """Связь с прибором (голые атрибуты, без замка, как `state`); только скаляры (Dict at Boundary).

        `state`: `up` (кадры идут), `idle` (тишина, проба ответила), `silent` (тишина, пробовать нечем — план пуст),
        `lost`, `off` (выводится из состояния `idle`/`stopping`/`closed`, не хранится). `lost_for_s` — целые секунды
        с потери при переподключении после потери, иначе `None` (целое: state не сливается на каждом такте).
        """
        state = self._state
        reconnecting = self._reconnecting
        lost_since = self._lost_since
        lost_for = int(time.monotonic() - lost_since) if reconnecting and lost_since is not None else None
        return {
            "state": "off" if state in ("idle", "stopping", "closed") else self._link,
            "reconnecting": reconnecting,
            "outages": self._outages,
            "attempts": self._attempts,
            "last_outage_s": self._last_outage_s,
            "lost_for_s": lost_for,
        }

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
            elif self._held:  # busy/not_found/error/lost/closed при живом владельце: цикл ещё идёт или закрывается
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
                # счётчики связи — на цикл `start -> stop` (W2-a)
                self._outages = self._attempts = 0
                self._last_outage_s = self._lost_since = None
                self._link = "off"
                self._reconnecting = False
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
                cmd.cancelled = True  # владелец откатит цикл после open / _apply_run; повторов не будет
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
        """Остановить захват; не отбрасывается. `timeout` — только срок ожидания вызывающего.

        Из отказа (`busy`/`not_found`/`error`) — сразу `closed` и событие стопа цикла: владелец либо уже закрывает
        порт, либо (`reconnect`) ждёт повтора и выходит. Из `lost` — прежней веткой `stopping`.
        """
        pending: list[tuple[str, str]] = []
        with self._lock:
            state = self._state
            if state in ("idle", "closed", "stopping"):
                return
            exited = self._exited
            if state in _FAILED:
                self._set_locked("closed", pending)  # порт не зовётся: владелец закрывает его сам
                self._stop_evt.set()  # иначе цикл попыток (W2-a) продолжил бы повторы после стопа
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
        `grabbing`, до первого `get_frame`) и в `grabbing`. При переподключении (`reconnecting`) правка входит в план
        открытия (`run`) следующей попытки, ящик не трогается. В `stopping`/`closed`/отказе или при закрытом ящике
        правка не принимается: значение register'а попадёт в прибор планом `run` следующего цикла.
        """
        if policy not in ("live", "restart"):
            raise ValueError("policy должна быть live или restart")
        if not steps:
            return
        with self._lock:
            merged = self._reconnecting
            if merged:  # `_replace_in_run` — чистая функция от `self._run` и шагов: под замком из любого потока
                self._run = self._replace_in_run(steps)
                accepted = True
            else:
                accepted = self._state in ("opening", "grabbing") and not self._box.closed
            if accepted and not merged:
                for step in steps:
                    self._pending[step.field] = (step, policy)
                if not self._drain_queued:
                    self._drain_queued = True
                    self._box.cmds.append(_Cmd(self._drain))
        if merged:
            logger.info("apply policy=%s: переподключение, правка войдёт в план открытия", policy)
        elif not accepted:
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

    def _set_loop_state(self, new: str, then: Callable[[], None] | None = None) -> bool:
        """Запись состояния из цикла попыток (W2-a); `False` — стоп запрошен или `closed`/`stopping`, ничего не тронуто.

        `then` исполняется под тем же захватом `self._lock`, что и запись (флаг `_reconnecting`, слияние правок в
        план); `on_state` — вне замка.
        """
        pending: list[tuple[str, str]] = []
        with self._lock:
            if self._stop_now() or self._state in ("closed", "stopping"):
                return False
            self._set_locked(new, pending)
            if then is not None:
                then()
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

    def _apply_run(self, run: Sequence[Step]) -> None:
        """Профиль `run` между `open` и `start_grabbing` (владелец); `run` — снимок плана, взятый под замком."""
        self._runner.apply_plan(run)  # type: ignore[union-attr]

    def _apply_rest(self, grabbing: bool) -> bool:
        """Профиль `rest` после `stop_grabbing` до `close`; `False` — `open` ветки reopen упал, `close` не зовётся."""
        if not self._rest:
            return True
        direct = "restart_regrab" in self._port.capabilities or not grabbing  # H1: NETER снимает только close
        return self._runner.run_rest(self._rest, direct)  # type: ignore[union-attr]

    def _owner_main(self, worker_stop: threading.Event, pause: threading.Event) -> None:
        """TASK-воркер на цикл `start -> stop`: поток-владелец порта. Стоп процесса (`worker_stop`) = стоп цикла.

        Без `reconnect` — одна попытка (прежнее поведение). С ним — цикл попыток в ЭТОМ потоке: ящик команд и сторож
        общие на весь цикл, каждая попытка с нуля (`_Hold`, профиль, `ProfileRunner`); между попытками — уборка порта
        без `rest` и пауза `reconnect_interval_s` срезами 0,1 с.
        """
        self._owner = threading.current_thread()
        with self._lock:
            cmd, cycle_stop, exited, box = self._cmd, self._stop_evt, self._exited, self._box
        assert cmd is not None
        stop_evt = lambda: cycle_stop.is_set() or worker_stop.is_set()  # noqa: E731
        self._stop_now = stop_evt
        self._start_watchdog()
        self._outage = None
        first = True
        ever_grabbed = False
        failed = False
        try:
            while True:
                hold = self._hold = _Hold()
                self._regrab_failed = False
                self._awaiting_frame = False
                self._profile.reset()  # начало run каждой попытки: params / params_status / param_errors заново
                failed = False
                error: Exception | None = None
                try:
                    outcome = self._attempt(cmd if first else None, stop_evt, box, ever_grabbed)
                except Exception as exc:  # noqa: BLE001 — любой отказ попытки: решение ниже, порт закрывается уборкой
                    outcome, error = "failed", exc
                if outcome == "stopped":
                    break
                failed = True
                if not self._reconnect or (first and cmd.cancelled):
                    self._end_without_reconnect(outcome, error, hold)  # прежнее поведение: повторов нет
                    break
                if first and not hold.up:  # (а) отказ первой попытки: прибор ещё не брался
                    state = self._refusal_state(error, hold)
                    self._fail(state, error or RuntimeError(outcome))
                    self._outage = _Outage(ever_grabbed=False)
                    entered = self._set_loop_state(state, then=self._enter_reconnect_locked)
                    cmd.finish(False)  # после `_reconnecting = True`: вызывающий `start()` видит `reconnecting`
                    if not entered:
                        break
                elif hold.up:  # (б) потеря связи из `grabbing`
                    ever_grabbed = True
                    if not self._lost_from_grabbing(error):
                        break
                elif not self._retry_failed(error, hold, ever_grabbed):  # (в) неудачный повтор
                    break
                # (г) уборка без `rest`, пауза, следующая попытка
                self._cleanup(hold.grabbing, False, hold.opened, hold.acquired)
                self._hold = _Hold()  # порт убран: финальная уборка его не тронет
                failed = False
                if not self._backoff(cycle_stop, stop_evt):
                    break
                self._attempts += 1
                if self._outage is not None:
                    self._outage.tries += 1
                self._link_tick()
                first = False
        finally:
            self._reconnecting = False
            cmd.finish(False)  # no-op, если итог уже `True`
            self._close_box(box)  # до закрытия порта: оставшиеся команды получают ответ раньше, чем вернётся `stop()`
            hold = self._hold
            # `rest` — только на открытом порту: стоп в окне перезахвата мог оставить порт закрытым
            self._cleanup(hold.grabbing, hold.run_applied and not failed and hold.opened, hold.opened, hold.acquired)
            self._stop_watchdog()
            with self._lock:
                pending: list[tuple[str, str]] = []
                self._reconnecting = False
                if self._state not in _FAILED:
                    self._set_locked("closed", pending)
                self._held = False  # снимается вместе с финальным состоянием
                exited.set()
            self._fire_states(pending)

    def _attempt(self, cmd: _StartCmd | None, stop_evt: Callable[[], bool], box: _Box, ever_grabbed: bool) -> str:
        """Одна попытка: `acquire -> open -> run -> start_grabbing -> захват`; исход `_grab_loop` или `stopped`.

        `cmd` — только у первой попытки: она ведёт ответ `start()` как раньше (`_commit`, `_enter_grabbing`, без
        промежуточных проверок стопа — их роль играет `_commit`). Повтор (`cmd is None`) проверяет стоп после
        `acquire`, `open` и записи `run`. Исключение порта летит в `_owner_main`.
        """
        hold = self._hold
        retry = cmd is None
        self._port_call("acquire", self._sdk.acquire)
        hold.acquired = True
        if retry and stop_evt():
            return "stopped"
        ident = self._resolve_ident()
        self._port_call("open", self._port.open, ident)
        hold.opened = True
        self._device = ident
        self._runner = ProfileRunner(self._port, ident, self._profile, logger, self._timing, self._port_call)
        if retry and stop_evt():
            return "stopped"
        with self._lock:  # `apply` при переподключении меняет план из другого потока под этим замком
            run = self._attempt_run = self._run
        self._apply_run(run)
        hold.run_applied = True
        if retry and stop_evt():
            return "stopped"
        self._discard_link_events()
        if cmd is not None:
            if not self._commit(cmd, stop_evt):
                return "stopped"
            self._port_call("start_grabbing", self._port.start_grabbing)
            hold.grabbing = True
            self._link = "up"  # до `on_state(grabbing)`: подписчик сразу видит связь
            if not self._enter_grabbing(cmd, stop_evt):
                return "stopped"
            hold.up = True
        else:
            self._port_call("start_grabbing", self._port.start_grabbing)
            hold.grabbing = True
            if not self._resume(ever_grabbed):
                return "stopped"
        return self._grab_loop(stop_evt, box)

    def _resume(self, ever_grabbed: bool) -> bool:
        """После `start_grabbing` повтора: состояние и правки, принятые после снимка плана; `False` — стоп.

        Свободный поток после потери остаётся `lost` (и `reconnecting`) до ПЕРВОГО кадра (`_grab_loop`); аппаратный
        триггер, режим не задан или прибор ещё не брался — сразу `grabbing`.
        """
        mode = self._trigger_mode()
        if ever_grabbed and mode is not None and mode != "On":
            self._awaiting_frame = True
            return self._set_loop_state("lost", then=self._queue_run_diff_locked)
        if not self._set_loop_state("grabbing", then=self._back_up_locked):
            return False
        self._recovered()
        return True

    def _end_without_reconnect(self, outcome: str, error: Exception | None, hold: _Hold) -> None:
        """Конец цикла без повторов (прежнее поведение): исключение -> `_fail`, потеря связи -> `error`."""
        if error is not None:
            self._fail(self._refusal_state(error, hold), error)
        elif outcome == "lost":
            # тишина/событие прибора без `reconnect`: иначе рецепт с `trigger_managed true` + `Off` молча держал бы
            # мёртвый поток (решение лида по ревью)
            logger.error("session: связь с прибором потеряна (%s); переподключение выключено", self._last_error)
            self._link = "lost"
            self._cas(("grabbing",), "error")

    def _lost_from_grabbing(self, error: Exception | None) -> bool:
        """(б) Потеря связи из `grabbing`: учёт, одна WARNING, `lost` + `reconnecting`; `False` — стоп."""
        if error is not None:
            self._last_error = describe_error(error)
        self._link = "lost"
        self._outages += 1
        self._lost_since = time.monotonic()
        self._outage = _Outage(ever_grabbed=True)
        logger.warning(
            "session: связь с прибором потеряна (%s); переподключение каждые %s с",
            self._last_error,
            f"{self._reconnect_interval_s:g}",
        )
        return self._set_loop_state("lost", then=self._enter_reconnect_locked)

    def _retry_failed(self, error: Exception | None, hold: _Hold, ever_grabbed: bool) -> bool:
        """(в) Неудачный повтор: `_fail` не зовётся, `opening` не ставится, WARNING — дросселем 60 с; `False` — стоп.

        Тишина без первого кадра (исход `lost` без исключения) — тоже неудачный повтор: причина уже в `last_error`.
        """
        outage = self._outage
        if outage is None:  # не бывает: повтору всегда предшествует (а) или (б); учёт заводится на месте
            outage = self._outage = _Outage(ever_grabbed=ever_grabbed)
        if error is not None:
            self._last_error = describe_error(error)
        now = time.monotonic()
        if error is not None and not isinstance(error, PortError) and not outage.stack_logged:
            outage.stack_logged = True  # первое не-`PortError` (например `OSError` из ctypes) — со стеком
            logger.error("session: повтор открытия: исключение %s", self._last_error, exc_info=error)
        elif now >= outage.next_warn:
            outage.next_warn = now + _RETRY_WARN_S
            logger.warning("session: прибора нет %.0f с, попыток %d", now - outage.t0, outage.tries)
        state = "lost" if ever_grabbed else self._refusal_state(error, hold)
        return self._set_loop_state(state)

    def _backoff(self, cycle_stop: threading.Event, stop_evt: Callable[[], bool]) -> bool:
        """Пауза `reconnect_interval_s` срезами `cycle_stop.wait(0.1)`; `False` — стоп во время паузы."""
        end = time.monotonic() + self._reconnect_interval_s
        while not stop_evt():
            self._link_tick()
            left = end - time.monotonic()
            if left <= 0:
                return True
            cycle_stop.wait(min(_BACKOFF_SLICE_S, left))
        return False

    def _link_tick(self) -> None:
        """Владелец при переподключении: `on_link()`, если сменился `attempts` или целая секунда `lost_for_s`."""
        if self._on_link is None:
            return
        since = self._lost_since
        key = (self._attempts, None if since is None else int(time.monotonic() - since))
        if key != self._link_key:
            self._link_key = key
            self._notify(self._on_link)

    @staticmethod
    def _refusal_state(error: Exception | None, hold: _Hold) -> str:
        """Состояние отказа попытки: `busy`/`not_found` только на открытии; не-`PortError` и прочее — `error`."""
        if isinstance(error, PortError):
            return _failed_state(error, opening=not hold.opened)
        return "error"

    def _enter_reconnect_locked(self) -> None:
        """Под `self._lock`: вход в переподключение; правки, не дошедшие до `_drain`, сливаются в план открытия.

        Поставленный `_drain` найдёт пустой пакет и выйдет.
        """
        self._reconnecting = True
        if self._pending:
            self._run = self._replace_in_run([step for step, _policy in self._pending.values()])
            self._pending.clear()

    def _queue_run_diff_locked(self) -> None:
        """Под `self._lock`: шаги плана, изменённые после снимка попытки (`apply` при переподключении), — в `_drain`.

        Ящик исполнит их до следующего `get_frame` (перезахватом: политика правки при слиянии в план не хранится).
        """
        applied = self._attempt_run
        if self._run is applied:
            return
        before = {step.field: step for step in applied}
        changed = [step for step in self._run if before.get(step.field) != step]
        self._attempt_run = self._run
        if not changed:
            return
        for step in changed:
            self._pending[step.field] = (step, "restart")
        if not self._drain_queued:
            self._drain_queued = True
            self._box.cmds.append(_Cmd(self._drain))

    def _back_up_locked(self) -> None:
        """Под `self._lock`: возврат в `grabbing` после отказа — правки после снимка в `_drain`, связь `up`."""
        self._queue_run_diff_locked()
        self._reconnecting = False
        self._link = "up"
        self._last_error = None
        outage = self._outage
        if outage is not None and outage.ever_grabbed:
            self._last_outage_s = round(time.monotonic() - outage.t0, 1)

    def _recovered(self) -> None:
        """Попытка дошла до `grabbing` (владелец, вне замка): INFO о возврате, учёт отказа закрыт."""
        self._hold.up = True
        outage, self._outage = self._outage, None
        if outage is None:
            return
        if outage.ever_grabbed:
            logger.info(
                "session: связь восстановлена за %.1f с, попыток %d", time.monotonic() - outage.t0, outage.tries
            )
        else:
            logger.info("session: прибор взят, попыток %d", outage.tries)

    def _trigger_mode(self) -> Any:
        """Значение шага `trigger_mode` в плане `run` (`None` — шага нет или он пропущен: режим не задан)."""
        step = next((s for s in self._run if s.field == "trigger_mode"), None)
        return None if step is None or step.skip is not None else step.value

    def _discard_link_events(self) -> None:
        """Перед `start_grabbing`: события связи прошлого сеанса прибора устарели — вычитать и отбросить."""
        if isinstance(self._port, LinkEventSource):
            stale = self._port.drain_link_events()
            logger.debug("session: отброшено событий прибора до start_grabbing: %d", len(stale))

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

    def _grab_loop(self, stop_evt: Callable[[], bool], box: _Box) -> Literal["stopped", "failed", "lost"]:
        """Читать кадры до `stop_evt`. `failed` — три ошибки подряд или отказ перезахвата; `lost` — потеря связи.

        Без `reconnect` при `failed` состояние уже `error` (`_fail`); с ним `_fail` не зовётся (решает цикл попыток).
        Исход `lost` всегда пишет причину в `last_error`. После КАЖДОГО возврата `get_frame` (кадр, `None`,
        `PortError`): событие прибора `disconnected`, затем правило тишины `link_silence_s`, затем ящик команд.
        """
        if not self._poll_box(box, stop_evt):  # правки, принятые в `opening`: до первого `get_frame`
            return "failed"
        events = isinstance(self._port, LinkEventSource)
        consecutive = 0
        last_frame = last_probe = time.monotonic()
        while not stop_evt():
            raw = None
            try:
                raw = self._port_call("get_frame", self._port.get_frame, self._timeout_ms)
            except PortError as exc:
                self._errors += 1
                consecutive += 1
                self._last_error = describe_error(exc)
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    if not self._reconnect:
                        self._fail("error", exc)
                    return "failed"
            else:
                consecutive = 0  # кадр и таймаут (None) — не ошибки
            now = time.monotonic()
            if self._awaiting_frame and raw is None:
                self._link_tick()  # повтор ждёт первого кадра (`lost`): `lost_for_s` идёт и здесь
            if raw is not None:
                last_frame = now
                if self._awaiting_frame:  # свободный поток после потери: связь вернулась с первым кадром
                    self._awaiting_frame = False
                    if not self._set_loop_state("grabbing", then=self._back_up_locked):
                        return "stopped"
                    self._recovered()
                self._link = "up"
            reason = None
            if events and "disconnected" in self._port.drain_link_events():  # type: ignore[attr-defined]
                reason = "событие прибора disconnected"
            elif self._link_silence_s > 0 and now - last_frame >= self._link_silence_s:
                reason, last_probe = self._silence(now, now - last_frame, last_probe)
            if reason is None:
                self._box_ran = False
                if not self._poll_box(box, stop_evt):
                    return "failed"
                if self._box_ran:  # перезахват по живой правке — не тишина
                    last_frame = last_probe = time.monotonic()
            if raw is not None:
                try:
                    self._on_frame(raw)
                except Exception:  # noqa: BLE001 — исключение колбэка не ошибка порта, захват не останавливается
                    logger.exception("session: on_frame завершился исключением")
            if reason is not None:
                self._last_error = reason
                return "lost"
        return "stopped"

    def _silence(self, now: float, silent_s: float, last_probe: float) -> tuple[str | None, float]:
        """Правило тишины: причина потери (`None` — связь есть) и новый `last_probe`.

        Свободный поток (`trigger_mode` задан и не `On`) — потеря сразу, проба не спрашивается (на стенде прибор
        отвечал при мёртвом потоке). `On` или режим не задан — проба узла `run[0]` раз в `link_silence_s`.
        """
        mode = self._trigger_mode()
        if mode is not None and mode != "On":
            return f"тишина {silent_s:.1f} с при trigger_mode={mode}", last_probe
        if now - last_probe < self._link_silence_s:
            return None, last_probe
        run = self._run
        if not run:
            self._link = "silent"  # пробовать нечем
            return None, now
        try:
            self._port_call("probe", self._port.get_param, run[0].binding)
        except PortError as exc:
            if exc.kind in _LINK_DEAD_KINDS:
                return f"тишина {silent_s:.1f} с, проба: {describe_error(exc)}", now
        self._link = "idle"  # прибор ответил (значением или отказом узла): поток просто ждёт триггера
        return None, now

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
            if cmd.fn == self._drain:  # живая правка (запись или перезахват) исполнена: окно тишины заново
                self._box_ran = True
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
        with self._lock:  # план меняет и `apply` при переподключении (другой поток): присваивание — под замком
            batch = list(self._pending.values())
            self._pending.clear()
            self._drain_queued = False
            if batch:
                self._run = self._replace_in_run([step for step, _policy in batch])
            run = self._run
        if not batch:
            return
        order = {step.field: i for i, step in enumerate(run)}  # родитель раньше потомка, как в плане
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
        запрошен до `start_grabbing` -> он не зовётся (порт закроет `_cleanup`). Отказ -> `_fail("error")`; с
        `reconnect` — только `last_error`: потерю решает цикл попыток (как три ошибки кадра подряд).
        События связи до `start_grabbing` отбрасываются (как в каждой попытке).
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
            self._discard_link_events()
            self._port_call("start_grabbing", self._port.start_grabbing)
            hold.grabbing = True
        except Exception as exc:  # noqa: BLE001 — любой отказ перезахвата: цикл завершается, `_cleanup` по `hold`
            self._regrab_failed = True
            if self._reconnect:
                self._last_error = describe_error(exc)
            else:
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
