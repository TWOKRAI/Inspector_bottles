"""``robot_driver_v2.stop`` (T5.3f f2).

Purpose:
    Остановка драйвера робота Delta v2 (ADR-DH-009): ``request_stop``, стоп процесса, защёлка, эхо стопа.

Stability: lite
"""

from __future__ import annotations

import time

from Services.device_hub.drivers.base import logger
from Services.device_hub.drivers.robot_driver_v2.state import _JogRun
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_NO_ECHO_WINDOW,
    TEXT_STOPPING,
    TEXT_STOP_UNCONFIRMED,
    _PROCESS_STOP_DEFAULT_S,
)
from Services.robot_comm.core.protocol_v2 import STOP_LEVEL

__all__ = ["StopMixin"]


class StopMixin:
    """Миксин ``RobotDriverV2``: остановка плагина и процесса, защёлка стопа, проверка эха.

    Без ``__init__`` и полей: читает атрибуты драйвера ``RobotDriverV2``.
    Поля и атрибуты базы: ``_cfg``, ``_client``, ``_jog_tx_lock``, ``_state``, ``_transport``, ``entry``.
    Методы соседей: ``_publish_error``, ``_record_err``, ``_stop_jog``, ``is_connected``.
    """

    def request_stop(self, deadline: float | None = None) -> None:
        """Фаза 1 остановки плагина (К1): защёлка ``_shutdown`` и одна запись стопа без эха, потоков и закрытия.

        ``deadline`` — абсолютный срок по ``time.monotonic()`` (None — сейчас + ``_PROCESS_STOP_DEFAULT_S``). Уровень —
        сильнейший нужный: задание и программа HARD (SOFT посреди хода ждал бы цели), jog SOFT. Простой подключённый
        робот (нет задания, программы и jog) тоже получает один SOFT (решение владельца 2026-10-19); не подключённый
        простой — нет. Защёлка: уровень не ниже уже записан и последняя запись не упала
        — записи нет; упавшая запись повторяется ровно один раз, пока не вышел срок. ``_jog_tx_lock`` берётся с
        таймаутом остатка срока; не взят — стоп пишется без замка (В1). Затем проверка эха этой записи (H7): чтения
        начинаются, только пока чтение с повторами транспорта успевает до срока; окно было, эха нет, или запись не
        прошла — «стоп не подтверждён роботом»; окна нет (срок меньше бюджета записи) — «эхо не читалось (нет окна)»
        (``last_error``, свойство ``stop_unconfirmed`` для health плагина).
        Не бросает. Повторный вызов безопасен. После него ``connect()`` возвращает False, ``jog_hold`` и запуск
        программы отвечают ``TEXT_STOPPING``.
        """
        if deadline is None:
            deadline = time.monotonic() + _PROCESS_STOP_DEFAULT_S
        self._state.request_stop_begin()  # защёлка выключения; первый вызов — новое поколение защёлки
        locked = self._jog_tx_lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        try:
            if not locked:
                logger.warning(f"робот {self.entry.id!r}: замок перехода jog не взят до срока — стоп пишется без него")
            self._process_stop(deadline)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: стоп процесса прерван: {type(exc).__name__}: {exc}")
        finally:
            if locked:
                self._jog_tx_lock.release()
        try:
            # T5.3e: идущий park -> failed «драйвер останавливается» — после записи стопа (D5 «Гарантия выключения»)
            self._park.abort(TEXT_STOPPING, stop=True)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: итог основной остановки не записан: {type(exc).__name__}: {exc}")
        try:
            self._check_stop_echo(deadline)
        except Exception as exc:
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: проверка эха прервана: {type(exc).__name__}: {exc}")

    @property
    def stop_unconfirmed(self) -> bool:
        """Стоп процесса этого робота не подтверждён (нет эха или запись не прошла); для health плагина."""
        return self._state.stop_unconfirmed()

    @property
    def stop_unconfirmed_text(self) -> str | None:
        """Текст причины для health: ``TEXT_STOP_UNCONFIRMED`` или ``TEXT_NO_ECHO_WINDOW``; ``None`` — не помечен."""
        return self._state.stop_unconfirmed_text()

    def _transport_up(self) -> bool:
        """Транспорт подключён сейчас (без ``_ready``); замков не берёт — зовётся под замком состояния."""
        return self._transport is not None and bool(self._transport.is_connected)

    def _process_stop(self, deadline: float) -> None:
        """Тело ``request_stop`` (замок перехода jog взят или не взят по сроку): пометки, защёлка, запись."""
        # is_connected зовётся под замком состояния, в той же ветке, что и раньше (простой робот)
        level, run, stop_jog = self._state.process_stop_plan(
            lambda: self.is_connected,
            link_up=self._transport_up,
        )
        if not level or self._client is None:
            return  # простой неподключённый робот, стоп уже записан или нет клиента: записи нет
        jog_run = run if stop_jog else None
        while True:
            # Повтор — только после упавшей записи и только если запись успеет до срока (не больше двух попыток)
            attempt = self._state.next_stop_attempt(deadline, self._write_budget_s)
            if attempt is None:
                return
            try:
                self._write_stop(level, jog_run)
                return
            except Exception as exc:
                self._record_err()
                logger.warning(
                    f"робот {self.entry.id!r}: стоп процесса не записан ({attempt}): {type(exc).__name__}: {exc}"
                )

    def _write_budget_s(self) -> float:
        """Худшее время одной записи: ``timeout_sec * (retries + 1)`` транспорта (умолчания build_transport)."""
        transport = getattr(self.entry, "transport", None) or {}
        return float(transport.get("timeout_sec", 1.0)) * (int(transport.get("retries", 1)) + 1)

    def _write_stop(self, level: int, run: _JogRun | None = None) -> int:
        """Одна запись ``STOP_REQ`` (``client.issue_stop``) без эха; итог — в защёлку. Ошибка записи — наружу.

        ``run`` — jog, которому адресован стоп: его seq — в множество своих стопов ДО записи (Д1), ``stop_sent`` —
        сразу ПОСЛЕ удачной записи (флаг отражает запись, не эхо).
        """
        if run is not None:
            self._state.note_own_stop(run.seq)
        try:
            value = self._client.issue_stop(level)
        except Exception:
            self._state.stop_write_failed()
            raise
        self._state.stop_written(value, run)
        return value

    def _stop_and_wait(self, level: int, run: _JogRun | None = None) -> None:
        """Стоп с эхом (пути оператора и обычный disconnect): запись через защёлку + эхо по таймауту клиента."""
        value = self._write_stop(level, run)
        written = value & 3
        timeout = self._cfg.soft_echo_timeout_s if written == STOP_LEVEL["SOFT"] else self._cfg.stop_echo_timeout_s
        self._client.await_stop_echo(value, written, deadline=time.monotonic() + timeout)

    def _check_stop_echo(self, deadline: float) -> None:
        """Эхо записи стопа процесса этого поколения, без записи, один раз на значение (H7).

        Чтения идут до ``deadline - _write_budget_s()``: чтение, начатое позже, могло бы пережить срок на мёртвой
        связи. Исходы без подтверждения (``stop_unconfirmed`` и ``last_error``): запись прошла, окно было, эха нет —
        ``TEXT_STOP_UNCONFIRMED``; запись прошла, окна нет — ``TEXT_NO_ECHO_WINDOW``; запись не прошла —
        ``TEXT_STOP_UNCONFIRMED``. Простой робот (записи не было) не проверяется. Не бросает.
        """
        check, value = self._state.echo_check_plan()  # проверяемое значение помечается в том же переходе
        if not check:
            return
        client = self._client
        read_until = deadline - self._write_budget_s()
        confirmed = False
        has_window = value is not None and client is not None and time.monotonic() < read_until
        if has_window:
            try:
                client.await_stop_echo(value, value & 3, deadline=read_until)
                confirmed = True
            except Exception as exc:
                logger.warning(f"робот {self.entry.id!r}: эхо стопа не получено: {type(exc).__name__}: {exc}")
        if confirmed:
            return
        # запись прошла, а читать эхо было некогда (срок минус бюджет записи) — это не «эхо не пришло»
        no_window = value is not None and client is not None and not has_window
        text = TEXT_NO_ECHO_WINDOW if no_window else TEXT_STOP_UNCONFIRMED
        self._state.mark_unconfirmed(text)
        self._record_err()
        logger.warning(f"робот {self.entry.id!r}: {text}")
        self._publish_error(text)

    def _stop_latched(self, level: int) -> None:
        """Запись стопа без эха через защёлку: такой уровень уже записан в этом поколении — записи нет (H1)."""
        if self._state.latch_covers(level):
            return
        self._write_stop(level)

    def _request_stop(self, program_level: int) -> None:
        """Стоп обычного ``disconnect``: флаг ``_stopping``, пометка jog, стопы с ожиданием эха без замков (К1)."""
        # V1: JOG_CONT в полёте дописывает jog под _jog_tx_lock — читаем его под тем же замком
        with self._jog_tx_lock:
            run, stop_jog, prog_alive, job_active = self._state.disconnect_stop_plan(
                program_level, link_up=self._transport_up
            )
        # _stop_jog снова берёт _jog_tx_lock (не реентерабельный) — замки отпущены
        client = self._client
        if client is None:
            return
        if job_active:
            # HARD обрывает ход CVT сразу; SOFT на CVT откладывается до точки захвата (R9). Тик, ждущий wait_done,
            # получает RobotAborted или ошибку транспорта и считает задание неудачным.
            try:
                self._stop_and_wait(STOP_LEVEL["HARD"])
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп задания не доставлен: {type(exc).__name__}: {exc}")
        if stop_jog and run is not None:
            try:
                self._stop_jog(run)
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп jog не доставлен: {type(exc).__name__}: {exc}")
        if prog_alive:
            try:
                self._stop_and_wait(program_level)
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп программы не доставлен: {type(exc).__name__}: {exc}")
        if not (job_active or stop_jog or prog_alive) and self._state.disconnect_soft_plan(
            lambda: self.is_connected, self._transport_up
        ):
            # Решение владельца 2026-10-19: отключаемый подключённый робот получает стоп и в покое (SOFT);
            # решение владельца 2026-10-21: и робот посреди connect, чья связь была поднята к стоп-секции (снимок
            # _stop_linked, транспорт жив). Защёлка гасит вторую запись в том же выключении (внутри перехода).
            # Только запись SOFT: эхо простого робота не читается (supervisor не ждёт soft_echo_timeout_s),
            # last_error нет (T5.3c c3)
            try:
                self._write_stop(STOP_LEVEL["SOFT"])
            except Exception as exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп простого робота не записан: {type(exc).__name__}: {exc}")
