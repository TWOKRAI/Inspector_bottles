"""``robot_driver_v2.ops`` (T5.3f f2).

Purpose:
    Операции драйвера робота Delta v2: таблица ``OPS`` (имя операции -> функция) и операции оператора.

Stability: lite
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from Services.device_hub.drivers.exchange_log import TEXT_BAD_GET_ARGS, TEXT_BAD_KNOBS
from Services.device_hub.drivers.robot_driver_v2.args import (
    _STORE_ERRORS,
    _BadArgs,
    _base_rev_arg,
    _number_arg,
    _bool_arg,
    _int_in,
    _is_int,
    _name_arg,
    _store_refusal,
    _strict_coord,
)
from Services.device_hub.drivers.robot_driver_v2.jobs import JobMixin
from Services.device_hub.drivers.robot_driver_v2.jog import JogMixin
from Services.device_hub.drivers.robot_driver_v2.params import ParamMixin
from Services.device_hub.drivers.robot_driver_v2.programs import ProgramMixin
from Services.device_hub.drivers.robot_driver_v2.texts import (
    TEXT_BAD_DO,
    TEXT_BAD_STOP_LEVEL,
    TEXT_NO_STORE,
    TEXT_PARK_CANCELLED,
    _DO_CHANNELS,
    _LEASE_JOIN_S,
    _NOT_CONNECTED,
    _OPERATOR_ECHO_BUDGET_S,
    _PARK_TIMEOUT_DEFAULT_S,
    _PARK_TIMEOUT_MAX_S,
    _PARK_TIMEOUT_MIN_S,
    _STOP_NAMES,
)
from Services.device_hub.drivers.robot_driver_v2.tlm import _parse_tlm
from Services.device_hub.robot_data_ops import TEXT_BAD_ARGS
from Services.robot_comm.core.protocol_v2 import STOP_LEVEL
from Services.robot_comm.errors import RobotTimeout
from Services.robot_comm.programs import Point
from Services.robot_comm.robot_data import load_points, save_points

if TYPE_CHECKING:
    from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

__all__ = ["OPS", "OpsMixin", "_EXCHANGE_OPS", "_op_exchange_log_get", "_op_exchange_log_set"]


class OpsMixin:
    """Миксин ``RobotDriverV2``: операции оператора (телеметрия, стоп, servo, DO, jog_step, точка).

    Без ``__init__`` и полей: читает атрибуты драйвера ``RobotDriverV2``.
    Поля и атрибуты базы: ``_client``, ``_state``, ``_store``, ``entry``.
    Методы соседей: ``_read_tlm``, ``_store_call``, ``_write_stop``, ``is_connected``.
    """

    def _op_get_telemetry(self, _args: dict) -> dict:
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        telemetry, free, encoder = _parse_tlm(self._read_tlm())
        return {
            "status": "ok",
            "telemetry": telemetry,
            "free": free,
            "encoder": encoder,
            "queue_len": self._state.job_queue_len(),
        }

    def _op_abort(self, args: dict) -> dict:
        """Стоп оператора {mode: 1|2|3 или "SOFT"|"HARD"|"HALT"}: тело — ``_operator_stop``; ответ прежней формы."""
        result = self._operator_stop(args.get("mode", STOP_LEVEL["SOFT"]))
        if result["status"] != "ok":
            return result
        return {"status": "ok", "mode": result["level"]}

    def _operator_stop(self, raw_level: Any) -> dict:
        """Общее тело ``stop`` и ``abort`` (T5.3d DESIGN 3): запись ``STOP_REQ`` через ``_write_stop`` (мимо защёлки
        стопа процесса, но с её учётом), затем опрос эха до ``t0 + 0,8 с``. Замков драйвера не берёт, ``_stopping`` не
        ставит. Итог: ``{"status": "ok", "level": <int>, "echo": bool}``; нет эха к сроку — ``echo: False`` без ошибки
        (отложенный SOFT до цели хода — норма протокола). Плохой уровень — ``TEXT_BAD_STOP_LEVEL``, робот не тронут."""
        t0 = time.monotonic()
        if isinstance(raw_level, str) and raw_level.upper() in STOP_LEVEL:
            level = STOP_LEVEL[raw_level.upper()]
        elif isinstance(raw_level, int) and not isinstance(raw_level, bool) and raw_level in STOP_LEVEL.values():
            level = raw_level
        else:
            return {"status": "error", "message": TEXT_BAD_STOP_LEVEL}
        client = self._client
        if client is None:
            return dict(_NOT_CONNECTED)
        value = self._write_stop(level)  # ошибка записи — наружу: стоп не доставлен
        # T5.3e: удачный стоп оператора любого уровня отменяет идущий park (итог ставит тик)
        self._state.park_cancel(TEXT_PARK_CANCELLED)
        try:
            client.await_stop_echo(value, value & 3, deadline=t0 + _OPERATOR_ECHO_BUDGET_S)
        except RobotTimeout:
            return {"status": "ok", "level": level, "echo": False}
        return {"status": "ok", "level": level, "echo": True}

    def _motion_refusal(self, *, syncing: bool = False) -> dict | None:
        """Отказ занятости для движения и записи параметров: останов, программа, задание, jog (и синхронизация)."""
        return self._state.motion_refusal(syncing)

    def _op_stop(self, args: dict) -> dict:
        """Стоп оператора {level}: занятость не проверяет; ответ ``{"status", "level": <ИМЯ>, "echo": bool}``."""
        result = self._operator_stop(args.get("level", STOP_LEVEL["SOFT"]))
        if result["status"] != "ok":
            return result
        return {"status": "ok", "level": _STOP_NAMES[result["level"]], "echo": result["echo"]}

    def _op_servo(self, args: dict) -> dict:
        try:
            on = _bool_arg(args, "on")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        refusal = self._motion_refusal()
        if refusal is not None:
            return refusal
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        self._client.servo(on)
        if on:
            self._state.servo_on_done()  # T5.3e (В-4): «серво ON» снимает запрет движения после park
        return {"status": "ok"}

    def _op_park(self, args: dict) -> dict:
        """Основная остановка {timeout_s?} (T5.3e, В2): ответ сразу ``{accepted, seq, timeout_s}``, ход — в тике.

        Порядок: допуск ``park_begin`` -> стоп держащегося jog (тело ``jog_release``) -> SOFT программе
        пользователя (В-1) -> ``accept`` автомата последним (до него тик дом не запустит). Сбой после допуска —
        ``failed`` этого ``seq`` и ответ-ошибка.
        """
        try:
            timeout_s = self._park_timeout(args)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        begin = self._state.park_begin()
        if begin.refusal is not None:
            return begin.refusal
        try:
            run = begin.run
            if run is not None:
                try:
                    handle = run.handle
                    if handle is not None:
                        self._close_thread(handle, _LEASE_JOIN_S)  # вне замков: поток поводка может ждать замок
                    self._stop_jog(run)
                finally:
                    self._state.jog_release_done()
            if begin.prog_soft:
                self._write_stop(STOP_LEVEL["SOFT"])
            self._park.accept(begin.seq, timeout_s)
        except Exception as exc:
            self._record_err()
            self._park.fail(begin.seq, f"{type(exc).__name__}: {exc}")
            return {"status": "error", "message": f"основная остановка не начата: {type(exc).__name__}: {exc}"}
        return {"status": "ok", "accepted": True, "seq": begin.seq, "timeout_s": timeout_s}

    def _park_timeout(self, args: dict) -> float:
        """Срок park: аргумент, иначе ``entry.params["park_timeout_s"]``, иначе 30 с; число 1..60, bool — нет."""
        if "timeout_s" in args:
            value = _number_arg(args, "timeout_s")
        elif "park_timeout_s" in self._params:
            value = _number_arg(self._params, "park_timeout_s")
        else:
            value = _PARK_TIMEOUT_DEFAULT_S
        if not _PARK_TIMEOUT_MIN_S <= value <= _PARK_TIMEOUT_MAX_S:
            raise _BadArgs("timeout_s")
        return value

    def _op_do_set(self, args: dict) -> dict:
        try:
            on = _bool_arg(args, "on")
            ch = args.get("ch")
            if type(ch) is not int:
                raise _BadArgs("ch")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        if ch not in _DO_CHANNELS:
            return {"status": "error", "message": TEXT_BAD_DO}
        refusal = self._motion_refusal()
        if refusal is not None:
            return refusal
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        self._client.do_set(ch, on)
        return {"status": "ok"}

    def _op_jog_step(self, args: dict) -> dict:
        """JOG_STEP {dx, dy, dz=0, drz=0, spd 1..100}: ``done_seq``-команда — отказ при программе / jog / задании /
        синхронизации; ответ после ACK, без ожидания DONE."""
        try:
            dx, dy = _strict_coord(args, "dx"), _strict_coord(args, "dy")
            dz, drz = _strict_coord(args, "dz", 0.0), _strict_coord(args, "drz", 0.0)
            speed = _int_in(args, "spd", 1, 100)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        refusal = self._state.disconnect_refusal() or self._motion_refusal(syncing=True)
        if refusal is not None:
            return refusal
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        result = self._client.jog_step(dx, dy, dz, drz, speed)
        return {"status": "ok", "seq": result.seq}

    def _op_point_capture(self, args: dict) -> dict:
        """Поза из TLM -> ``Point(frame=None)`` -> вставка в ``points.yaml``; ответ после записи файла (О9-а)."""
        try:
            name, base_rev = _name_arg(args, "name"), _base_rev_arg(args)
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        store = self._store
        if store is None:
            return {"status": "error", "message": TEXT_NO_STORE}
        if not self.is_connected:
            return dict(_NOT_CONNECTED)
        telemetry, _free, _encoder = _parse_tlm(self._read_tlm())
        point = Point(
            name=name,
            x=telemetry["x_mm"],
            y=telemetry["y_mm"],
            z=telemetry["z_mm"],
            rz=telemetry["rz_deg"],
            hand=telemetry["hand"],
            frame=None,
        )
        try:
            points, _rev = self._store_call(load_points, store, self.entry.id)
            points[name] = point
            rev = self._store_call(save_points, store, self.entry.id, points, base_rev=base_rev)
        except _STORE_ERRORS as exc:
            return _store_refusal(exc)
        return {"status": "ok", "point": point.to_dict(), "rev": rev}


def _op_exchange_log_get(drv: RobotDriverV2, args: dict) -> dict:
    """Строки журнала обмена {since_seq=0, limit=200} и состояние; работает и без связи с роботом.

    Плохой аргумент — постоянный текст отказа (R8), счётчик ошибок обмена не растёт.
    """
    since_seq, limit = args.get("since_seq", 0), args.get("limit", 200)
    if not (_is_int(since_seq) and _is_int(limit)) or since_seq < 0 or limit < 1:
        return {"status": "error", "message": TEXT_BAD_GET_ARGS}
    return {"status": "ok", **drv._exchange_log.get(since_seq=since_seq, limit=limit)}


def _op_exchange_log_set(drv: RobotDriverV2, args: dict) -> dict:
    """Ручки журнала {enabled?, periodic?, clear?} без переподключения; ответ — состояние без строк."""
    knobs = {key: args.get(key) for key in ("enabled", "periodic", "clear")}
    if any(v is not None and not isinstance(v, bool) for v in knobs.values()):
        return {"status": "error", "message": TEXT_BAD_KNOBS}
    return {"status": "ok", **drv._exchange_log.set(**knobs)}


_EXCHANGE_OPS = {
    "exchange_log_get": _op_exchange_log_get,
    "exchange_log_set": _op_exchange_log_set,
}


OPS: dict[str, Callable[[RobotDriverV2, dict], dict]] = {
    "jog_hold": JogMixin._op_jog_hold,
    "jog_release": JogMixin._op_jog_release,
    "get_telemetry": OpsMixin._op_get_telemetry,
    "enqueue_job": JobMixin._op_enqueue_job,
    "return_job": JobMixin._op_return_job,
}
OPS["abort"] = OpsMixin._op_abort  # T5.3 круг 2: стоп оператора, мимо защёлки
OPS.update(_EXCHANGE_OPS)  # Журнал обмена (T5.6): две операции отдельным блоком

# Операции движения и параметров (T5.3d d1): отдельным блоком
OPS.update(
    {
        "stop": OpsMixin._op_stop,
        "servo": OpsMixin._op_servo,
        "do_set": OpsMixin._op_do_set,
        "jog_step": OpsMixin._op_jog_step,
        "point_capture": OpsMixin._op_point_capture,
        "param_set": ParamMixin._op_param_set,
        "param_apply": ParamMixin._op_param_apply,
        "program_run": ProgramMixin._op_program_run,
        "program_abort": ProgramMixin._op_program_abort,
    }
)
OPS["park"] = OpsMixin._op_park  # T5.3e: основная остановка (В2), последней — порядок ROBOT_V2_OPS
