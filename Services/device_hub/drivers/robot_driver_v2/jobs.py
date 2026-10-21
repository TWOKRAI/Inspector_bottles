"""``robot_driver_v2.jobs`` (T5.3f f2).

Purpose:
    Задания и возвраты драйвера робота Delta v2 (T3.7): дренаж очередей тиком, операции постановки.

Stability: lite
"""

from __future__ import annotations

from typing import Any

from Services.device_hub.drivers.base import logger
from Services.device_hub.drivers.robot_driver_v2.args import _BadArgs, _check_wire, _coord, _whole
from Services.device_hub.drivers.robot_driver_v2.state import _Job, _Place
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_BAD_JOB_ARGS,
    TEXT_BAD_RETURN_ARGS,
    _BUSY_REPLIES,
    _NOT_CONNECTED,
)
from Services.device_hub.drivers.robot_driver_v2.tlm import _parse_tlm
from Services.robot_comm.core.client_v2 import RobotClientV2
from Services.robot_comm.core.params_v2 import to_eng
from Services.robot_comm.core.protocol_v2 import ERR, STOP_LEVEL
from Services.robot_comm.errors import RobotCommandError, RobotNak, RobotTimeout
from Services.robot_comm.programs import Point

__all__ = ["JobMixin", "_JobStopped"]


class _JobStopped(Exception):
    """``stop_event`` хаба взведён, пока тик ждёт завершения задания (DESIGN п.5)."""


