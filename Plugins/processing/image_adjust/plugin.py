"""ImageAdjustPlugin — коррекция кадра перед детекцией линий.

Ставится после сегментации и ПЕРЕД edge_detection: подкрутить яркость/контраст/
насыщенность/гамму, чтобы TEED ловил чище и больше линий. Вход/выход — BGR-кадр.
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
from .registers import ImageAdjustRegisters


@register_plugin(
    "image_adjust",
    category="processing",
    description="Коррекция кадра: яркость, контраст, насыщенность, гамма",
)
class ImageAdjustPlugin(ProcessModulePlugin):
    """BGR-кадр → скорректированный BGR (яркость/контраст/насыщенность/гамма)."""

    name = "image_adjust"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Скорректированный BGR-кадр"),
    ]

    commands: dict[str, str] = {}
    register_class = ImageAdjustRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import ImageAdjustPluginConfig

        return ImageAdjustPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: ImageAdjustRegisters = self._init_register(ctx)
        ctx.log_info(
            f"ImageAdjustPlugin: brightness={self._reg.brightness} contrast={self._reg.contrast} "
            f"saturation={self._reg.saturation} gamma={self._reg.gamma}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None:
            return None
        out = geometry.apply_adjust(
            frame,
            brightness=float(self._reg.brightness),
            contrast=float(self._reg.contrast),
            saturation=float(self._reg.saturation),
            gamma=float(self._reg.gamma),
        )
        return {**item, "frame": out}
