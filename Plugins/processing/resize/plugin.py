"""ResizePlugin -- масштабирование BGR-кадра.

Processing-плагин: process(items) -> items с cv2.resize.
"""

from __future__ import annotations

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .registers import ResizeRegisters

# Маппинг интерполяции
_INTERP_MAP: dict[str, int] = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA,
}


@register_plugin("resize", category="processing", description="Масштабирование BGR-кадра")
class ResizePlugin(ProcessModulePlugin):
    """Масштабирование кадра через cv2.resize."""

    name = "resize"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Масштабированный BGR-кадр"),
    ]

    commands = {}

    # Register-класс плагина → managed register (GUI видит/меняет) + generic set_config
    register_class = ResizeRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class → register_schema() резолвит register_bindings.

        Без этого base.config_class() возвращает None и register_schema() == [],
        тогда RegistersManager процесса не создаётся и handler register_update
        не регистрируется (живой путь обрывается). См. PluginOrchestrator._init_registers.
        """
        from .config import ResizePluginConfig

        return ResizePluginConfig

    def configure(self, ctx: PluginContext) -> None:
        """Параметры ресайза: managed register (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)
        # Интерполяция статична (не live-tunable) — из YAML-конфига.
        self._interp: int = _INTERP_MAP.get(ctx.config.get("interpolation", "linear"), cv2.INTER_LINEAR)

        ctx.log_info(
            f"ResizePlugin: scale={self._reg.scale_factor}, target={self._reg.target_width}x{self._reg.target_height}"
        )

    @for_each
    def process(self, item: dict) -> dict | None:
        """Масштабирование одного кадра. Параметры ВСЕГДА из self._reg (live)."""
        frame = item.get("frame")
        if frame is None:
            return None

        # Параметры читаются из регистра на каждом кадре → live-правка применяется
        target_w = self._reg.target_width
        target_h = self._reg.target_height
        if target_w > 0 and target_h > 0:
            new_w, new_h = target_w, target_h
        else:
            h, w = frame.shape[:2]
            new_w = max(1, int(w * self._reg.scale_factor))
            new_h = max(1, int(h * self._reg.scale_factor))

        resized = cv2.resize(frame, (new_w, new_h), interpolation=self._interp)
        return {**item, "frame": resized, "width": new_w, "height": new_h}
