"""DrawingIoPlugin — сохранение карты точек рисунка в файл и загрузка обратно.

Запрос владельца: сохранить полученный рисунок (карту точек, опц. с кадром) в файл,
потом выбрать файл и загрузить — и рисовать снова, ничего не теряя.

- ``drawing_save`` (команда/кнопка пульта): снимает текущие draw_points (мм) + границы
  листа + кадр-референс и пишет ``drawings/<ts>.json`` (+ ``.png``). Armed-on-command,
  как RobotDrawPlugin.cmd_send — снимок согласован (точки+кадр из одного кадра).
- ``drawing_load``: читает JSON, ставит load_active — плагин ПОДМЕНЯЕТ draw_points в
  каждом кадре, пока load_active не снят (превью и робот рисуют загруженное). Пустой
  путь → снять load_active (вернуться к живым точкам).

Стоит в процессе points ПОСЛЕ robot_scale, ДО points_render/robot_draw: на сохранении
видит точки в мм, на загрузке подменяет их для превью и робота.
"""

from __future__ import annotations

import os
import time

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from . import store
from .registers import DrawingIoRegisters


@register_plugin(
    "drawing_io",
    category="io",
    description="Сохранение/загрузка карты точек рисунка (JSON + PNG)",
)
class DrawingIoPlugin(ProcessModulePlugin):
    """draw_points ↔ файл: сохранить снимок, загрузить и подменить для рисования."""

    name = "drawing_io"
    category = "io"
    thread_safe = False

    inputs = [
        Port(name="draw_points", dtype="list[dict]", shape="N", optional=True, description="[{x_mm,y_mm,pen}] (мм)"),
        Port(name="draw_bounds", dtype="list[float]", shape="4", optional=True, description="границы листа"),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр-референс (проброс)"),
    ]
    outputs = [
        Port(
            name="draw_points", dtype="list[dict]", shape="N", optional=True, description="точки (подмена при загрузке)"
        ),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (проброс)"),
    ]

    commands = {"drawing_save": "cmd_save", "drawing_load": "cmd_load"}
    register_class = DrawingIoRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import DrawingIoPluginConfig

        return DrawingIoPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: DrawingIoRegisters = self._init_register(ctx)
        self._save_armed = False
        self._loaded_points: list[dict] = []
        self._loaded_bounds: list[float] | None = None
        ctx.log_info(f"DrawingIoPlugin: dir={self._reg.drawings_dir!r}")

    # ------------------------------------------------------------------ #
    # КОМАНДЫ
    # ------------------------------------------------------------------ #

    def cmd_save(self, _data: dict) -> dict:
        """Кнопка «Сохранить»: снять текущий рисунок в файл (на ближайшем кадре)."""
        self._save_armed = True
        self._ctx.log_info("DrawingIoPlugin: armed save — сохраню текущий рисунок")
        return {"status": "ok", "armed": True}

    def cmd_load(self, data: dict) -> dict:
        """Кнопка «Загрузить»: прочитать JSON и включить подмену. Пустой путь → выключить."""
        path = str(data.get("path") or data.get("name") or "").strip()
        if not path:
            self._reg.load_active = False
            self._loaded_points = []
            self._loaded_bounds = None
            self._ctx.log_info("DrawingIoPlugin: загрузка снята (живые точки)")
            return {"status": "ok", "load_active": False}
        full = path if path.endswith(".json") else path + ".json"
        if not os.path.isabs(full):
            full = os.path.join(self._reg.drawings_dir, full)
        try:
            points, bounds, _meta, _img = store.load(full)
        except Exception as exc:  # noqa: BLE001 — ошибку отдаём в результат команды
            self._ctx.log_error(f"DrawingIoPlugin: не удалось загрузить {full}: {exc}")
            return {"status": "error", "message": str(exc)}
        self._loaded_points = points
        self._loaded_bounds = bounds
        self._reg.load_active = True
        self._reg.loaded_path = full
        self._reg.loaded_points = len(points)
        self._ctx.log_info(f"DrawingIoPlugin: загружено {len(points)} точек из {full}")
        return {"status": "ok", "load_active": True, "points": len(points)}

    # ------------------------------------------------------------------ #
    # PROCESS — подмена при загрузке + снимок при сохранении
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for item in items:
            # Загрузка активна → подменяем точки (превью и робот рисуют загруженное).
            if self._reg.load_active and self._loaded_points:
                # Загруженные точки — АБСОЛЮТНЫЕ мм. Лист физически там, где задаёт текущий
                # robot_scale (его draw_bounds в item). drawing_io стоит ПОСЛЕ robot_scale,
                # поэтому прижимаем загруженное к ТЕКУЩЕМУ листу (минует clamp_to_zone) —
                # точка за зоной ляжет на границу (защита от рисования мимо бумаги). Границы
                # оставляем текущие (превью совпадает с физлистом); если их нет — берём из файла.
                cur_bounds = item.get(self._reg.bounds_source)
                has_cur = isinstance(cur_bounds, list) and len(cur_bounds) == 4
                use_bounds = cur_bounds if has_cur else self._loaded_bounds
                pts = self._clamp_to_bounds(self._loaded_points, use_bounds)
                item = {**item, self._reg.points_source: pts}
                if not has_cur and self._loaded_bounds is not None:
                    item[self._reg.bounds_source] = list(self._loaded_bounds)

            if self._save_armed:
                self._do_save(item)
                self._save_armed = False
            out.append(item)
        return out

    @staticmethod
    def _clamp_to_bounds(points: list[dict], bounds) -> list[dict]:
        """Прижать точки к прямоугольнику листа bounds=[x0,y0,x1,y1] (если задан)."""
        if not (isinstance(bounds, list) and len(bounds) == 4):
            return list(points)
        x0, y0, x1, y1 = (float(v) for v in bounds)
        xlo, xhi = (x0, x1) if x0 <= x1 else (x1, x0)
        ylo, yhi = (y0, y1) if y0 <= y1 else (y1, y0)
        out: list[dict] = []
        for p in points:
            out.append(
                {
                    "x_mm": min(xhi, max(xlo, float(p["x_mm"]))),
                    "y_mm": min(yhi, max(ylo, float(p["y_mm"]))),
                    "pen": int(p.get("pen", 1)),
                }
            )
        return out

    def _do_save(self, item: dict) -> None:
        pts = item.get(self._reg.points_source)
        if not isinstance(pts, list) or not pts:
            self._ctx.log_error("DrawingIoPlugin: нет точек для сохранения")
            return
        bounds = item.get(self._reg.bounds_source)
        frame = item.get("frame") if self._reg.save_image else None
        meta = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "points": len(pts)}
        # Суффикс счётчика → два сохранения в одну секунду не затирают друг друга.
        stem = time.strftime("%Y%m%d_%H%M%S") + f"_{int(self._reg.saves_done):03d}"
        try:
            path = store.save(
                self._reg.drawings_dir,
                stem,
                pts,
                bounds=bounds if isinstance(bounds, list) else None,
                meta=meta,
                image_bgr=frame,
            )
        except Exception as exc:  # noqa: BLE001 — сохранение не должно ронять pipeline
            self._ctx.log_error(f"DrawingIoPlugin: ошибка сохранения: {exc}")
            return
        self._reg.last_saved = path
        self._reg.saves_done += 1
        self._ctx.log_info(f"DrawingIoPlugin: сохранено {len(pts)} точек → {path}")
