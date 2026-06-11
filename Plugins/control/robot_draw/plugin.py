"""RobotDrawPlugin — рисование фигур роботом (полилинии, круги, прямоугольники).

ПОТРЕБИТЕЛЬ соединения: клиента берёт из ``Services.robot_comm.runtime``
(владелец — robot_io, co-location в одном процессе обязательна).

АСИНХРОННОЕ исполнение (ревью п.7): ``draw()``/``draw_circle()`` блокируют до
draw_timeout_s (ожидание прохода робота) — выполнять их в обработчике команды
нельзя (заморозит round-trip и process()). Команды ``draw_*`` лишь кладут
задание в очередь и возвращаются сразу; фоновый worker исполняет, состояние
``idle|drawing|done|failed`` и прогресс — в register и state-дереве.

Перед фигурой worker переключает робота в режим DRAW (когда свободен);
координаты пера берутся из задания (z) или из register (pen_down/up).
"""

from __future__ import annotations

import queue
import time
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    Port,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Services.modbus import ModbusDriverError
from Services.robot_comm import DrawPoint, RobotJobError, RobotNotConnectedError, runtime

from .registers import RobotDrawRegisters

# Ожидание освобождения робота перед переключением в DRAW, сек.
_MODE_SWITCH_WAIT_S = 5.0


def gen_rect(x1: float, y1: float, x2: float, y2: float) -> list[DrawPoint]:
    """Прямоугольник по двум противоположным углам — только 4 вершины.

    Робот сам едет прямой MovL между вершинами, дробить стороны не нужно.
    Подвод пером вверх к углу 1 -> перо вниз -> обход 4 углов + замыкание.
    """
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    points = [DrawPoint(corners[0][0], corners[0][1], 0), DrawPoint(corners[0][0], corners[0][1], 1)]
    points += [DrawPoint(cx, cy, 1) for cx, cy in corners[1:] + [corners[0]]]
    return points


