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

import os
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
# Буфер робота на один проход (= PTS_MAX / DEFAULT_PASS_LIMIT). Путь длиннее робот
# рисует несколькими проходами с подъёмом пера и заездом домой между ними — это
# отражается в предпросмотре (границы проходов). Полный рисунок при этом сохраняется.
_PASS_LIMIT = 100


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

            # Пробный прогон: пишем точки в текст и НЕ трогаем робот (проверка перед боем).
            if self._reg.dry_run:
                self._preview_points(points)
                self._armed = False
                break

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
    # ПРОБНЫЙ ПРОГОН — предпросмотр точек в тексте (роботу не отправляем)
    # ------------------------------------------------------------------ #

    def _preview_points(self, points: list[dict]) -> None:
        """dry_run: записать точки в текст + краткая сводка в лог, роботу не слать."""
        try:
            path = self._dump_points(points)
        except Exception as exc:  # noqa: BLE001 — превью не должно валить pipeline
            self._ctx.log_error(f"RobotDrawPlugin: не удалось записать предпросмотр точек: {exc}")
            return
        n = len(points)
        xs = [p["x_mm"] for p in points]
        ys = [p["y_mm"] for p in points]
        passes = self._count_passes(points)
        self._ctx.log_info(
            f"RobotDrawPlugin: ПРОБНЫЙ ПРОГОН — {n} точек, проходов={passes}, "
            f"X {min(xs):.1f}..{max(xs):.1f} мм, Y {min(ys):.1f}..{max(ys):.1f} мм → {path} "
            "(роботу НЕ отправлено)"
        )

    @staticmethod
    def _to_draw_points(points: list[dict]) -> list[Any]:
        """dict-точки → DrawPoint (для split_draw_passes — точные границы проходов)."""
        from Services.robot_comm.core.datatypes import DrawPoint

        return [DrawPoint(float(p["x_mm"]), float(p["y_mm"]), int(p.get("pen", 1))) for p in points]

    def _count_passes(self, points: list[dict]) -> int:
        """Сколько проходов ≤ _PASS_LIMIT (резка по штрихам, как у RobotClient.draw)."""
        from Services.robot_comm.core.datatypes import split_draw_passes

        return len(split_draw_passes(self._to_draw_points(points), _PASS_LIMIT))

    def _dump_points(self, points: list[dict]) -> str:
        """Записать точки в текстовый файл dump_path (мм + перо + рег 0.1мм + проходы).

        Границы проходов считаются той же split_draw_passes, что и при реальной отправке —
        предпросмотр показывает, где робот поднимет перо и заедет домой. Возвращает путь.
        """
        from Services.robot_comm.core.datatypes import split_draw_passes

        path = self._reg.dump_path or "robot_points_preview.txt"
        passes = split_draw_passes(self._to_draw_points(points), _PASS_LIMIT)
        n = len(points)
        pen_ups = sum(1 for p in points if int(p.get("pen", 1)) == 0)
        xs = [p["x_mm"] for p in points]
        ys = [p["y_mm"] for p in points]
        out = [
            f"# Робот {self._reg.device_id}: предпросмотр точек рисования ({time.strftime('%Y-%m-%d %H:%M:%S')})",
            f"# Всего точек: {n} | подводов (pen=0): {pen_ups} | проходов по {_PASS_LIMIT}: {len(passes)}",
            f"# Диапазон X(мм): {min(xs):.1f}..{max(xs):.1f}   Y(мм): {min(ys):.1f}..{max(ys):.1f}",
            "# pen: 0 = подвод/перемещение (перо ВВЕРХ), 1 = рисование (перо ВНИЗ)",
            "# [рег] = что реально уходит роботу (0.1 мм, целое s16)",
            f"# {'idx':>4} {'x_mm':>9} {'y_mm':>9}  pen   [рег x10  y10]",
        ]
        idx = 0
        for pi, batch in enumerate(passes, start=1):
            if pi > 1:
                out.append(f"# --- ПРОХОД {pi}: перо ВВЕРХ + заезд ДОМОЙ, дальше новый проход ---")
            for p in batch:
                x, y, pen = float(p.x_mm), float(p.y_mm), int(p.pen)
                out.append(f"  {idx:>4} {x:>9.2f} {y:>9.2f}   {pen}    [{round(x * 10):>6} {round(y * 10):>6}]")
                idx += 1
        text = "\n".join(out) + "\n"
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

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
