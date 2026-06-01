"""ContourDrawPlugin — рисует контур вокруг найденного цвета (атомарный плагин).

Вход: item["frame"] (оригинальный кадр) + item["contours"] (от contour_finder).
Выход: item["frame"] с нарисованными контурами (на КОПИИ — оригинал не мутируем).
Если контуров нет — кадр без изменений (pass-through). Цвет/толщина — слайдеры.

Декомпозиция (по модели владельца): детектор отдаёт массив контуров, отдельный
draw-плагин получает картинку+массив и рисует → дальше в дисплей.
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

from .registers import ContourDrawRegisters


@register_plugin("contour_draw", category="rendering", description="Рисует линию контура вокруг найденного цвета")
class ContourDrawPlugin(ProcessModulePlugin):
    """frame + contours → frame с нарисованной линией контура."""

    name = "contour_draw"
    category = "rendering"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной кадр"),
        Port(name="contours", dtype="list[ndarray]", shape="N", description="Контуры для отрисовки"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр с контуром"),
    ]

    commands = {}
    register_class = ContourDrawRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import ContourDrawPluginConfig

        return ContourDrawPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: ContourDrawRegisters = self._init_register(ctx)
        ctx.log_info(
            f"ContourDrawPlugin: color BGR=({self._reg.color_b},{self._reg.color_g},{self._reg.color_r}), "
            f"thickness={self._reg.thickness}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        """Нарисовать контуры на копии кадра. Без контуров — pass-through."""
        frame = item.get("frame")
        if frame is None:
            return None
        contours = item.get("contours")
        if not contours:
            return item  # нечего рисовать

        r = self._reg
        color = (int(r.color_b), int(r.color_g), int(r.color_r))
        canvas = frame.copy()  # не мутируем оригинал (он мог уйти в SHM/другим потребителям)
        cv2.drawContours(canvas, list(contours), -1, color, int(r.thickness))
        return {**item, "frame": canvas}
