"""FrameSaverPlugin — периодическое сохранение кадров на диск.

Output-плагин: получает frame_ready → читает кадр из SHM →
сохраняет каждый N-й кадр в output_dir (PNG или JPEG).
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


@register_plugin("frame_saver", category="output", description="Сохранение кадров на диск")
class FrameSaverPlugin(ProcessModulePlugin):
    """Периодическое сохранение кадров из SHM на диск."""

    name = "frame_saver"
    category = "output"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр для сохранения"),
    ]
    outputs = []

    commands = {
        "save_now": "save_now",
        "get_stats": "get_stats",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: output_dir, формат, интервал."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._output_dir = Path(cfg.get("output_dir", "data/frames"))
        self._save_every_n: int = cfg.get("save_every_n", 10)
        self._image_format: str = cfg.get("image_format", "jpeg")
        self._jpeg_quality: int = cfg.get("jpeg_quality", 85)

        self._frame_count: int = 0
        self._saved_count: int = 0
        self._pending_frame_info: dict | None = None
        self._ctx = ctx

        # Создаём директорию
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Handler для frame_ready
        ctx.router_manager.register_message_handler(
            "frame_ready", self._on_frame_ready
        )

        # Команды
        ctx.command_manager.register_command("save_now", self._cmd_save_now)
        ctx.command_manager.register_command("get_stats", self._cmd_get_stats)

        ctx.log_info(
            f"FrameSaverPlugin[{self._camera_id}]: "
            f"dir={self._output_dir}, every={self._save_every_n}, "
            f"format={self._image_format}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Запустить worker для сохранения."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "saver_worker", self._save_loop, cfg, auto_start=True
        )
        ctx.log_info(f"FrameSaverPlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(
            f"FrameSaverPlugin[{self._camera_id}]: shutdown, "
            f"сохранено кадров: {self._saved_count}"
        )

    # --- Handlers ---

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready — сохранить info для worker."""
        data = msg.get("data", {})
        if data.get("camera_id") == self._camera_id:
            self._frame_count += 1
            # Сохраняем только каждый N-й
            if self._frame_count % self._save_every_n == 0:
                self._pending_frame_info = data

    # --- Worker ---

    def _save_loop(self, stop_event, pause_event) -> None:
        """Цикл: проверяет pending → читает SHM → сохраняет на диск."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if self._pending_frame_info is None:
                time.sleep(0.01)
                continue

            info = self._pending_frame_info
            self._pending_frame_info = None

            self._save_frame(info)

    def _save_frame(self, info: dict) -> bool:
        """Прочитать кадр из SHM и сохранить на диск."""
        shm_name = info.get("shm_name", f"camera_{self._camera_id}_frame")
        shm_index = info.get("shm_index", 0)

        mm = self._ctx.memory_manager
        if mm is None:
            return False

        frame = mm.read_images(f"camera_{self._camera_id}", shm_name, shm_index)
        if frame is None:
            return False

        # Имя файла: camera_0_frame_000042.jpeg
        frame_id = info.get("frame_id", self._saved_count)
        ext = "jpg" if self._image_format == "jpeg" else "png"
        filename = f"camera_{self._camera_id}_frame_{frame_id:06d}.{ext}"
        filepath = self._output_dir / filename

        # Сохранение
        if self._image_format == "jpeg":
            params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        else:
            params = [cv2.IMWRITE_PNG_COMPRESSION, 3]

        success = cv2.imwrite(str(filepath), frame, params)
        if success:
            self._saved_count += 1
        return success

    # --- Команды ---

    def _cmd_save_now(self, data: dict) -> dict:
        """Принудительное сохранение следующего кадра."""
        # Следующий кадр будет сохранён вне зависимости от N
        self._frame_count = self._save_every_n - 1
        return {"status": "ok", "message": "next frame will be saved"}

    def _cmd_get_stats(self, data: dict) -> dict:
        """Статистика сохранения."""
        return {
            "status": "ok",
            "saved_count": self._saved_count,
            "total_frames": self._frame_count,
            "output_dir": str(self._output_dir),
        }
