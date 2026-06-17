"""TextVectorPlugin — генератор однолинейных штрихов текста/сердца в draw_points.

Зачем: рисовать роботом текст (имя, слово) и сердце ОДНОЙ линией (Hershey-стиль) —
чисто, без потери точек, с точными масштабом/поворотом/позицией. Отдаёт draw_points В
ПИКСЕЛЯХ (как strokes_to_points) → дальше robot_scale/points_render/robot_draw общие.

Несколько элементов = несколько экземпляров плагина в цепочке (merge=True накапливает):
портрет + основной текст + имя ниже + сердце. enabled=False → проброс входа.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from . import geometry
from .registers import TextVectorRegisters


@register_plugin(
    "text_vector",
    category="processing",
    description="Векторный однолинейный текст/сердце → draw_points (Hershey-стиль, в пикселях)",
)
class TextVectorPlugin(ProcessModulePlugin):
    """text/heart → draw_points (px): раскладка + матрица 2×2, накопление или замена."""

    name = "text_vector"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(
            name="draw_points",
            dtype="list[dict]",
            shape="N",
            optional=True,
            description="[{x_mm,y_mm,pen}] вход (для merge с фото/др. элементами)",
        ),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (проброс)"),
    ]
    outputs = [
        Port(
            name="draw_points",
            dtype="list[dict]",
            shape="N",
            optional=True,
            description="[{x_mm,y_mm,pen}] (пиксели) — элемент + (опц.) вход",
        ),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (проброс)"),
    ]

    commands: dict[str, str] = {}
    register_class = TextVectorRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import TextVectorPluginConfig

        return TextVectorPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: TextVectorRegisters = self._init_register(ctx)
        ctx.log_info(
            f"TextVectorPlugin: element={self._reg.element} text={self._reg.text!r} "
            f"size={self._reg.size_px}px enabled={self._reg.enabled}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        key = self._reg.points_source
        if not self._reg.enabled:
            return item

        pts, skipped = geometry.build_element(
            element=(self._reg.element or "text").lower(),
            text=self._reg.text or "",
            size_px=float(self._reg.size_px),
            tracking_px=float(self._reg.tracking_px),
            scale=float(self._reg.scale),
            rotation_deg=float(self._reg.rotation_deg),
            pos_x=float(self._reg.pos_x),
            pos_y=float(self._reg.pos_y),
        )
        if skipped:
            uniq = "".join(dict.fromkeys(skipped))
            self._reg.skipped_last = uniq
            self._ctx.log_info(f"TextVectorPlugin: символы не в шрифте, пропущены: {uniq!r}")
        else:
            self._reg.skipped_last = ""

        incoming = item.get(key)
        incoming = incoming if isinstance(incoming, list) else []
        out = ([*incoming, *pts]) if self._reg.merge else pts
        self._reg.points_last = len(pts)
        return {**item, key: out}
