"""BlobFilterPlugin — очистка бинарной маски линий от шумовых blob'ов.

Порт логики из projects_obsidian/sketch_robot/modules/blob_filter.py. Через
connected components находит связные белые области, измеряет площадь и стирает
те, что не проходят фильтр. В отличие от contour_filter — НЕ перерисовывает
контуры, а сохраняет оригинальные пиксели (толстые линии TEED остаются толстыми).

Ставится ПОСЛЕ edge_detection и ПЕРЕД strokes_to_points.

Вход: item["mask"] (бинарь 0/255). Выход: очищенный mask + перерисованный
frame (BGR-рендер маски) для дисплея.
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

from .registers import BlobFilterRegisters


@register_plugin(
    "blob_filter",
    category="processing",
    description="Удалить мелкие/крупные blob'ы по площади (connected components)",
)
class BlobFilterPlugin(ProcessModulePlugin):
    """mask → connectedComponentsWithStats → фильтр по площади → mask + frame."""

    name = "blob_filter"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска линий"),
    ]
    outputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Очищенная маска"),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-рендер очищенной маски"),
    ]

    commands: dict[str, str] = {}
    register_class = BlobFilterRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import BlobFilterPluginConfig

        return BlobFilterPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: BlobFilterRegisters = self._init_register(ctx)
        ctx.log_info(f"BlobFilterPlugin: area=[{self._reg.min_area}, {self._reg.max_area}]")

    @for_each
    def process(self, item: dict) -> dict | None:
        mask = item.get("mask")
        if mask is None:
            return item

        min_area = int(self._reg.min_area)
        max_area = int(self._reg.max_area)

        # Connected components: каждая связная белая область получает label.
        # stats[:, CC_STAT_AREA] = площадь (число пикселей). label 0 = фон.
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        result = mask.copy()
        for label_id in range(1, num_labels):
            area = int(stats[label_id, cv2.CC_STAT_AREA])
            if area < min_area or (max_area > 0 and area > max_area):
                result[labels == label_id] = 0

        line_bgr = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
        return {**item, "mask": result, "frame": line_bgr}
