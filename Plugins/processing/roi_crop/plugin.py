"""RoiCropPlugin -- вырез одного прямоугольного ROI скалярными live-полями.

Processing-плагин (1→1): frame → frame[y:y+h, x:x+w]. В отличие от region_split
(мультирегион, fan-out, параметры списком в config — НЕ live), здесь один ROI
скалярными register-полями x/y/width/height — нормальные числовые поля в инспекторе,
применяются НА ЛЕТУ (читаются из self._reg каждый кадр).

width/height = 0 → до правого/нижнего края кадра. Границы клампятся (не падаем при OOB).
В item кладём roi_x/roi_y (смещение ROI в полном кадре) — для downstream, если нужно.

Stateless → thread_safe=True.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import RoiCropRegisters


@register_plugin("roi_crop", category="processing", description="Вырез одного ROI (live x/y/width/height)")
class RoiCropPlugin(ProcessModulePlugin):
    """frame → один прямоугольный ROI (скалярные live-поля x/y/width/height)."""

    name = "roi_crop"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(h, w, 3)", description="Вырезанный ROI"),
    ]

    register_class = RoiCropRegisters

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: RoiCropRegisters = self._init_register(ctx)
        self._last_log_key: tuple | None = None  # диагностика: лог только при смене ROI/кадра
        ctx.log_info(f"RoiCropPlugin: ROI x={self._reg.x}, y={self._reg.y}, w={self._reg.width}, h={self._reg.height}")

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None:
            return None

        h, w = frame.shape[:2]
        # Скалярные параметры читаем КАЖДЫЙ кадр → live-тюнинг применяется сразу.
        x0 = max(0, min(int(self._reg.x), w - 1))
        y0 = max(0, min(int(self._reg.y), h - 1))
        rw = int(self._reg.width)
        rh = int(self._reg.height)
        x1 = w if rw <= 0 else min(x0 + rw, w)
        y1 = h if rh <= 0 else min(y0 + rh, h)

        # ДИАГНОСТИКА (throttled — лог только при смене кадра/ROI): видеть реальные числа.
        # Помогает поймать «801 → полный кадр»: покажет, что реально приходит в reg и кадр.
        log_key = (w, h, rw, rh, x0, y0)
        if log_key != self._last_log_key:
            self._last_log_key = log_key
            self._ctx.log_info(
                f"RoiCrop diag: frame={w}x{h} reg(x={self._reg.x},y={self._reg.y},"
                f"w={rw},h={rh}) -> crop x[{x0}:{x1}] y[{y0}:{y1}] = {x1 - x0}x{y1 - y0}"
            )

        if x1 <= x0 or y1 <= y0:
            return None  # вырожденный ROI — нечего отдавать

        crop = frame[y0:y1, x0:x1].copy()  # copy: отвязать от SHM-буфера
        return {**item, "frame": crop, "roi_x": x0, "roi_y": y0}
