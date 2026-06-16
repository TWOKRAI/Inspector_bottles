"""PixelToRobotPlugin — px → мм робота по гомографии калибровки (позиция ЗАБОРА).

Недостающее runtime-звено калибровки: визард ``camera_robot_calibration`` делает
``config/calibration/<camera_id>.yaml`` (гомография 3×3), а этот узел ПРИМЕНЯЕТ её в
потоке — переводит пиксельный центр диска (тот, что пересёк линию; ``sidecar.center_px``
от ``center_crop``) в координаты робота (мм). Это позиция забора с ленты для
``word_layout`` → ``robot_io.enqueue_job``.

Гомография ROI-локальна (см. план): детектор узла и калибровки ОБЯЗАНЫ работать в одном
ROI, иначе координаты смещены. При разных ROI — ``roi_offset_x/y`` приводит px к системе
калибровки.

Энкодер (для CVT-трекинга по ленте) узел НЕ читает — чтобы не стучать по Modbus. Его
читает один раз на задание драйвер в ``enqueue_job`` (девайс-сторона), и только когда
робот подключён. Пробег ленты до пикинга компенсирует CVT-трекинг прошивки.

Вход:  ``sidecar.center_px`` (или ``center_px``) = [x, y] px ROI; кадр — pass-through.
Выход: ``pick_xy`` = {x_mm, y_mm} в мм робота.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import PixelToRobotRegisters


@register_plugin(
    "pixel_to_robot",
    category="processing",
    description="Калибровка px→мм робота: гомография к центру диска → позиция забора {x_mm,y_mm}",
)
class PixelToRobotPlugin(ProcessModulePlugin):
    """center_px (px ROI) → pick_xy (мм робота) по гомографии cam0.yaml."""

    name = "pixel_to_robot"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (pass-through)"),
    ]
    outputs = [
        Port(name="pick_xy", dtype="dict", optional=True, description="{x_mm, y_mm} — позиция забора в мм робота"),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (pass-through)"),
    ]

    commands = {"reload_calibration": "cmd_reload"}
    register_class = PixelToRobotRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import PixelToRobotPluginConfig

        return PixelToRobotPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: PixelToRobotRegisters = self._init_register(ctx)
        self._h = None  # np.ndarray 3×3 или None
        self._load_calibration()

    def cmd_reload(self, _data: dict) -> dict:
        """Перечитать файл калибровки (после прогона визарда, без рестарта рецепта)."""
        self._load_calibration()
        return {"status": "ok", "loaded": self._reg.loaded}

    def _load_calibration(self) -> None:
        """Загрузить гомографию из config/calibration/<camera_id>.yaml в numpy-матрицу."""
        import numpy as np

        from Plugins.calibration.camera_robot.store import load_calibration

        self._h = None
        self._reg.loaded = False
        try:
            payload = load_calibration(self._reg.camera_id, self._reg.calibration_dir)
        except Exception as exc:  # noqa: BLE001 — кривой файл не должен валить процесс
            self._reg.last_error = f"load: {exc}"
            self._ctx.log_error(f"PixelToRobotPlugin: ошибка чтения калибровки: {exc}")
            return
        if not payload or "px_to_mm" not in payload:
            self._reg.last_error = f"нет калибровки '{self._reg.camera_id}' в {self._reg.calibration_dir}"
            self._ctx.log_info(
                f"PixelToRobotPlugin: калибровка '{self._reg.camera_id}' не найдена — pick_xy не выдаётся "
                f"(прогони визард camera_robot_calibration)"
            )
            return
        self._h = np.asarray(payload["px_to_mm"], dtype=float)
        self._reg.loaded = True
        self._reg.last_error = ""
        self._ctx.log_info(f"PixelToRobotPlugin: калибровка '{self._reg.camera_id}' загружена (гомография 3×3)")

    # ------------------------------------------------------------------ #
    # PROCESS
    # ------------------------------------------------------------------ #

    @for_each
    def process(self, item: dict) -> dict | None:
        if self._h is None:
            return item
        center = self._extract_center(item)
        if center is None:
            return item

        from Plugins.calibration.camera_robot.geometry import apply_homography

        px = (center[0] + self._reg.roi_offset_x, center[1] + self._reg.roi_offset_y)
        try:
            x_mm, y_mm = apply_homography(self._h, px)
        except Exception as exc:  # noqa: BLE001 — точка вне области гомографии и т.п.
            self._reg.last_error = f"apply: {exc}"
            return item

        self._reg.last_x_mm = round(x_mm, 2)
        self._reg.last_y_mm = round(y_mm, 2)
        self._reg.conversions += 1
        return {**item, self._reg.output_key: {"x_mm": x_mm, "y_mm": y_mm}}

    def _extract_center(self, item: dict) -> tuple[float, float] | None:
        """Достать px-центр диска: item['sidecar'][center_key] → item[center_key]."""
        key = self._reg.center_key
        sidecar = item.get("sidecar")
        raw = None
        if isinstance(sidecar, dict):
            raw = sidecar.get(key)
        if raw is None:
            raw = item.get(key)
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            return float(raw[0]), float(raw[1])
        return None

    def shutdown(self, ctx: PluginContext) -> None:
        self._ctx.log_info(f"PixelToRobotPlugin: shutdown (переводов {self._reg.conversions})")
