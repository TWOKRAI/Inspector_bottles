"""``robot_driver_v2.park`` (T5.3e): автомат основной остановки робота v2 в тике драйвера.

Purpose:
    ``ParkMachine`` ведёт принятый ``robot_park``: конец текущей команды или цикла -> простой -> домой -> серво OFF.
    Единственный писатель ``devices.state.<id>.park``; терминал (``done`` / ``failed``) — сравнением по ``seq``
    (``RobotState.park_end``). Шаги идут в тике драйвера (``guard`` — первой строкой, ``step`` — после TLM), без
    циклов ожидания и ``sleep``: шаг идёт до первого ожидания и выходит. Своих потоков нет.

Public API:
    ``ParkMachine`` (конструктор с колбэками; ``accept``, ``guard``, ``step``, ``abort``, ``fail``).

Pre/post:
    ``accept`` — после ``RobotState.park_begin`` и пометок release / SOFT; ``abort`` из ``request_stop`` —
    после записи стопа (при выключении итог ставит только он). Порядок замков: ``_mlock`` -> замок состояния;
    ``launch_home``, ``servo_off``, ``heartbeat`` — вне ``_mlock``; после их возврата — сверка ``_active`` / ``seq`` /
    выключения. Публикация — под ``_mlock`` (fire-and-forget IPC).

Stability: lite
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from Services.device_hub.drivers.base import logger
from Services.device_hub.drivers.robot_driver_v2.state import ParkView, RobotState
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_DISCONNECTING,
    TEXT_PARK_DROPPED,
    TEXT_PARK_HOME_ABORTED,
    TEXT_PARK_HOME_FAILED,
    TEXT_PARK_LINK,
    TEXT_PARK_NOT_HOME,
    TEXT_PARK_TIMEOUT,
    _HOME_TOL_DEG,
    _HOME_TOL_MM,
    _PARK_RETRY,
)
from Services.robot_comm.programs import Point

__all__ = ["ParkMachine"]

# Выключение процесса: автомат замирает — итог ставит только abort(stop=True) из request_stop после записи стопа
_FREEZE = object()


class ParkMachine:
    """Автомат основной остановки одного робота v2 (T5.3e, В2). Драйвер не импортирует: всё через колбэки."""

    def __init__(
        self,
        *,
        state: RobotState,
        clock: Callable[[], float],
        publish: Callable[[dict], None],
        home_point: Callable[[], Point],
        launch_home: Callable[[int], dict],
        servo_off: Callable[[], bool],
        heartbeat: Callable[[], None],
        record_err: Callable[[], None],
        log_id: str,
    ) -> None:
        self._state = state
        self._clock = clock
        self._publish = publish
        self._home_point = home_point
        self._launch_home = launch_home
        self._servo_off = servo_off
        self._heartbeat = heartbeat
        self._record_err = record_err
        self._log_id = log_id
        # Не _lock: имя совпало бы со швом журнала обмена в сторожах тестов (Opus M7)
        self._mlock = threading.Lock()
        self._active = False
        self._seq = 0
        self._t0: float | None = None
        self._deadline: float | None = None
        self._step: str | None = None
        self._launched = False
        self._home: str | None = None
        self._last_pub: str | None = None
        self._home_grace = False  # одна проверка позы отложена на тик (TLM мог быть прочитан до DONE)

    # ------------------------------------------------------------------ #
    # Вход и выход
    # ------------------------------------------------------------------ #

    def accept(self, seq: int, timeout_s: float) -> None:
        """Принять park ``seq`` (последний шаг ``_op_park``): сброс полей, публикация ``parking`` / ``activity``.

        park уже закрыт (``abort`` / ``fail`` успели) — выход без записи.
        """
        with self._mlock:
            v = self._state.park_view()
            if not (v.parking and v.seq == seq):
                return
            self._active = True
            self._seq = seq
            self._t0 = self._clock()
            self._deadline = self._t0 + timeout_s
            self._step = "activity"
            self._launched = False
            self._home = None
            self._last_pub = None
            self._home_grace = False
            self._publish_parking_locked()

    def fail(self, seq: int, reason: str) -> None:
        """``_op_park`` упал до ``accept``: терминал ``failed`` этого ``seq``."""
        with self._mlock:
            self._finish_locked(seq, False, reason)

    def abort(self, reason: str, *, stop: bool = False) -> None:
        """Закрыть идущий park (``request_stop`` — ``stop=True``, ``disconnect``). Закрывает и не принятый автоматом.

        При выключении итог ставит только ``request_stop`` (``stop=True``): прочие вызовы — без записи.
        """
        v = self._state.park_view()
        if v.shutdown and not stop:
            return
        if v.parking:
            with self._mlock:
                self._finish_locked(v.seq, False, reason)

    # ------------------------------------------------------------------ #
    # Тик
    # ------------------------------------------------------------------ #

    def guard(self, connected: bool) -> None:
        """Первая строка тика: причины закрыть park (выключение — замереть). Не бросает."""
        seq: int | None = None
        try:
            with self._mlock:
                v = self._live_view_locked()
                if v is None:
                    return
                seq = self._seq
                reason = self._reason(v, connected)
                if reason is _FREEZE or reason is None:
                    return
                self._finish_locked(seq, False, reason)
        except Exception as exc:
            self._on_error(seq, exc)

    def step(self, telemetry: Mapping[str, Any], free: bool) -> None:
        """Шаги park после TLM и ``poll_errors``, до ``_dispatch``: до первого ожидания. Не бросает."""
        seq: int | None = None
        try:
            while True:
                with self._mlock:
                    v = self._live_view_locked()
                    if v is None:
                        return
                    seq = self._seq
                    reason = self._reason(v, True)
                    if reason is _FREEZE:
                        return
                    if reason is not None:
                        self._finish_locked(seq, False, reason)
                        return
                    call = self._advance_locked(v, telemetry, free)
                if call is None:
                    return  # ждать следующего тика или терминал уже поставлен
                if call == "launch":
                    reply = self._launch_home(seq)
                    with self._mlock:
                        if not self._still_mine_locked(seq):
                            return
                        if not self._on_launch_reply_locked(seq, reply):
                            return
                    continue
                # call == "servo"
                self._heartbeat()
                ok = self._servo_off()
                self._heartbeat()
                with self._mlock:
                    if not self._still_mine_locked(seq) or not ok:
                        return  # ok False — выключение: итог ставит abort(stop=True)
                    self._finish_locked(seq, True, None)
                return
        except Exception as exc:
            self._on_error(seq, exc)

    # ------------------------------------------------------------------ #
    # Под _mlock
    # ------------------------------------------------------------------ #

    def _live_view_locked(self) -> ParkView | None:
        """Срез своего живого park; устаревший (закрыт снаружи или начат другой) — ``_active = False``, None."""
        if not self._active:
            return None
        v = self._state.park_view()
        if not (v.parking and v.seq == self._seq):
            self._active = False
            return None
        return v

    def _still_mine_locked(self, seq: int) -> bool:
        """После вызова вне ``_mlock``: тот же park жив и не выключение — иначе выход без записи."""
        if not (self._active and self._seq == seq):
            return False
        return not self._state.park_view().shutdown

    def _reason(self, v: ParkView, connected: bool) -> object:
        """Первая причина закрыть park: выключение (``_FREEZE``), отключение, стоп оператора, связь, срок."""
        if v.shutdown:
            return _FREEZE
        if v.disconnecting:
            return TEXT_DISCONNECTING
        if v.cancel:
            return v.cancel
        if not connected:
            return TEXT_PARK_LINK
        if self._deadline is not None and self._clock() > self._deadline:
            return TEXT_PARK_TIMEOUT
        return None

    def _advance_locked(self, v: ParkView, telemetry: Mapping[str, Any], free: bool) -> str | None:
        """Один переход шага. -> ``"launch"`` / ``"servo"`` (вызов вне ``_mlock``) или None (ждать / терминал)."""
        while True:
            step = self._step
            if step == "activity":
                if v.job_active or v.jog_busy or v.program_active:
                    return None  # программы возврата и смены инструмента доезжают сами (В-1)
                self._set_step_locked("idle")
            elif step == "idle":
                if not free:
                    return None
                self._set_step_locked("home")
            elif step == "home":
                if not self._launched:
                    if self._at_home(telemetry):
                        self._home = "already"
                        self._set_step_locked("servo")
                        continue
                    return "launch"
                if v.program_active:
                    return None
                outcome = v.home_outcome
                if outcome == "done":
                    if self._at_home(telemetry):
                        self._home = "moved"
                        self._set_step_locked("servo")
                        continue
                    if not self._home_grace:
                        self._home_grace = True  # TLM этого тика мог быть прочитан до DONE — ещё один тик
                        return None
                    self._finish_locked(self._seq, False, TEXT_PARK_NOT_HOME)
                    return None
                text = TEXT_PARK_HOME_ABORTED if outcome == "aborted" else TEXT_PARK_HOME_FAILED
                self._finish_locked(self._seq, False, text)
                return None
            elif step == "servo":
                return "servo"
            else:
                return None

    def _on_launch_reply_locked(self, seq: int, reply: dict) -> bool:
        """Ответ запуска хода домой. -> True: продолжать шаги в этом тике."""
        if reply.get("status") == "ok":
            self._launched = True
            return True  # дальше — ждать конца программы дома (program_active)
        message = reply.get("message")
        if message in _PARK_RETRY:
            return False  # захват занят на миг — повтор следующим тиком
        self._finish_locked(seq, False, str(message))
        return False

    def _at_home(self, telemetry: Mapping[str, Any]) -> bool:
        home = self._home_point()
        return (
            abs(float(telemetry["x_mm"]) - home.x) <= _HOME_TOL_MM
            and abs(float(telemetry["y_mm"]) - home.y) <= _HOME_TOL_MM
            and abs(float(telemetry["z_mm"]) - home.z) <= _HOME_TOL_MM
            and abs(float(telemetry["rz_deg"]) - home.rz) <= _HOME_TOL_DEG
        )

    def _set_step_locked(self, step: str) -> None:
        self._step = step
        self._publish_parking_locked()

    def _publish_parking_locked(self) -> None:
        """``parking`` — только при смене шага и только у живого park."""
        if not self._active or self._last_pub == self._step:
            return
        self._last_pub = self._step
        self._publish(
            {
                "seq": self._seq,
                "state": "parking",
                "step": self._step,
                "home": self._home,
                "servo": None,
                "dropped": None,
                "reason": None,
                "elapsed_s": None,
            }
        )

    def _finish_locked(self, seq: int, ok: bool, reason: str | None) -> None:
        """Терминал ``seq``: ``park_end`` (сравнить-и-поставить); проиграл — без записи."""
        won, jobs, returns = self._state.park_end(seq, ok)
        if not won:
            return
        own = self._seq == seq
        if own:
            self._active = False
        elapsed = round(self._clock() - self._t0, 3) if own and self._t0 is not None else None
        value = {
            "seq": seq,
            "state": "done" if ok else "failed",
            "step": self._step if own else "activity",
            "home": self._home if own else None,
            "servo": False if ok else None,
            "dropped": {"jobs": jobs, "returns": returns},
            "reason": reason,
            "elapsed_s": elapsed,
        }
        self._publish(value)
        if ok:
            logger.info(f"робот {self._log_id!r}: основная остановка {seq} выполнена: дом {value['home']}, серво OFF")
        else:
            logger.warning(f"робот {self._log_id!r}: основная остановка {seq} не выполнена: {reason}")
        if jobs or returns:
            logger.warning(f"робот {self._log_id!r}: {TEXT_PARK_DROPPED.format(jobs=jobs, returns=returns)}")

    def _on_error(self, seq: int | None, exc: Exception) -> None:
        """Исключение шага: счётчик, лог, ``failed`` этого ``seq`` — кроме выключения (итог ставит request_stop)."""
        self._record_err()
        logger.warning(f"робот {self._log_id!r}: шаг основной остановки прерван: {type(exc).__name__}: {exc}")
        if seq is None:
            return
        try:
            with self._mlock:
                if self._state.park_view().shutdown:
                    return
                self._finish_locked(seq, False, f"{type(exc).__name__}: {exc}")
        except Exception as fin_exc:
            self._record_err()
            logger.warning(f"робот {self._log_id!r}: итог основной остановки не записан: {type(fin_exc).__name__}")
