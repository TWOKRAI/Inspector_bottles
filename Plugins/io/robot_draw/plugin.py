"""RobotDrawPlugin — приёмник точек рисования в pipeline (sink).

Образец — Plugins/io/robot_io/plugin.py (тонкий форвардер в процесс devices).
Соединением с роботом владеет DeviceHubPlugin. Этот плагин:
1. В process() (НЕ блокирующий) забирает item["draw_points"] (от strokes_to_points)
   и кладёт задание {device_id, points} в локальную очередь.
2. Worker ``draw_forwarder`` (LOOP) шлёт ``robot_draw_polyline`` в hub через
   DeviceHubClient. Драйвер кладёт задание в свою draw-очередь и СРАЗУ отвечает —
   реальное рисование с чанкованием (PTS_MAX=100) идёт асинхронно в devices.

«Сколько получится — столько и передаём»: чанкование точек на проходы делает
RobotClient.draw() внутри devices, здесь шлётся весь путь одним заданием.
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

from Plugins.hub.device_hub.client import DeviceHubClient

from .registers import RobotDrawRegisters

# Поллинг очереди заданий в форвардере, сек.
_FORWARDER_POLL_S = 0.1
# Макс. размер локальной очереди заданий (одно задание = один snapshot).
_QUEUE_MAXSIZE = 8


@register_plugin(
    "robot_draw",
    category="io",
    description="Приёмник точек рисования: pipeline → devices (robot_draw_polyline)",
)
class RobotDrawPlugin(ProcessModulePlugin):
    """draw_points → очередь → robot_draw_polyline в devices (async-рисование)."""

    name = "robot_draw"
    category = "io"
    thread_safe = False

    inputs = [
        Port(
            name="draw_points",
            dtype="list[dict]",
            shape="N",
            optional=True,
            description="[{x_mm, y_mm, pen}] — задание рисования",
        ),
        Port(
            name="trigger",
            dtype="any",
            optional=True,
            description="Сигнал-триггер «Рисовать» (напр. кнопка пульта). Ключ чтения — register trigger_source",
        ),
    ]
    outputs = []  # sink: side-effect к железу, кадр пробрасывается

    commands = {"robot_draw_send": "cmd_send"}
    register_class = RobotDrawRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import RobotDrawPluginConfig

        return RobotDrawPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: RobotDrawRegisters = self._init_register(ctx)
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._client: DeviceHubClient | None = None
        self._last_was_error = False
        # Отправка роботу — ТОЛЬКО по команде (кнопка «Отправить роботу»).
        # strokes_to_points считают точки непрерывно (для карты), но робот
        # рисует лишь когда явно нажали. _armed взводится cmd_send на 1 кадр.
        self._armed = False
        ctx.log_info(f"RobotDrawPlugin: configured (device_id={self._reg.device_id})")

    # ------------------------------------------------------------------ #
    # КОМАНДА — отправить текущие точки роботу (одноразово)
    # ------------------------------------------------------------------ #

    def cmd_send(self, data: dict) -> dict:
        """Кнопка «Отправить роботу»: отправить текущий путь (следующий кадр)."""
        self._armed = True
        self._ctx.log_info("RobotDrawPlugin: armed — отправлю текущие точки роботу")
        return {"status": "ok", "armed": True}

    def start(self, ctx: PluginContext) -> None:
        self._client = DeviceHubClient(ctx)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("draw_forwarder", self._forwarder_loop, cfg, auto_start=True)
        ctx.log_info("RobotDrawPlugin: started (draw_forwarder запущен)")

    def shutdown(self, ctx: PluginContext) -> None:
        self._client = None
        ctx.log_info(
            f"RobotDrawPlugin: shutdown (sent={self._reg.jobs_sent}, "
            f"points={self._reg.points_total}, dropped={self._reg.jobs_dropped})"
        )

    # ------------------------------------------------------------------ #
    # PROCESS — приём заданий из pipeline (pass-through, НЕ блокируется)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        # Pipeline-триггер: сигнал из pipeline (напр. кнопка пульта «Рисовать» на
        # порту out_1, провод out_1 → robot_draw) взводит рисование — как команда
        # robot_draw_send. Ключ trigger_source = имя исходного порта (без переименования).
        # Сигнал и draw_points приходят в РАЗНЫЕ process()-вызовы → _armed взводится
        # на кадре сигнала, путь уходит на ближайшем кадре с draw_points (одноразово).
        trig = self._reg.trigger_source
        if trig:
            for item in items:
                if item.get(trig):
                    if not self._armed:
                        self._ctx.log_info(f"RobotDrawPlugin: pipeline-триггер '{trig}' — armed")
                    self._armed = True
                    break

        # Отправляем ТОЛЬКО когда взведена команда/триггер (одноразово на нажатие).
        if not self._armed:
            return items
        for item in items:
            pts = item.get(self._reg.points_source)
            if not isinstance(pts, list) or not pts:
                continue
            points = [
                {"x_mm": float(p["x_mm"]), "y_mm": float(p["y_mm"]), "pen": int(p.get("pen", 1))}
                for p in pts
                if isinstance(p, dict) and "x_mm" in p and "y_mm" in p
            ]
            if not points:
                continue
            task = {"device_id": self._reg.device_id, "points": points}
            try:
                self._queue.put_nowait(task)
                self._reg.queue_len = self._queue.qsize()
            except queue.Full:
                self._reg.jobs_dropped += 1
                self._ctx.log_error("RobotDrawPlugin: очередь заданий полна, задание отброшено")
            # Одноразово: разоружаемся после первой валидной пачки.
            self._armed = False
            break
        return items

    # ------------------------------------------------------------------ #
    # FORWARDER (worker) — IPC-мост в процесс devices
    # ------------------------------------------------------------------ #

    def _forwarder_loop(self, stop_event: Any, pause_event: Any) -> None:
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(_FORWARDER_POLL_S)
                continue
            try:
                task = self._queue.get(timeout=_FORWARDER_POLL_S)
            except queue.Empty:
                continue

            self._reg.queue_len = self._queue.qsize()
            if self._client is None:
                self._reg.jobs_dropped += 1
                continue

            n = len(task["points"])
            try:
                result = self._client.request(
                    "robot_draw_polyline",
                    task,
                    timeout=float(self._reg.request_timeout_s),
                )
            except Exception as exc:
                self._reg.jobs_dropped += 1
                self._reg.hub_errors += 1
                self._reg.last_error = str(exc)
                if not self._last_was_error:
                    self._ctx.log_error(f"RobotDrawPlugin: hub ошибка: {exc}")
                    self._last_was_error = True
                continue

            if result.get("status") == "ok":
                self._reg.jobs_sent += 1
                self._reg.points_total += n
                if self._last_was_error:
                    self._ctx.log_info("RobotDrawPlugin: hub восстановлен")
                    self._last_was_error = False
                self._ctx.log_info(f"RobotDrawPlugin: задание отправлено ({n} точек) → {result}")
            else:
                self._reg.jobs_dropped += 1
                self._reg.hub_errors += 1
                self._reg.last_error = result.get("message", "неизвестная ошибка hub")
                if not self._last_was_error:
                    self._ctx.log_error(f"RobotDrawPlugin: hub отказ: {self._reg.last_error}")
                    self._last_was_error = True
