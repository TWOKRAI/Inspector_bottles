# -*- coding: utf-8 -*-
"""Сеанс прибора `DeviceSession` (Task 2.1): поток-владелец, жизненный цикл, ошибки кадра, сторож.

Все вызовы порта и `DeviceSdk` (`acquire`, `enum_devices`, `open`, `start_grabbing`, `get_frame`,
`stop_grabbing`, `close`, `release`) идут ТОЛЬКО из потока-владельца: один владелец на цикл
`open -> close`, новый `start()` после остановки — новый поток. Потоки владельца и сторожа — `daemon`.

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

Слой: только stdlib и `.interface`/`.params`; без `multiprocess_prototype` и вендоров.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence

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
        on_stall: Callable[[str, float], None] | None = None,
        on_state: Callable[[str, str], None] | None = None,
        on_timing: Callable[[str, float], None] | None = None,
        run: Sequence[Step] = (),
        rest: Sequence[Step] = (),
    ) -> None:
        if watchdog_s <= timeout_ms / 1000.0:
            raise ValueError("watchdog_s должен быть больше timeout_ms/1000")
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
        self._current: _Call | None = None
        self._cycle_t0 = 0.0
        self._errors = 0
        self._last_error: str | None = None
        self._device: DeviceIdentity | None = None
        self._profile = ProfileState()  # профили run/rest (Task 2.2); замок и данные принадлежат сеансу
        self._runner: ProfileRunner | None = None

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

    def start(self, timeout: float = 5.0) -> bool:
        """Начать захват: `True` — захват идёт.

        Из `stopping`, из потока владельца и при живом владельце — `False` сразу, без очереди.
        """
        if threading.current_thread() is self._owner:
            return False
        pending: list[tuple[str, str]] = []
        creator = False
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
                self._held = True
                self._cycle_t0 = time.monotonic()
                self._set_locked("opening", pending)
                self._owner = threading.Thread(
                    target=self._owner_main, args=(cmd, self._stop_evt), name="camera_device-owner", daemon=True
                )
                self._owner.start()
        self._fire_states(pending)
        assert cmd is not None
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
            owner = self._owner
            if state in _FAILED:
                self._set_locked("closed", pending)  # порт не зовётся: владелец уже закрывает его сам
            else:
                self._set_locked("stopping", pending)
                self._stop_evt.set()
        self._fire_states(pending)
        if owner is None or threading.current_thread() is owner:
            return  # из on_frame: самосоединения нет, владелец сам завершит цикл
        owner.join(timeout + self._timeout_ms / 1000.0)

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

    def _commit(self, cmd: _StartCmd, stop_evt: threading.Event) -> bool:
        """Решение «откат или фиксация» под замком: кто первый — тот решил."""
        with self._lock:
            if cmd.cancelled or stop_evt.is_set():
                return False
            cmd.committed = True
            return True

    def _enter_grabbing(self, cmd: _StartCmd, stop_evt: threading.Event) -> bool:
        """После `start_grabbing` под замком: отмена/стоп -> откат (`False`), иначе `grabbing` и итог `True`.

        Ответ `start()` всегда равен реальному состоянию: `True` только если цикл остался `grabbing`.
        """
        pending: list[tuple[str, str]] = []
        with self._lock:
            abort = cmd.cancelled or stop_evt.is_set()
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

    def _owner_main(self, cmd: _StartCmd, stop_evt: threading.Event) -> None:
        watchdog_stop = threading.Event()
        threading.Thread(
            target=self._watchdog, args=(watchdog_stop,), name="camera_device-watchdog", daemon=True
        ).start()
        acquired = opened = grabbing = run_applied = failed = False
        self._profile.reset()  # начало run каждого start(): params / params_status / param_errors заново
        try:
            self._port_call("acquire", self._sdk.acquire)
            acquired = True
            ident = self._resolve_ident()
            self._port_call("open", self._port.open, ident)
            opened = True
            self._device = ident
            self._runner = ProfileRunner(self._port, ident, self._profile, logger, self._timing)
            self._apply_run()
            run_applied = True
            if self._commit(cmd, stop_evt):
                self._port_call("start_grabbing", self._port.start_grabbing)
                grabbing = True
                if self._enter_grabbing(cmd, stop_evt):
                    failed = not self._grab_loop(stop_evt)
        except PortError as exc:
            failed = True
            self._fail(_failed_state(exc, opening=not opened), exc)
        except Exception as exc:  # noqa: BLE001 — любой отказ владельца -> error, порт закрывается ниже
            failed = True
            self._fail("error", exc)
        finally:
            cmd.finish(False)  # no-op, если итог уже `True`
            self._cleanup(grabbing, run_applied and not failed, opened, acquired)
            watchdog_stop.set()
            with self._lock:
                pending: list[tuple[str, str]] = []
                if self._state not in _FAILED:
                    self._set_locked("closed", pending)
                self._held = False  # снимается вместе с финальным состоянием
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

    def _grab_loop(self, stop_evt: threading.Event) -> bool:
        """Читать кадры до `stop_evt`; `False` — три ошибки подряд (состояние уже `error`)."""
        consecutive = 0
        while not stop_evt.is_set():
            try:
                raw = self._port_call("get_frame", self._port.get_frame, self._timeout_ms)
            except PortError as exc:
                self._errors += 1
                consecutive += 1
                self._last_error = describe_error(exc)
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    self._fail("error", exc)
                    return False
                continue
            consecutive = 0  # кадр и таймаут (None) — не ошибки
            if raw is None:
                continue
            try:
                self._on_frame(raw)
            except Exception:  # noqa: BLE001 — исключение колбэка не ошибка порта, захват не останавливается
                logger.exception("session: on_frame завершился исключением")
        return True

    # ------------------------------------------------------------------ #
    # Сторож
    # ------------------------------------------------------------------ #

    def _watchdog(self, stop: threading.Event) -> None:
        """Один `on_stall(call, seconds)` на вызов порта, длящийся дольше `watchdog_s`; порт не зовёт."""
        tick = min(0.05, self._watchdog_s / 4)
        while not stop.wait(tick):
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