@register_plugin(
    "robot_draw",
    category="control",
    description="Рисование фигур роботом Delta (полилинии/круги/прямоугольники)",
)
class RobotDrawPlugin(ProcessModulePlugin):
    """Очередь заданий рисования + фоновый исполнитель с прогрессом."""

    name = "robot_draw"
    category = "control"
    thread_safe = False

    inputs = [
        Port(name="points", dtype="list[dict]", optional=True, description="Точки {x_mm,y_mm,pen} (auto_draw)"),
    ]
    outputs = []

    commands = {
        "draw_points": "cmd_draw_points",
        "draw_circle": "cmd_draw_circle",
        "draw_square": "cmd_draw_square",
        "set_pen": "cmd_set_pen",
        "set_draw_speed": "cmd_set_draw_speed",
        "set_overlap": "cmd_set_overlap",
        "abort_draw": "cmd_abort_draw",
        "get_draw_progress": "cmd_get_draw_progress",
    }
    register_class = RobotDrawRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class → register_schema() резолвит register_bindings."""
        from .config import RobotDrawPluginConfig

        return RobotDrawPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: register + очередь заданий."""
        self._ctx = ctx
        self._reg: RobotDrawRegisters = self._init_register(ctx)
        self._tasks: "queue.Queue[dict]" = queue.Queue()
        ctx.log_info("RobotDrawPlugin: configured")

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: поднять исполнителя рисования."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("robot_draw_worker", self._draw_loop, cfg, auto_start=True)
        ctx.log_info("RobotDrawPlugin: started")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED: прервать текущее рисование (клиент не закрываем — не владелец)."""
        client = runtime.peek_client()
        if client is not None and client.is_connected and self._reg.busy:
            try:
                client.draw_abort()
            except ModbusDriverError as exc:  # pragma: no cover - defensive
                ctx.log_error(f"RobotDrawPlugin: abort на shutdown упал: {exc}")
        ctx.log_info(f"RobotDrawPlugin: shutdown (нарисовано фигур: {self._reg.draws_done})")

    # ------------------------------------------------------------------ #
    # PROCESS — авто-рисование из item (опционально)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """При auto_draw: точки из item[points_source] -> очередь. Pass-through."""
        if not self._reg.auto_draw:
            return items
        for item in items:
            raw = item.get(self._reg.points_source)
            if isinstance(raw, list) and raw:
                self._enqueue({"kind": "points", "points": raw})
        return items

    # ------------------------------------------------------------------ #
    # WORKER — исполнение заданий
    # ------------------------------------------------------------------ #

    def _draw_loop(self, stop_event, pause_event) -> None:
        """Фон: брать задания из очереди и исполнять (блокирующе — здесь можно)."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                task = self._tasks.get(timeout=0.2)
            except queue.Empty:
                continue
            self._execute(task, stop_event)

    def _execute(self, task: dict, stop_event) -> None:
        """Одно задание: режим DRAW -> параметры пера -> фигура -> состояние."""
        client = self._get_client()
        if client is None:
            self._fail("клиент робота недоступен (владелец robot_io не стартовал?)")
            return
        self._reg.state = "drawing"
        self._reg.busy = True
        self._publish_state()
        try:
            self._prepare(client, task, stop_event)
            ok = self._run_figure(client, task)
        except (ModbusDriverError, RobotJobError, ValueError) as exc:
            self._fail(str(exc))
            return
        finally:
            self._reg.busy = False
        if ok:
            self._reg.state = "done"
            self._reg.draws_done += 1
        else:
            self._fail("рисование не завершилось (таймаут/abort)")
            return
        self._publish_state()

    def _prepare(self, client, task: dict, stop_event) -> None:
        """Переключить в DRAW (дождавшись free) и применить параметры пера."""
        t_end = time.monotonic() + _MODE_SWITCH_WAIT_S
        while time.monotonic() < t_end and not stop_event.is_set():
            if client.is_free():
                break
            time.sleep(0.05)
        client.set_mode("draw")
        z = task.get("z")
        if z is not None:
            client.set_pen(float(z), float(z) + self._reg.lift_mm)
        else:
            client.set_pen(self._reg.pen_down_mm, self._reg.pen_up_mm)
        client.set_draw_speed(int(self._reg.draw_speed_pct))
        client.set_overlap(float(self._reg.overlap_mm))

    def _run_figure(self, client, task: dict) -> bool:
        """Исполнить фигуру задания."""
        timeout = float(self._reg.draw_timeout_s)
        if task["kind"] == "circle":
            self._reg.total_points = 0
            return client.draw_circle(task["cx"], task["cy"], task["r"], timeout=timeout)
        points = [
            p if isinstance(p, DrawPoint) else DrawPoint(float(p["x_mm"]), float(p["y_mm"]), int(p.get("pen", 1)))
            for p in task["points"]
        ]
        self._reg.total_points = len(points)
        return client.draw(points, timeout=timeout)

    def _get_client(self):
        try:
            client = runtime.get_client()
        except RobotNotConnectedError:
            return None
        return client if client.is_connected else None

    def _enqueue(self, task: dict) -> dict:
        self._tasks.put(task)
        return {"status": "ok", "queued": self._tasks.qsize()}

    def _fail(self, message: str) -> None:
        self._reg.state = "failed"
        self._reg.busy = False
        self._reg.last_error = message
        self._ctx.log_error(f"RobotDrawPlugin: {message}")
        self._publish_state()

    def _publish_state(self) -> None:
        if self._ctx.state_proxy is not None:
            self._ctx.state_proxy.merge(
                "robot/draw",
                {
                    "state": self._reg.state,
                    "busy": self._reg.busy,
                    "progress_point": self._reg.progress_point,
                    "total_points": self._reg.total_points,
                    "draws_done": self._reg.draws_done,
                },
            )

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — кладут задание и возвращаются СРАЗУ
    # ------------------------------------------------------------------ #

    def cmd_draw_points(self, data: dict) -> dict:
        """Полилиния: {points: [{x_mm,y_mm,pen}], z?: высота рисования}."""
        points = data.get("points")
        if not isinstance(points, list) or not points:
            return {"status": "error", "message": "нужно: {points: [{x_mm, y_mm, pen}]}"}
        return self._enqueue({"kind": "points", "points": points, "z": data.get("z")})

    def cmd_draw_circle(self, data: dict) -> dict:
        """Круг родным MCircle: {cx, cy, r, z?}."""
        try:
            task = {
                "kind": "circle",
                "cx": float(data["cx"]),
                "cy": float(data["cy"]),
                "r": float(data["r"]),
                "z": data.get("z"),
            }
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {cx, cy, r: float}"}
        return self._enqueue(task)

    def cmd_draw_square(self, data: dict) -> dict:
        """Прямоугольник по углам ЛВ и ПН: {x1, y1, x2, y2, z?}."""
        try:
            points = gen_rect(float(data["x1"]), float(data["y1"]), float(data["x2"]), float(data["y2"]))
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {x1, y1, x2, y2: float}"}
        return self._enqueue({"kind": "points", "points": points, "z": data.get("z")})

    def cmd_set_pen(self, data: dict) -> dict:
        """Высоты пера: {down, up} (мм). Применяется к следующей фигуре."""
        try:
            self._reg.pen_down_mm = float(data["down"])
            self._reg.pen_up_mm = float(data["up"])
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {down, up: float}"}
        return {"status": "ok", "down": self._reg.pen_down_mm, "up": self._reg.pen_up_mm}

    def cmd_set_draw_speed(self, data: dict) -> dict:
        """Скорость рисования: {pct: 1..100}."""
        try:
            self._reg.draw_speed_pct = max(1, min(100, int(data["pct"])))
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {pct: int}"}
        return {"status": "ok", "pct": self._reg.draw_speed_pct}

    def cmd_set_overlap(self, data: dict) -> dict:
        """Скругление углов: {mm: float}."""
        try:
            self._reg.overlap_mm = max(0.1, float(data["mm"]))
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {mm: float}"}
        return {"status": "ok", "mm": self._reg.overlap_mm}

    def cmd_abort_draw(self, _data: dict) -> dict:
        """Прервать рисование НЕМЕДЛЕННО (минуя очередь — транзакция thread-safe)."""
        client = runtime.peek_client()
        if client is None or not client.is_connected:
            return {"status": "error", "message": "клиент робота недоступен"}
        try:
            client.draw_abort()
        except ModbusDriverError as exc:
            return {"status": "error", "message": str(exc)}
        # выкинуть невыполненные задания
        dropped = 0
        while not self._tasks.empty():
            try:
                self._tasks.get_nowait()
                dropped += 1
            except queue.Empty:  # pragma: no cover - гонка опустошения
                break
        return {"status": "ok", "dropped_tasks": dropped}

    def cmd_get_draw_progress(self, _data: dict) -> dict:
        """Прогресс: состояние исполнителя + живые busy/prog с робота."""
        result: dict[str, Any] = {
            "status": "ok",
            "state": self._reg.state,
            "total_points": self._reg.total_points,
            "draws_done": self._reg.draws_done,
            "queued": self._tasks.qsize(),
        }
        client = runtime.peek_client()
        if client is not None and client.is_connected:
            try:
                result["busy"] = client.draw_busy()
                result["progress_point"] = client.draw_progress()
                self._reg.busy = bool(result["busy"])
                self._reg.progress_point = int(result["progress_point"])
            except ModbusDriverError as exc:
                result["read_error"] = str(exc)
        return result
