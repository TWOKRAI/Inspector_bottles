"""CropPlugin — обрезка кадра по прямоугольнику [x,y,w,h] + resize к выходному размеру.

Зачем: выбрать регион источника (убрать лишние края, «приблизить» лицо), при этом
размер выходного кадра остаётся постоянным (по умолчанию = размер входа), чтобы
дальнейший тракт (edge_detection → strokes_to_points → robot_scale) работал со
стабильным пиксельным диапазоном. Меняя crop_x/crop_y — «двигаешь окно» по
источнику; crop_w/crop_h — масштаб (зум). Поля live-tunable → пульт-дашборд.

Всё ноль → проброс кадра без изменений.
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import CropRegisters


@register_plugin(
    "crop",
    category="processing",
    description="Обрезка кадра по прямоугольнику [x,y,w,h] + resize (выбор региона источника)",
)
class CropPlugin(ProcessModulePlugin):
    """frame → frame: вырезать регион и привести к выходному размеру."""

    name = "crop"
    category = "processing"
    thread_safe = True

    inputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Исходный кадр")]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Обрезанный кадр")]

    commands: dict[str, str] = {}
    register_class = CropRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import CropPluginConfig

        return CropPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: CropRegisters = self._init_register(ctx)
        ctx.log_info(
            f"CropPlugin: регион ({self._reg.crop_x},{self._reg.crop_y}) "
            f"{self._reg.crop_w}x{self._reg.crop_h} → out {self._reg.out_width}x{self._reg.out_height}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None or not hasattr(frame, "shape") or len(getattr(frame, "shape", ())) < 2:
            return item

        h_in, w_in = int(frame.shape[0]), int(frame.shape[1])
        x = max(0, min(int(self._reg.crop_x), w_in - 1))
        y = max(0, min(int(self._reg.crop_y), h_in - 1))
        cw = int(self._reg.crop_w)
        ch = int(self._reg.crop_h)
        w = (w_in - x) if cw <= 0 else min(cw, w_in - x)
        h = (h_in - y) if ch <= 0 else min(ch, h_in - y)
        w = max(1, w)
        h = max(1, h)

        out_w = int(self._reg.out_width) or w_in
        out_h = int(self._reg.out_height) or h_in

        # Нечего делать: регион = весь кадр и выход = входу.
        if x == 0 and y == 0 and w == w_in and h == h_in and out_w == w_in and out_h == h_in:
            self._reg.last_w, self._reg.last_h = w_in, h_in
            return item

        region = frame[y : y + h, x : x + w]
        if (w, h) != (out_w, out_h):
            region = cv2.resize(region, (out_w, out_h), interpolation=cv2.INTER_AREA)
        self._reg.last_w, self._reg.last_h = w, h
        return {**item, "frame": region}
