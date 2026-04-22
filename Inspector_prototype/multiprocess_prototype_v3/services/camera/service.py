"""CameraService — бизнес-логика управления камерой.

Содержит:
- Управление бэкендом (switch, create)
- Захват и публикация кадров (capture + resize + SHM + notify)
- FPS throttling
- Hikvision-специфичная логика (platform check, parameter patching)
- Перечисление устройств

Не зависит от ProcessModule и multiprocess_framework.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from multiprocess_prototype_v3.services.camera.ports import CameraOutputPort

from multiprocess_prototype_v3.registers.camera import (
    CAMERA_TYPES,
    DEFAULT_CAMERA_TYPE,
    SUPPORTS_ENUM,
)
from multiprocess_prototype_v3.services.camera.backends import (
    CameraBackendParams,
    create_camera_backend,
)
from multiprocess_prototype_v3.services.camera.constants import (
    CAMERA_SHM_HEIGHT,
    CAMERA_SHM_WIDTH,
)
from Utils.fps_module import FrameFPS

# Задержка после close() аппаратных камер (ОС отпускает устройство)
_HW_RELEASE_DELAY = {"webcam": 0.3, "hikvision": 0.3}


def _wait_hw_release(camera_type: str) -> None:
    """Подождать пока ОС освободит устройство после close()."""
    delay = _HW_RELEASE_DELAY.get(camera_type, 0)
    if delay > 0:
        time.sleep(delay)


def _resize_frame_for_shm(frame: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Resize frame до размеров SHM-буфера."""
    if frame.shape[0] == target_h and frame.shape[1] == target_w:
        return frame
    try:
        import cv2

        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    except ImportError:
        return frame


