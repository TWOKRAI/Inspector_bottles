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
import numpy as np

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
        mode = (self._reg.mode or "resize").lower()

        # Нечего делать (только resize): регион = весь кадр и выход = входу.
        if mode != "clip" and x == 0 and y == 0 and w == w_in and h == h_in and out_w == w_in and out_h == h_in:
            self._reg.last_w, self._reg.last_h = w_in, h_in
            return item

        region = frame[y : y + h, x : x + w]
        self._reg.last_w, self._reg.last_h = w, h

        if mode == "clip":
            # Обрезка БЕЗ масштаба: регион в нативном размере кладём на фикс. холст out_w×out_h
            # по (paste_x, paste_y); выход за край холста отсекается («точка ставится на краю»).
            return {**item, "frame": self._paste_clip(region, out_w, out_h)}

        # resize-режим: вырезать + растянуть к выходному размеру (старое поведение).
        if (w, h) != (out_w, out_h):
            region = cv2.resize(region, (out_w, out_h), interpolation=cv2.INTER_AREA)
        return {**item, "frame": region}

    def _paste_clip(self, region, out_w: int, out_h: int):
        """Вставить регион в нативном масштабе на белый холст out_w×out_h по paste_x/y (clip).

        Прямоугольник вставки пересекается с холстом — часть за краем отсекается (не
        ресайзится). Белый фон = соглашение тракта (segmentation bg_white).
        """
        rh, rw = int(region.shape[0]), int(region.shape[1])
        if region.ndim == 3:
            canvas = np.full((out_h, out_w, region.shape[2]), 255, dtype=region.dtype)
        else:
            canvas = np.full((out_h, out_w), 255, dtype=region.dtype)
        px0, py0 = int(self._reg.paste_x), int(self._reg.paste_y)
        # Пересечение [px0..px0+rw]×[py0..py0+rh] с холстом [0..out_w]×[0..out_h].
        dst_x0, dst_y0 = max(0, px0), max(0, py0)
        dst_x1, dst_y1 = min(out_w, px0 + rw), min(out_h, py0 + rh)
        if dst_x1 > dst_x0 and dst_y1 > dst_y0:
            sx0, sy0 = dst_x0 - px0, dst_y0 - py0
            canvas[dst_y0:dst_y1, dst_x0:dst_x1] = region[sy0 : sy0 + (dst_y1 - dst_y0), sx0 : sx0 + (dst_x1 - dst_x0)]
        return canvas
