"""CapturePlugin — захват кадров с вебкамеры.

Source-плагин: cv2.VideoCapture → RingBufferWriter (SHM) → IPC frame_ready.
Запускается в паузе, ждёт команды start_capture.

Архитектура доставки кадров:
  1. CapturePlugin записывает frame в SHM через RingBufferWriter (pre-allocated)
  2. Отправляет IPC-сообщение с координатами (shm_actual_name, shm_index, width/height)
  3. GUI-процесс: FrameShmMiddleware.on_receive() открывает SHM по actual_name → numpy
"""

from __future__ import annotations

import time

import cv2

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.shared_resources_module.buffers.ring_buffer import (
    RingBufferWriter,
)
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


@register_plugin("capture", category="source", description="Захват кадров с вебкамеры (cv2)")
class CapturePlugin(ProcessModulePlugin):
    """Захват кадров с вебкамеры через cv2.VideoCapture.

    Lifecycle:
        configure() — ring buffer (SHM pre-allocation) + команды
        start() — создание capture_worker (loop, paused)
        shutdown() — остановка камеры, очистка SHM
    """

    name = "capture"
    category = "source"

    inputs = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр с камеры"),
    ]

    # Команды регистрируются вручную в configure()
    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: SHM ring-buffer, команды."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._device_id: int = cfg.get("device_id", 0)
        self._fps: int = cfg.get("fps", 25)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        ring_buffer_size: int = cfg.get("ring_buffer_size", 3)

        # Куда отправлять frame_ready
        default_target = f"processor_{self._camera_id}"
        frame_targets = cfg.get("frame_targets", None)
        if frame_targets is None:
            self._frame_targets: list[str] = [default_target]
        else:
            self._frame_targets = frame_targets if isinstance(frame_targets, list) else [frame_targets]

        shm_owner = f"camera_{self._camera_id}"
        shm_slot = f"camera_{self._camera_id}_frame"

        ctx.log_info(
            f"CapturePlugin[{self._camera_id}]: device={self._device_id}, "
            f"{self._width}x{self._height}@{self._fps}fps, ring_buffer={ring_buffer_size}"
        )

        # Ring-buffer: pre-allocate SHM-блоки для round-robin записи кадров
        self._ring_buffer = RingBufferWriter(
            ctx.memory_manager,
            owner=shm_owner,
            slot_prefix=shm_slot,
            k=ring_buffer_size,
        )

        # Команды
        def cmd_start_capture(data: dict) -> dict:
            self._start_capture(ctx)
            return {"status": "ok"}

        def cmd_stop_capture(data: dict) -> dict:
            self._stop_capture(ctx)
            return {"status": "ok"}

        ctx.command_manager.register_command("start_capture", cmd_start_capture)
        ctx.command_manager.register_command("stop_capture", cmd_stop_capture)

        # Состояние
        self._cap: cv2.VideoCapture | None = None
        self._is_capturing = False
        self._frame_count = 0
        self._ctx = ctx

    def start(self, ctx: PluginContext) -> None:
        """Создать capture_worker (стартует в паузе — ждёт start_capture)."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "capture_worker", self._capture_loop, cfg, auto_start=False
        )
        ctx.worker_manager.pause_worker("capture_worker")
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: worker создан (paused)")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка камеры и очистка SHM."""
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: shutdown...")
        if ctx.worker_manager:
            ctx.worker_manager.pause_worker("capture_worker")
        self._release_camera()
        if ctx.memory_manager:
            ctx.memory_manager.close_all(f"camera_{self._camera_id}")

    # --- Внутренние методы ---

    def _start_capture(self, ctx: PluginContext) -> None:
        """Открыть камеру и начать захват."""
        if self._is_capturing:
            return
        self._cap = cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)
        if self._cap.isOpened():
            # Пробуем установить параметры, но не падаем если камера не поддерживает
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            self._cap.set(cv2.CAP_PROP_FPS, self._fps)
            # Прочитать реальные параметры камеры
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            ctx.log_info(
                f"CapturePlugin[{self._camera_id}]: камера открыта "
                f"(реальное разрешение: {actual_w}x{actual_h})"
            )
            self._is_capturing = True
            if not ctx.worker_manager.is_worker_running("capture_worker"):
                ctx.worker_manager.start_worker("capture_worker")
            ctx.worker_manager.resume_worker("capture_worker")
            ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват запущен")
        else:
            ctx.log_error(
                f"CapturePlugin[{self._camera_id}]: не удалось открыть камеру {self._device_id}"
            )

    def _stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват."""
        if ctx.worker_manager:
            ctx.worker_manager.pause_worker("capture_worker")
        self._is_capturing = False
        self._release_camera()
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват остановлен")

    def _release_camera(self) -> None:
        """Освободить камеру."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_loop(self, stop_event, pause_event) -> None:
        """Основной цикл: cv2.read → SHM write → IPC координаты."""
        frame_interval = 1.0 / max(self._fps, 1)

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            t0 = time.monotonic()
            try:
                ret, frame = self._cap.read()
            except Exception:
                time.sleep(0.1)
                continue

            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # Resize если нужно
            h, w = frame.shape[:2]
            if w != self._width or h != self._height:
                frame = cv2.resize(frame, (self._width, self._height))

            # Запись в SHM ring-buffer (pre-allocated)
            slot_index, seq_id = self._ring_buffer.write(frame)
            self._frame_count += 1

            # Получить фактическое OS-имя SHM (содержит PID на Windows)
            shm_owner = f"camera_{self._camera_id}"
            shm_slot = f"camera_{self._camera_id}_frame"
            shm_actual_name = None
            mm = self._ctx.memory_manager
            if mm and hasattr(mm, "get_actual_shm_name"):
                shm_actual_name = mm.get_actual_shm_name(shm_owner, shm_slot, slot_index)

            # Отправить координаты (без numpy! — только метаданные для чтения из SHM)
            frame_data = {
                "camera_id": self._camera_id,
                "shm_name": shm_slot,
                "shm_index": slot_index,
                "shm_actual_name": shm_actual_name,
                "width": self._width,
                "height": self._height,
                "channels": 3,
                "dtype": "uint8",
                "seq_id": seq_id,
                "frame_id": self._frame_count,
                "timestamp": t0,
            }
            for target in self._frame_targets:
                self._ctx.io.send_data(target, "frame_ready", frame_data)

            # FPS throttle
            elapsed = time.monotonic() - t0
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