class CameraService:
    """Бизнес-логика камеры. Чистый сервис без привязки к фреймворку.

    Управляет бэкендом захвата, FPS-троттлингом, переключением типов камер,
    параметрами Hikvision. Взаимодействует с инфраструктурой через CameraOutputPort.

    Модель переключения (простая):
        stop → close → wait_hw_release(old) → create(new)
    Никаких pre-reset при переходе К новому типу — только задержка
    после закрытия аппаратного бэкенда, чтобы ОС успела освободить устройство.
    """

    def __init__(self, output: CameraOutputPort, config: dict) -> None:
        self._out = output

        # Параметры из конфига
        self._fps = config.get("fps", 30)
        self._width = config.get("resolution_width", 640)
        self._height = config.get("resolution_height", 480)
        self._device_id = config.get("device_id", 0)
        self._camera_index = config.get("camera_index", 0)
        self._hikvision_width = config.get("hikvision_resolution_width", 1920)
        self._hikvision_height = config.get("hikvision_resolution_height", 1080)
        self._hikvision_frame_rate = float(config.get("hikvision_frame_rate", 25.0))
        self._hikvision_exposure_time = float(config.get("hikvision_exposure_time", 10000.0))
        self._hikvision_gain = float(config.get("hikvision_gain", 0.0))
        self._simulator_image_path = config.get("simulator_image_path")
        self._file_source_path = config.get("file_source_path", "")

        # Бизнес-состояние
        self._backend_lock = threading.Lock()
        self._frame_id = 0
        self._fps_counter = FrameFPS(interval=1.0)

        # Инициализация бэкенда (без handoff — при старте устройство свободно)
        initial_type = config.get("camera_type", DEFAULT_CAMERA_TYPE)
        if initial_type not in CAMERA_TYPES:
            initial_type = DEFAULT_CAMERA_TYPE
        self._current_type = initial_type
        self._backend = self._create_backend(initial_type)

    # --- Публичные свойства ---

    @property
    def current_type(self) -> str:
        return self._current_type

    @property
    def is_capturing(self) -> bool:
        """Активен ли захват (бэкенд запущен)."""
        return getattr(self._backend, "_running", False)

    # --- Создание и переключение бэкенда ---

    def _backend_params(self) -> CameraBackendParams:
        """Собрать параметры для создания бэкенда."""
        return CameraBackendParams(
            width=self._width,
            height=self._height,
            device_id=self._device_id,
            camera_index=self._camera_index,
            hikvision_width=self._hikvision_width,
            hikvision_height=self._hikvision_height,
            simulator_image_path=self._simulator_image_path,
            send_to_gui=lambda msg_type, data: self._out.send_to_gui(msg_type, data),
            file_source_path=self._file_source_path,
        )

    def _create_backend(self, camera_type: str):
        """Создать экземпляр бэкенда по типу камеры."""
        return create_camera_backend(camera_type, self._backend_params())

    def switch_camera_type(self, new_type: str) -> dict:
        """Переключить тип камеры. Возвращает dict с результатом.

        Модель: stop → close → wait(old) → create(new).
        """
        if new_type not in CAMERA_TYPES:
            return {"status": "error", "error": f"Unknown camera_type: {new_type}"}
        if new_type == "hikvision" and sys.platform != "win32":
            new_type = "simulator"
            self._out.send_to_gui("status", {"status": "Hikvision only on Windows, using Simulator"})
        with self._backend_lock:
            if self._current_type == new_type:
                self._out.send_to_gui("status", {"status": f"Already {new_type}"})
                return {"status": "ok"}
            old_type = self._current_type
            # Чистое завершение текущего бэкенда
            self._backend.stop()
            self._backend.close()
            # Задержка только после закрытия аппаратной камеры
            _wait_hw_release(old_type)
            # Создать новый бэкенд (конструктор откроет устройство)
            self._current_type = new_type
            self._backend = self._create_backend(new_type)
            self._out.send_to_gui("camera_type_changed", {"camera_type": new_type})
            self._out.send_to_gui("status", {"status": f"Switched to {new_type}"})
            return {"status": "ok", "camera_type": new_type}

    # --- Управление захватом ---

    def start_capture(self, data: dict) -> dict | None:
        """Запустить захват. Для hikvision делегирует handle_command."""
        with self._backend_lock:
            if self._current_type == "hikvision":
                result = self._backend.handle_command("start_grabbing", data)
                return result
            else:
                self._backend.start()
                # Проверить что бэкенд реально запустился
                if hasattr(self._backend, "_running") and not self._backend._running:
                    self._out.send_to_gui(
                        "error",
                        {"error": f"Не удалось открыть камеру ({self._current_type})"},
                    )
                    return {"status": "error", "error": "Camera failed to open"}
                return {"status": "ok"}

    def stop_capture(self, data: dict) -> dict:
        """Остановить захват. Сбрасывает FPS-счётчик.

        Не закрывает бэкенд — камера остаётся открытой для быстрого
        повторного старта. close() делается только при switch или shutdown.
        """
        self._fps_counter.reset()
        self._out.send_to_gui("fps_update", {"fps": 0})
        with self._backend_lock:
            if self._current_type == "hikvision":
                result = self._backend.handle_command("stop_grabbing", data)
            else:
                self._backend.stop()
                result = {"status": "ok"}
        return result or {"status": "ok"}

    def capture_and_publish(self) -> bool:
        """Захватить один кадр, resize, записать в SHM, уведомить процессор.

        Returns:
            True если кадр успешно обработан, False если нет кадра.
        """
        frame_start = time.perf_counter()

        # Захват кадра
        with self._backend_lock:
            backend = self._backend
        frame = backend.capture_frame()
        if frame is None:
            time.sleep(0.01)
            return False

        # Подготовка метаданных
        self._frame_id = (self._frame_id + 1) % 121
        timestamp = time.time()

        # Resize до размеров SHM-буфера
        frame = _resize_frame_for_shm(frame, CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH)

        # Запись в SHM через порт
        shm_result = self._out.write_frame_to_shm(frame, self._frame_id, timestamp)
        if shm_result:
            # Уведомление процессора
            notification_data = {
                "frame_id": self._frame_id,
                "timestamp": timestamp,
                "shm_name": shm_result.get("shm_name", "camera_frame"),
                "shm_index": shm_result.get("shm_index", 0),
                "shm_actual_name": shm_result.get("shm_actual_name", ""),
                "seq_id": shm_result.get("seq_id", self._frame_id),
                "width": frame.shape[1],
                "height": frame.shape[0],
            }
            self._out.send_frame_to_processor(notification_data)

            # Обновление FPS
            fps = self._fps_counter.update()
            if fps > 0:
                self._out.send_to_gui("fps_update", {"fps": fps})

        # FPS throttling (не для hikvision — он сам контролирует frame rate)
        if self._current_type != "hikvision":
            elapsed = time.perf_counter() - frame_start
            target_interval = 1.0 / max(1, self._fps)
            sleep_time = target_interval - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)

        return True

    # --- Настройки параметров ---

    def set_fps(self, data: dict) -> dict:
        """Установить целевой FPS."""
        self._fps = max(1, min(120, data.get("fps", self._fps)))
        return {"status": "ok", "fps": self._fps}

    def set_resolution(self, data: dict) -> dict:
        """Установить разрешение (для simulator/webcam пересоздаёт бэкенд)."""
        self._width = data.get("width", self._width)
        self._height = data.get("height", self._height)
        if self._current_type in ("simulator", "webcam"):
            with self._backend_lock:
                self._backend.close()
                self._backend = self._create_backend(self._current_type)
        return {"status": "ok"}

    def set_device_id(self, data: dict) -> dict:
        """Установить device_id (индекс устройства OpenCV)."""
        self._device_id = data.get("device_id", self._device_id)
        return {"status": "ok", "device_id": self._device_id}

    def set_camera_index(self, data: dict) -> dict:
        """Установить camera_index (индекс камеры Hikvision)."""
        self._camera_index = data.get("camera_index", self._camera_index)
        return {"status": "ok", "camera_index": self._camera_index}

    def set_hikvision_resolution(self, data: dict) -> dict:
        """Установить разрешение для Hikvision."""
        self._hikvision_width = data.get("width", self._hikvision_width)
        self._hikvision_height = data.get("height", self._hikvision_height)
        return {"status": "ok"}

    def patch_hikvision_params(self, partial: dict) -> None:
        """Обновить параметры Hikvision (frame_rate, exposure_time, gain).

        Если текущий бэкенд — hikvision, применяет параметры немедленно.
        """
        if "frame_rate" in partial:
            self._hikvision_frame_rate = float(partial["frame_rate"])
        if "exposure_time" in partial:
            self._hikvision_exposure_time = float(partial["exposure_time"])
        if "gain" in partial:
            self._hikvision_gain = float(partial["gain"])
        with self._backend_lock:
            if self._current_type == "hikvision":
                self._backend.handle_command(
                    "set_parameters",
                    {
                        "frame_rate": self._hikvision_frame_rate,
                        "exposure_time": self._hikvision_exposure_time,
                        "gain": self._hikvision_gain,
                    },
                )

    # --- Hikvision команды ---

    def handle_hikvision_command(self, cmd: str, data: dict) -> dict:
        """Обработать Hikvision-специфичную команду (open, close, get/set_parameters)."""
        with self._backend_lock:
            if self._current_type != "hikvision":
                if cmd == "close":
                    return {"status": "ok"}
                return {"status": "error", "error": "Not in hikvision mode"}
            result = self._backend.handle_command(cmd, data)
            return result or {}

    # --- Перечисление устройств ---

    def enumerate_devices(self, data: dict) -> dict:
        """Перечислить доступные устройства.

        Поддерживает backend hint для перечисления устройств другого типа
        без полного переключения бэкенда.
        """
        payload = dict(data or {})
        backend_hint = payload.get("backend")
        use_backend = backend_hint if backend_hint in ("webcam", "hikvision") else None

        with self._backend_lock:
            effective_type = use_backend or self._current_type
            if effective_type not in SUPPORTS_ENUM:
                self._out.send_to_gui("enum_devices_response", {"devices": []})
                return {"status": "ok", "devices": []}

            if use_backend and use_backend != self._current_type:
                result = self._enum_devices_for_backend(use_backend, payload)
            else:
                result = self._backend.handle_command("enum_devices", payload) or {}

            if isinstance(result, dict) and result.get("status") == "ok" and "devices" in result:
                self._out.send_to_gui("enum_devices_response", {"devices": result["devices"]})
            return result

    def _enum_devices_for_backend(self, backend: str, payload: dict) -> dict:
        """Перечислить устройства другого бэкенда (cross-backend enum).

        Для hikvision: временно освобождает webcam, вызывает enum, возвращает webcam.
        Для webcam: прямой вызов _enum_webcam_devices.
        """
        if backend == "hikvision":
            # Если текущий — webcam, нужно освободить ресурсы
            need_restore_webcam = self._current_type == "webcam"
            if need_restore_webcam:
                try:
                    self._backend.stop()
                    self._backend.close()
                except Exception:
                    pass
                _wait_hw_release("webcam")

            from hikvision_camera_module.core.capture import enum_devices

            result = enum_devices() or {}
            if isinstance(result, dict) and result.get("status") == "ok":
                for dev in result.get("devices") or []:
                    if isinstance(dev, dict):
                        dev.setdefault("source", "hikvision")

            if need_restore_webcam:
                self._backend = self._create_backend("webcam")
            return result

        if backend == "webcam":
            from multiprocess_prototype_v3.services.camera.backends import _enum_webcam_devices

            return _enum_webcam_devices(payload.get("max_index"))

        return {"status": "error", "devices": []}

    # --- Shutdown ---

    def shutdown(self) -> None:
        """Остановить и закрыть бэкенд. Вызывается из CameraProcess.shutdown()."""
        with self._backend_lock:
            if self._backend:
                try:
                    self._backend.stop()
                    self._backend.close()
                finally:
                    self._backend = None
