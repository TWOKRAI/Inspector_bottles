"""``robot_driver_v2.jog`` (T5.3f f2).

Purpose:
    Jog драйвера робота Delta v2: удержание, отпускание, поводок и стоп jog.

Stability: lite
"""

from __future__ import annotations

import threading

from Services.device_hub.drivers.base import logger
from Services.device_hub.drivers.robot_driver_v2.args import _BadArgs, _int_in
from Services.device_hub.drivers.robot_driver_v2.state import _JogRun
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_LEASE_LOST,
    TEXT_STOPPING,
    _LEASE_JOIN_S,
    _LEASE_PERIOD_FALLBACK_S,
    _NOT_CONNECTED,
    _next_thread_k,
)
from Services.device_hub.robot_data_ops import TEXT_BAD_ARGS
from Services.robot_comm.core.protocol_v2 import STOP_LEVEL

__all__ = ["JogMixin"]


class JogMixin:
    """Миксин ``RobotDriverV2``: удержание jog, поводок, стоп jog.

    Без ``__init__`` и полей: читает атрибуты драйвера ``RobotDriverV2``.
    Поля и атрибуты базы: ``_client``, ``_jog_tx_lock``, ``_state``, ``entry``.
    Методы соседей: ``_close_thread``, ``_publish_error``, ``_record_err``, ``_spawn_failed``, ``_spawn_fn``,
        ``_stop_and_wait``, ``_write_stop``, ``is_connected``.
    """

    def _op_jog_hold(self, args: dict) -> dict:
        """Подтверждение удержания: нет своего jog -> JOG_CONT и поток поводка; есть -> только ``_last_hold``.

        Без ``spawn`` — ``RuntimeError`` до любой записи.
        """
        spawn = self._spawn_fn()
        try:
            direction, speed = _int_in(args, "dir", 1, 8), _int_in(args, "spd", 1, 100)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        decision = self._state.jog_hold_check()  # свой jog держится -> продление (last_hold) без JOG_CONT
        if decision == "hold":
            return {"status": "ok"}
        if decision is not None:
            return decision
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        client = self._client
        # Переход jog: стоп в полёте держит этот замок — новый JOG_CONT уйдёт после возврата stop() (п.9)
        with self._jog_tx_lock:
            # Д4: допуск ставит jog_starting — до записи jog start_program видит переход как jog (_BUSY_JOG)
            decision, prev = self._state.jog_hold_admit()
            if decision == "hold":
                return {"status": "ok"}
            if decision is not None:
                return decision
            try:
                if prev is not None and prev.stop_requested and not prev.stop_sent:
                    self._stop_jog_locked(prev)  # release / окно ещё не дослали стоп — шлём его сами, один раз
                result = client.jog_cont(direction, speed)
                run = _JogRun(seq=result.seq)
                # _last_hold — ДО spawn: spawn запускает поток при вызове, поток читает _last_hold (К3)
                # H-A: запись движения — новое поколение защёлки ПОСЛЕ неё (стоп prev выше её не покрывает)
                stopping = self._state.jog_started(run)
                if stopping:
                    # H-B: стоп процесса не взял замок перехода и записан, пока JOG_CONT был в полёте, — он мог лечь
                    # раньше движения. Стоп этого seq пишется здесь, мимо защёлки; поводок не запускается.
                    # Единственное исключение из «одна запись стопа процесса на робота»: в этой гонке их две.
                    self._state.jog_aborted_by_stop(run)
                    try:
                        self._write_stop(STOP_LEVEL["SOFT"], run)
                    except Exception as exc:
                        self._record_err()
                        logger.warning(
                            f"робот {self.entry.id!r}: стоп jog после остановки не доставлен: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    return {"status": "error", "message": TEXT_STOPPING}
                thread_name = f"{self.entry.id}-lease-{_next_thread_k()}"
                try:
                    run.handle = spawn(lambda ev: self._lease_loop(run, ev), name=thread_name)
                except Exception as exc:
                    # JOG_CONT уже подтверждён: без поводка робот остался бы в JOG_CONT, а его E_ABORTED ушёл бы в
                    # last_error как чужая ошибка — стоп шлём сами (seq — в _own_stops), затем откат (К5)
                    try:
                        self._stop_jog_locked(run)
                    except Exception as stop_exc:
                        self._record_err()
                        logger.warning(
                            f"робот {self.entry.id!r}: стоп jog после отказа spawn не доставлен: "
                            f"{type(stop_exc).__name__}: {stop_exc}"
                        )
                    self._state.jog_spawn_failed(run, prev)
                    return self._spawn_failed(thread_name, exc)
            finally:
                self._state.jog_start_done()
        return {"status": "ok", "seq": result.seq}

    def _op_jog_release(self, _args: dict) -> dict:
        """Перестать писать поводок и явно остановить свой jog (Л4); нет своего jog -> ok без записи стопа."""
        # T3.7 (ревью р.1): jog_stopping ставится вместе с пометками — до возврата стопа тик не берёт задание
        run = self._state.jog_release_begin()
        if run is None:
            return {"status": "ok"}
        try:
            # handle is None: spawn ещё не вернулся — без close; _stop_jog ждёт _jog_tx_lock, который jog_hold держит
            # до возврата spawn, поток поводка видит run.released и выходит сам (К4). close — вне _jog_tx_lock:
            # поток поводка на пути Д3 сам может ждать этот замок
            handle = run.handle
            if handle is not None:
                self._close_thread(handle, _LEASE_JOIN_S)
            self._stop_jog(run)
        finally:
            self._state.jog_release_done()
        return {"status": "ok"}

    def _stop_jog(self, run: _JogRun) -> None:
        with self._jog_tx_lock:
            if not run.stop_sent:
                self._stop_jog_locked(run)

    def _stop_jog_locked(self, run: _JogRun) -> None:
        """Под ``_jog_tx_lock``: стоп SOFT своего jog с ожиданием эха. Seq — в множество своих стопов ДО записи (Д1),
        ``stop_sent`` — сразу после записи (П4: флаг отражает запись, эхо его не держит)."""
        self._stop_and_wait(STOP_LEVEL["SOFT"], run)  # ошибка транспорта / RobotTimeout — наружу, не глушится

    def _lease_loop(self, run: _JogRun, ev: threading.Event) -> None:
        """Поток поводка: пока окно удержания не истекло, нет release и область открыта — ``jog_lease()`` раз в период.

        Окно истекло или область закрывается (``ev``) -> стоп шлёт сам поток (без close своей записи).
        Выход по любой причине снимает ``active``.
        """
        client = self._client
        period = client.jog_lease_period_s or _LEASE_PERIOD_FALLBACK_S
        try:
            while True:
                # окно удержания / ev -> stop_requested; причина для лога (D-L1) и «после начала остановки»
                decision, reason, late = self._state.lease_check(run, ev)
                if decision == "released":
                    return  # стоп шлёт release
                if decision == "stop":
                    # то же, что ``_stop_jog`` (Д3): замок и условие прежние, но «писал ли поток» известно для лога
                    with self._jog_tx_lock:
                        wrote = not run.stop_sent
                        if wrote:
                            self._stop_jog_locked(run)
                    if wrote:
                        # вне обоих замков; нет строки при release, уже записанном стопе и исключении (warning ниже)
                        suffix = " после начала остановки" if late else ""
                        logger.info(f"робот {self.entry.id!r}: jog остановлен поводком{suffix}: {reason}")
                    return
                client.jog_lease()
                run.wake.wait(period)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: поводок jog прерван: {type(exc).__name__}: {exc}")
            self._publish_error(TEXT_LEASE_LOST)
        finally:
            self._state.lease_exit(run)
