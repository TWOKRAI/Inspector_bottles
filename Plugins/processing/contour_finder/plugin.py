"""ContourFinderPlugin — контуры и площадь по бинарной маске (атомарный плагин).

Вход: item["mask"] (от hsv_mask). Выход: item["detections"] (bbox/center/area) +
item["contours"] (list np-arrays для рисования). item["mask"] ДРОПАЕТСЯ — картинка-маска
не нужна дальше и не должна гоняться по IPC. Кадр (item["frame"]) пробрасывается.

Не рисует — рисование вынесено в отдельный плагин contour_draw (модульность).
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

from .registers import ContourFinderRegisters


@register_plugin("contour_finder", category="processing", description="Контуры и площадь по бинарной маске")
class ContourFinderPlugin(ProcessModulePlugin):
    """mask → findContours → фильтр по площади → detections + contours."""

    name = "contour_finder"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска"),
    ]
    outputs = [
        Port(name="detections", dtype="list[dict]", shape="N", description="Детекции (bbox, center, area)"),
        Port(name="contours", dtype="list[ndarray]", shape="N", description="Контуры для рисования"),
    ]

    commands = {}
    register_class = ContourFinderRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import ContourFinderPluginConfig

        return ContourFinderPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: ContourFinderRegisters = self._init_register(ctx)
        ctx.log_info(f"ContourFinderPlugin: area=[{self._reg.min_area}, {self._reg.max_area}]")

    @for_each
    def process(self, item: dict) -> dict | None:
        """Найти контуры на маске, отфильтровать по площади, собрать detections."""
        mask = item.get("mask")
        if mask is None:
            return item  # маски нет — нечего искать, пробрасываем как есть

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: list[dict] = []
        filtered: list = []
        min_area = self._reg.min_area
        max_area = self._reg.max_area
        for c in contours:
            area = int(cv2.contourArea(c))
            if area < min_area:
                continue
            if max_area > 0 and area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            detections.append(
                {
                    "bbox": [int(x), int(y), int(x + w), int(y + h)],
                    "center": [int(x + w // 2), int(y + h // 2)],
                    "area": area,
                }
            )
            filtered.append(c)

        out = {**item, "detections": detections, "contours": filtered}
        out.pop("mask", None)  # маска дальше не нужна — не гоняем по IPC
        return out