class JobMixin:
    """Миксин ``RobotDriverV2``: очереди заданий и возвратов (дренаж тиком, постановка).

    Без ``__init__`` и полей: читает атрибуты драйвера ``RobotDriverV2``.
    Поля и атрибуты базы: ``_pick_lead_mm``, ``_state``, ``_values``, ``entry``, ``jobs_done``, ``jobs_failed``,
        ``jobs_sent``.
    Методы соседей: ``_link_lost``, ``_publish_error``, ``_read_tlm``, ``_record_err``, ``_record_ok``,
        ``_spawn_fn``, ``_stop_and_wait``, ``_stop_latched``, ``is_connected``, ``start_return``.
    """

    def _dispatch(self, client: RobotClientV2, free: bool, stop_event: Any) -> None:
        """Одно действие за тик (DESIGN п.4): возврат из очереди, иначе задание. Обе ветки требуют ``free``.

        «Захват свободен» и взятие задания — один переход ``take_next_action``: ``job_active`` ставится ДО
        ``cvt_job``, поэтому ``jog_hold`` / ``start_program`` между проверкой и записью видят ``_BUSY_JOB`` (R7).
        """
        if not free:
            return
        item, job = self._state.take_next_action()
        if item is not None:
            self._start_next_return(item)
        elif job is not None:
            self._run_next_job(client, job, stop_event)

    def _run_next_job(self, client: RobotClientV2, job: _Job, stop_event: Any) -> None:
        """CVT_JOB + ожидание завершения в потоке тика (R1); пульс — ``on_poll``. Исключения из тика не выходят."""
        x, y, z, ecap, place = job

        def on_poll(_tlm: Any) -> None:
            if stop_event is not None and stop_event.is_set():
                raise _JobStopped
            client.kick_heartbeat()

        try:
            flags = (1 if z != 0.0 else 0) | (2 if place is not None else 0)
            if place is not None:
                px, py, pz, turn = place
                prz = to_eng("P_PICK_RZ", self._values["P_PICK_RZ"]) + turn  # R3: v2 забирает под P_PICK_RZ
            else:
                px = py = pz = prz = 0.0
            try:
                res = client.cvt_job(ecap & 0xFFFFFFFF, x, y, z, flags, px, py, pz, prz)
            except RobotNak as exc:
                if exc.errno != ERR["E_BUSY"]:
                    raise
                self._state.requeue_job(job)  # робот занят — повтор следующим тиком (паритет v1)
                return
            self.jobs_sent += 1
            client.wait_done(res.seq, on_poll=on_poll)
            self.jobs_done += 1
            self._record_ok()
        except (RobotTimeout, _JobStopped) as exc:
            self.jobs_failed += 1
            try:
                # R9: HARD (SOFT на CVT отложился бы до точки захвата). Останов хаба — через защёлку без эха (H1):
                # стоп процесса уже записал HARD этому заданию; таймаут задания — стоп с эхом, как раньше
                if isinstance(exc, _JobStopped):
                    self._stop_latched(STOP_LEVEL["HARD"])
                else:
                    self._stop_and_wait(STOP_LEVEL["HARD"])
            except Exception as stop_exc:
                self._record_err()
                logger.warning(f"робот {self.entry.id!r}: стоп задания не доставлен: {type(stop_exc).__name__}")
            text = "останов хаба" if isinstance(exc, _JobStopped) else str(exc)
            self._publish_error(f"задание прервано: {text}")
        except (RobotNak, RobotCommandError) as exc:
            self.jobs_failed += 1  # RobotAborted — подкласс RobotCommandError; задание теряется (паритет v1)
            self._publish_error(exc.text)
        except ValueError as exc:
            self.jobs_failed += 1  # R8: аргумент вне провода — не обрыв связи
            self._publish_error(f"задание не отправлено: {exc}")
        except Exception as exc:
            self.jobs_failed += 1
            self._record_err()
            logger.warning(f"робот {self.entry.id!r}: задание прервано сбоем связи: {type(exc).__name__}: {exc}")
            self._link_lost()  # урок fd5c003e8: сырой OSError оставляет is_connected == True
        finally:
            self._state.job_finished()

    def _start_next_return(self, item: tuple[float, float, float]) -> None:
        """Возврат, взятый тиком из очереди, — программой ``return_slot`` на потоке исполнителя (R2, DESIGN п.6)."""
        x, y, z = item
        v = self._values
        slot = Point(
            name="return_slot",
            x=x,
            y=y,
            z=z if z != 0.0 else to_eng("P_PLACE_Z", v["P_PLACE_Z"]),
            rz=to_eng("P_PICK_RZ", v["P_PICK_RZ"]),
            hand=int(v["P_HAND"]),
        )
        try:
            res = self.start_return(slot)
        except Exception as exc:  # H2: возврат не теряется молча — отказ считается и виден
            res = {"status": "error", "message": str(exc)}
        if res.get("status") == "ok":
            return
        if res in _BUSY_REPLIES:
            self._state.requeue_return(item)  # захват перехвачен между секциями — повтор следующим тиком
            return
        self._state.return_failed()
        self._publish_error(str(res.get("message")))

    def _op_enqueue_job(self, args: dict) -> dict:
        """Задание CVT_JOB в очередь (R1, R3-R6, R8): ключи v1 {x_mm, y_mm, z_mm?, e_capture?, place_x?, place_y?,
        place_z?, place_rz?}; ``place_rz`` — доворот к ``P_PICK_RZ``. Плохой ввод -> постоянный текст, очередь цела."""
        try:
            x, y = _coord(args, "x_mm"), _coord(args, "y_mm")
            z = _coord(args, "z_mm", 0.0)  # R6: 0 — умолчание прошивки P_PICK_Z (бит0 = 0)
            place: _Place | None = None
            if args.get("place_x") is not None and args.get("place_y") is not None:
                turn = _coord(args, "place_rz", 0.0)
                _check_wire(to_eng("P_PICK_RZ", self._values["P_PICK_RZ"]) + turn, "place_rz")
                place = (_coord(args, "place_x"), _coord(args, "place_y"), _coord(args, "place_z", 0.0), turn)
            raw_ecap = args.get("e_capture")
            ecap = None if raw_ecap is None else _whole(raw_ecap, "e_capture")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_JOB_ARGS, "queue_len": self._state.job_queue_len()}
        if not self.is_connected:
            return {**_NOT_CONNECTED, "queue_len": self._state.job_queue_len()}
        if ecap is None:
            ecap = _parse_tlm(self._read_tlm())[2]  # R5: энкодер сейчас, в потоке команды (s32)
        if self._pick_lead_mm != 0.0:
            # R4: ход ленты на импульс — P_BELT_FACTOR × 1e-5 мм/имп (не константа v1)
            ecap -= round(self._pick_lead_mm / (self._values["P_BELT_FACTOR"] * 1e-5))
        n = self._state.enqueue_job((x, y, z, ecap, place))  # maxlen: старейшее вытесняется (паритет v1)
        return {"status": "ok", "queue_len": n}

    def _op_return_job(self, args: dict) -> dict:
        """Возврат из слота {x_mm, y_mm, z_mm?} в очередь возвратов; исполнение — тиком (R2, DESIGN п.3).

        Без ``spawn`` — ``RuntimeError`` до очереди: возврат идёт программой на потоке исполнителя (H2).
        """
        self._spawn_fn()
        try:
            item = (_coord(args, "x_mm"), _coord(args, "y_mm"), _coord(args, "z_mm", 0.0))
        except _BadArgs:
            return {
                "status": "error",
                "message": TEXT_BAD_RETURN_ARGS,
                "return_queue_len": self._state.return_queue_len(),
            }
        if not self.is_connected:
            return {**_NOT_CONNECTED, "return_queue_len": self._state.return_queue_len()}
        n = self._state.enqueue_return(item)
        return {"status": "ok", "return_queue_len": n}
