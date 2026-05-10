"""FrameSaverPlugin -- периодическое сохранение кадров на диск.

Output-плагин: process(items) -> items (pass-through с side-effect сохранения).
Каждый N-й кадр сохраняется в output_dir (PNG или JPEG).

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

from pathlib import Path

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .registers import FrameSaverRegisters


@register_plugin("frame_saver", category="output", description="Сохранение кадров на диск")
class FrameSaverPlugin(ProcessModulePlugin):
    """Периодическое сохранение кадров на диск."""

    name = "frame_saver"
    category = "output"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр"),
    ]
    outputs = []

    commands = {
        "save_now": "_cmd_save_now",
        "get_stats": "_cmd_get_stats",
    }
    register_class = FrameSaverRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        cfg = ctx.config
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # camera_id из cfg (не входит в register — идентификатор хоста)
        self._camera_id: int = cfg.get("camera_id", 0)

        self._frame_count: int = 0
        self._saved_count: int = 0

        Path(self._reg.output_dir).mkdir(parents=True, exist_ok=True)

        ctx.log_info(
            f"FrameSaverPlugin[{self._camera_id}]: "
            f"dir={self._reg.output_dir}, every={self._reg.save_every_n}, "
            f"format={self._reg.image_format}"
        )

    def shutdown(self, ctx: PluginContext) -> None:
        """Финальная статистика."""
        ctx.log_info(
            f"FrameSaverPlugin[{self._camera_id}]: shutdown, "
            f"сохранено кадров: {self._saved_count}"
        )

    def process(self, items: list[dict]) -> list[dict]:
        """Сохранить каждый N-й кадр на диск. Pass-through."""
        for item in items:
            self._frame_count += 1
            if self._frame_count % self._reg.save_every_n == 0:
                self._save_frame(item)
        return items

    def _save_frame(self, item: dict) -> bool:
        """Сохранить кадр из item["frame"] на диск."""
        frame = item.get("frame")
        if frame is None:
            return False

        frame_id = item.get("frame_id", self._saved_count)
        ext = "jpg" if self._reg.image_format == "jpeg" else "png"
        filename = f"camera_{self._camera_id}_frame_{frame_id:06d}.{ext}"
        filepath = Path(self._reg.output_dir) / filename

        if self._reg.image_format == "jpeg":
            params = [cv2.IMWRITE_JPEG_QUALITY, self._reg.jpeg_quality]
        else:
            params = [cv2.IMWRITE_PNG_COMPRESSION, 3]

        success = cv2.imwrite(str(filepath), frame, params)
        if success:
            self._saved_count += 1
        return success

    # --- Команды ---

    def _cmd_save_now(self, data: dict) -> dict:
        """Принудительное сохранение следующего кадра."""
        self._frame_count = self._reg.save_every_n - 1
        return {"status": "ok", "message": "next frame will be saved"}

    def _cmd_get_stats(self, data: dict) -> dict:
        """Статистика."""
        return {
            "status": "ok",
            "saved_count": self._saved_count,
            "total_frames": self._frame_count,
            "output_dir": str(self._reg.output_dir),
        }
