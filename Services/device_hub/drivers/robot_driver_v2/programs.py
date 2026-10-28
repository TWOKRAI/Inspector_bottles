"""``robot_driver_v2.programs`` (T5.3f f2).

Purpose:
    Программы драйвера робота Delta v2: запуск в потоке исполнителя, возврат, смена инструмента.

Stability: lite
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Services.device_hub.drivers.base import logger
from Services.device_hub.drivers.robot_driver_v2.args import _STORE_ERRORS, _BadArgs, _name_arg, _store_refusal
from Services.device_hub.drivers.robot_driver_v2.texts import TEXT_NO_PROGRAM, TEXT_NO_STORE, _next_thread_k
from Services.device_hub.robot_data_ops import TEXT_BAD_ARGS
from Services.robot_comm.core.protocol_v2 import STOP_LEVEL
from Services.robot_comm.errors import RobotAborted, RobotCommError, RobotNotConnectedError
from Services.robot_comm.programs import Move, Point, Program, compile_program
from Services.robot_comm.programs.generators import return_slot, toolchange
from Services.robot_comm.robot_data import load_frames, load_points, load_program

__all__ = ["ProgramMixin"]


class ProgramMixin:
    """Миксин ``RobotDriverV2``: запуск программ, возврата и смены инструмента, поток исполнителя.

    Без ``__init__`` и полей: читает атрибуты драйвера ``RobotDriverV2``.
    Поля и атрибуты базы: ``_client``, ``_pub``, ``_state``, ``_store``, ``entry``.
    Методы соседей: ``_home_point``, ``_record_err``, ``_spawn_failed``, ``_spawn_fn``, ``_store_call``,
        ``_write_stop``, ``_ws_params``, ``is_connected``.
    """

    def start_program(self, program: Any, points: Mapping[str, Point], frames: Any = None, *, name: str) -> dict:
        """Запустить программу в потоке исполнителя; один прогон за раз (DESIGN п.6)."""
        return self._launch(program, points, frames, name=name, kind="program")

    def _launch(
        self,
        program: Any,
        points: Mapping[str, Point],
        frames: Any,
        *,
        name: str,
        kind: str,
        park_seq: int | None = None,
    ) -> dict:
        """Захват (программа / задание / jog) -> компиляция -> поток исполнителя. ``kind`` («program», «return»,
        «toolchange», «park») уходит в счётчики возвратов ``_program_loop`` (T3.7 DESIGN п.7) и в допуск park
        (T5.3e). Без ``spawn`` — ``RuntimeError`` до захвата."""
        spawn = self._spawn_fn()
        # is_connected зовётся под замком состояния последней проверкой, как раньше
        refusal = self._state.admit_launch(lambda: self.is_connected, kind=kind, park_seq=park_seq)
        if refusal is not None:
            return refusal
        try:
            scenario = compile_program(program, points, frames or {}, self._ws_params())
            total = len(scenario.records)
        except Exception as exc:
            self._state.launch_failed()
            return {"status": "error", "message": str(exc)}
        thread_name = f"{self.entry.id}-prog-{_next_thread_k()}"
        try:
            handle = spawn(lambda ev: self._program_loop(scenario, name, total, kind), name=thread_name)
        except Exception as exc:
            self._state.launch_failed()
            return self._spawn_failed(thread_name, exc)
        self._state.program_started(handle)
        return {"status": "ok", "name": name, "total": total}

    def start_return(self, slot: Point, **kw: Any) -> dict:
        """Возврат из слота с домом в конце: ``return_slot(slot, home=<дом из параметров>, **kw)``."""
        try:
            gp = return_slot(slot, home=self._home_point(), **kw)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return self._launch(gp.program, gp.points, None, name=gp.program.name, kind="return")

    def start_toolchange(self, current: int, target: int, points: Mapping[str, Point], **kw: Any) -> dict:
        """Смена инструмента с домом в конце: ``toolchange(..., home=<дом из параметров>)``."""
        try:
            gp = toolchange(current, target, points, home=self._home_point(), **kw)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        return self._launch(gp.program, gp.points, None, name=gp.program.name, kind="toolchange")

    def start_park_home(self, seq: int) -> dict:
        """Ход домой основной остановки ``seq`` (T5.3e): программа ``park_home`` из одного хода JOINT в дом из
        параметров; допуск — только своему живому park (``admit_launch(kind="park")``)."""
        program = Program(name="park_home", steps=(Move(point="home", kind="JOINT"),))
        return self._launch(program, {"home": self._home_point()}, None, name="park_home", kind="park", park_seq=seq)

    def _program_loop(self, scenario: Any, name: str, total: int, kind: str = "program") -> None:
        path = f"devices.state.{self.entry.id}.program"
        state = {"name": name, "state": "running", "done": 0, "total": total, "error": None}
        resent = [False]  # повтор стопа в on_progress — один раз на прогон
        link_lost = False  # T5.3e: исход хода домой при сбое связи — «link», а не «failed»

        def on_progress(done: int, all_records: int) -> None:
            state["done"], state["total"] = done, all_records
            self._pub(path, dict(state))
            # Микроокно (К1): стоп, записанный между проверкой stopping и взятием поколения в run_chunks, прогон
            # не видит — повторяем его при первом же опросе. Повтор привязан к прогону и идёт мимо защёлки стопа
            # процесса (та запись удачна, но могла лечь до g0 прогона); только запись, без эха
            level = self._state.stop_resend_level(resent[0], kind)
            if level:
                resent[0] = True  # локальная переменная потока исполнителя
            client = self._client
            if level and client.stop_generation != client.run_stop_base:
                level = 0  # стоп записан после g0: прогон видит его сам, повтор дал бы вторую запись
            if level:
                try:
                    self._write_stop(level)
                except Exception as exc:
                    self._record_err()
                    logger.warning(f"робот {self.entry.id!r}: повтор стопа программы не доставлен: {exc}")

        try:
            self._pub(path, dict(state))
            # T5.3e: park пришёл до первого хода программы пользователя — она не начинается (В-1)
            stopping = self._state.is_stopping() or (kind == "program" and self._state.park_view().parking)
            if stopping:
                state["state"] = "aborted"  # стоп пришёл до первого хода: run_chunks не зовём
            else:
                self._client.run_chunks(scenario, params=self._ws_params(), on_progress=on_progress)
                state["state"], state["done"] = "done", state["total"]
        except RobotAborted:
            state["state"] = "aborted"
        except Exception as exc:
            self._record_err()
            # Ошибка транспорта (не ответ робота и не компиляция) — потеря связи, как в _run_next_job (jobs.py)
            link_lost = isinstance(exc, RobotNotConnectedError) or not isinstance(exc, (RobotCommError, ValueError))
            state["state"], state["error"] = "failed", f"программа прервана ошибкой: {type(exc).__name__}: {exc}"
            logger.warning(f"робот {self.entry.id!r}: программа {name!r}: {state['error']}")
        finally:
            try:
                # Итог публикуется ДО снятия program_active: robot_program_run может прийти сразу после (DESIGN 7)
                self._pub(path, dict(state))
            finally:
                # Поток программы может увидеть обрыв раньше тика (тот же сокет переподключается сам): park
                # узнаёт причину из исхода, а не из guard следующего тика (А8)
                outcome = "link" if link_lost else state["state"]
                self._state.program_finished(kind, state["state"] == "done", outcome)

    def _op_program_run(self, args: dict) -> dict:
        """Программа, точки и СК из хранилища -> ``start_program``; ответ сразу, ход — в потоке исполнителя."""
        try:
            name = _name_arg(args, "name")
        except _BadArgs:
            return {"status": "error", "message": TEXT_BAD_ARGS}
        store = self._store
        if store is None:
            return {"status": "error", "message": TEXT_NO_STORE}
        try:
            program, _rev = self._store_call(load_program, store, self.entry.id, name)
            if program is None:
                return {"status": "error", "message": TEXT_NO_PROGRAM}
            points, _points_rev = self._store_call(load_points, store, self.entry.id)
            frames, _frames_rev = self._store_call(load_frames, store, self.entry.id)
        except _STORE_ERRORS as exc:
            return _store_refusal(exc)
        return self.start_program(program, points, frames, name=name)

    def _op_program_abort(self, _args: dict) -> dict:
        """Программа идёт -> ТОЛЬКО запись SOFT (``_write_stop``), без эха: подтверждение — итог ``.program``
        ``aborted``. Программы нет -> ``stopped: False``, ``STOP_REQ`` не пишется. ``_stopping`` не ставится."""
        running = self._state.program_running()
        if not running:
            return {"status": "ok", "stopped": False}
        self._write_stop(STOP_LEVEL["SOFT"])
        return {"status": "ok", "stopped": True}
