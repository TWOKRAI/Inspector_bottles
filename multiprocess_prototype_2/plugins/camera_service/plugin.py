"""CameraServicePlugin -- multi-backend камера.

Source-плагин: produce() возвращает BGR-кадры от выбранного backend'а.
SHM write и IPC send выполняет GenericProcess (SourceProducer).
"""

from __future__ import annotations

import sys
import time
import threading

import cv2

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin

from .backends import (
    CameraBackend,
    create_backend,
    hw_release_delay,
    CAMERA_TYPES,
    DEFAULT_CAMERA_TYPE,
)

# Модуль frame_id для wrap-around
_FRAME_ID_MODULO = 121


@register_plugin(
    "camera_service",
    category="source",
    description="Multi-backend камера (simulator/webcam/hikvision/file)",
)
class CameraServicePlugin(ProcessModulePlugin):
    """Multi-backend камера с горячим переключением backend'ов.

    Lifecycle:
        configure() — параметры камеры, backend, команды
        start()     — auto_start если задан в конфиге
        produce()   — захват одного кадра (вызывается SourceProducer)
        shutdown()  — освобождение backend'а
    """

    name = "camera_service"
    category = "source"

    inputs = []
    outputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="BGR-кадр с камеры",
        ),
    ]

    commands = {}

    # --- Lifecycle ---

    def configure(self, ctx: PluginContext) -> None:
        """Настроить параметры камеры и зарегистрировать команды."""
        cfg = ctx.config

        self._camera_type: str = cfg.get("camera_type", DEFAULT_CAMERA_TYPE)
        self._camera_id: int = cfg.get("camera_id", 0)
        self._device_id: int = cfg.get("device_id", 0)
        self._fps: int = cfg.get("fps", 25)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._auto_start: bool = cfg.get("auto_start", False)
        self._camera_index: int = cfg.get("camera_index", 0)
        self._hik_width: int = cfg.get("hikvision_resolution_width", 1920)
        self._hik_height: int = cfg.get("hikvision_resolution_height", 1080)
        self._sim_image: str | None = cfg.get("simulator_image_path")
        self._file_path: str = cfg.get("file_source_path", "")

        # Состояние
        self._backend: CameraBackend | None = None
        self._backend_lock = threading.Lock()
        self._is_capturing = False
        self._frame_count = 0
        self._ctx = ctx

        # Зарегистрировать все 14 команд
        self._register_commands(ctx)

        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}]: type={self._camera_type}, "
            f"{self._width}x{self._height}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Auto-start камеры если задан в конфиге."""
        if self._auto_start:
            self._do_start_capture(ctx)

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановить захват и освободить backend."""
        ctx.log_info(f"CameraServicePlugin[{self._camera_id}]: shutdown")
        self._is_capturing = False
        with self._backend_lock:
            if self._backend:
                self._backend.stop()
                self._backend.close()
                self._backend = None

    def produce(self) -> list[dict]:
        """Захватить один кадр от текущего backend'а.

        Возвращает [{"frame": ndarray, ...metadata}] или [].
        SHM write и IPC send выполняет SourceProducer.
        """
        if not self._is_capturing or self._backend is None:
            return []

        try:
            frame = self._backend.capture_frame()
        except Exception:
            return []

        if frame is None:
            return []

        # Resize до целевого разрешения если нужно
        h, w = frame.shape[:2]
        target_w, target_h = self._effective_resolution()
        if w != target_w or h != target_h:
            frame = cv2.resize(frame, (target_w, target_h))

        self._frame_count = (self._frame_count + 1) % _FRAME_ID_MODULO

        return [
            {
                "frame": frame,
                "camera_id": self._camera_id,
                "seq_id": self._frame_count,
                "frame_id": self._frame_count,
                "timestamp": time.monotonic(),
                "camera_type": self._camera_type,
                "width": target_w,
                "height": target_h,
                "channels": 3,
                "dtype": "uint8",
            }
        ]

    # --- Внутренние методы ---

    def _effective_resolution(self) -> tuple[int, int]:
        """Получить целевое разрешение с учётом типа backend'а.

        Returns:
            (width, height)
        """
        if self._camera_type == "hikvision":
            return self._hik_width, self._hik_height
        return self._width, self._height

    def _backend_kwargs(self) -> dict:
        """Собрать kwargs для create_backend() с учётом текущих настроек."""
        w, h = self._effective_resolution()
        return {
            "width": w,
            "height": h,
            "device_id": self._device_id,
            "camera_index": self._camera_index,
            "image_path": self._sim_image,
            "file_path": self._file_path,
        }

    def _do_start_capture(self, ctx: PluginContext) -> None:
        """Создать backend (если нет) и запустить захват."""
        if self._is_capturing:
            return

        with self._backend_lock:
            if self._backend is None:
                self._backend = create_backend(
                    self._camera_type, **self._backend_kwargs()
                )
            self._backend.start()

        self._is_capturing = True
        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}]: "
            f"захват запущен (backend={self._camera_type})"
        )

    def _do_stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват (backend остаётся, но stop)."""
        self._is_capturing = False
        with self._backend_lock:
            if self._backend:
                self._backend.stop()
        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}]: захват остановлен"
        )

    def _do_switch_camera_type(self, new_type: str) -> dict:
        """Горячее переключение backend'а.

        Последовательность: stop → close → hw_delay → create → auto-restart.
        """
        if new_type not in CAMERA_TYPES:
            return {
                "status": "error",
                "error": f"Неизвестный тип камеры: {new_type!r}. "
                f"Допустимые: {CAMERA_TYPES}",
            }

        was_capturing = self._is_capturing
        old_type = self._camera_type

        # Остановить текущий backend
        self._is_capturing = False
        with self._backend_lock:
            if self._backend:
                self._backend.stop()
                self._backend.close()
                self._backend = None

        # Аппаратная задержка после освобождения устройства
        delay = hw_release_delay(old_type)
        if delay > 0:
            time.sleep(delay)

        # Переключить тип
        self._camera_type = new_type

        # Создать новый backend
        with self._backend_lock:
            self._backend = create_backend(
                self._camera_type, **self._backend_kwargs()
            )

        # Если захват был активен — перезапустить
        if was_capturing:
            with self._backend_lock:
                if self._backend:
                    self._backend.start()
            self._is_capturing = True

        self._ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}]: "
            f"переключение {old_type} → {new_type}"
        )
        return {"status": "ok", "camera_type": new_type}

    # --- Регистрация команд ---

    def _register_commands(self, ctx: PluginContext) -> None:
        """Зарегистрировать все 14 команд плагина."""
        cm = ctx.command_manager

        # 1. start_capture
        def cmd_start_capture(data: dict) -> dict:
            self._do_start_capture(ctx)
            return {"status": "ok"}

        # 2. stop_capture
        def cmd_stop_capture(data: dict) -> dict:
            self._do_stop_capture(ctx)
            return {"status": "ok"}

        # 3. set_camera_type
        def cmd_set_camera_type(data: dict) -> dict:
            new_type = data.get("camera_type", "")
            return self._do_switch_camera_type(new_type)

        # 4. set_fps — clamp 1-120
        def cmd_set_fps(data: dict) -> dict:
            fps = data.get("fps", self._fps)
            self._fps = max(1, min(120, int(fps)))
            return {"status": "ok", "fps": self._fps}

        # 5. set_resolution — обновить и пересоздать backend если нужно
        def cmd_set_resolution(data: dict) -> dict:
            self._width = int(data.get("width", self._width))
            self._height = int(data.get("height", self._height))
            # Пересоздать backend если захват активен и тип simulator/webcam
            if self._is_capturing and self._camera_type in ("simulator", "webcam"):
                self._do_switch_camera_type(self._camera_type)
            return {
                "status": "ok",
                "width": self._width,
                "height": self._height,
            }

        # 6. set_device_id
        def cmd_set_device_id(data: dict) -> dict:
            self._device_id = int(data.get("device_id", self._device_id))
            return {"status": "ok", "device_id": self._device_id}

        # 7. set_camera_index
        def cmd_set_camera_index(data: dict) -> dict:
            self._camera_index = int(
                data.get("camera_index", self._camera_index)
            )
            return {"status": "ok", "camera_index": self._camera_index}

        # 8. enum_devices — passthrough
        def cmd_enum_devices(data: dict) -> dict:
            with self._backend_lock:
                if self._backend:
                    result = self._backend.handle_command("enum_devices", data)
                    return result or {"status": "ok", "devices": []}
            return {"status": "ok", "devices": []}

        # 9-14. hik_* команды — passthrough к backend (strip hik_ prefix)
        def _make_hik_passthrough(hik_cmd: str):
            """Создать обработчик hik_* команды."""
            backend_cmd = hik_cmd[4:]  # strip "hik_" prefix

            def handler(data: dict) -> dict:
                if self._camera_type != "hikvision":
                    return {
                        "status": "error",
                        "error": f"Команда {hik_cmd} доступна только для hikvision backend",
                    }
                with self._backend_lock:
                    if self._backend:
                        result = self._backend.handle_command(backend_cmd, data)
                        return result or {"status": "ok"}
                return {"status": "error", "error": "Backend не инициализирован"}

            return handler

        # Регистрация
        cm.register_command("start_capture", cmd_start_capture)
        cm.register_command("stop_capture", cmd_stop_capture)
        cm.register_command("set_camera_type", cmd_set_camera_type)
        cm.register_command("set_fps", cmd_set_fps)
        cm.register_command("set_resolution", cmd_set_resolution)
        cm.register_command("set_device_id", cmd_set_device_id)
        cm.register_command("set_camera_index", cmd_set_camera_index)
        cm.register_command("enum_devices", cmd_enum_devices)

        # hik_* passthrough команды
        for hik_cmd in (
            "hik_open",
            "hik_close",
            "hik_start_grabbing",
            "hik_stop_grabbing",
            "hik_get_parameters",
            "hik_set_parameters",
        ):
            cm.register_command(hik_cmd, _make_hik_passthrough(hik_cmd))
