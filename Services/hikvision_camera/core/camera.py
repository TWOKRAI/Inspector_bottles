# -*- coding: utf-8 -*-
"""
HikvisionCamera — state machine камеры с валидацией переходов.

Состояния: CLOSED → OPEN → GRABBING.
Все переходы защищены: нельзя захватить кадр без start_grabbing(),
нельзя start_grabbing() без open(). Автоматические каскады (close из GRABBING)
корректно останавливают захват перед закрытием.
"""

from __future__ import annotations

import threading
from ctypes import byref, memset, sizeof, POINTER
from enum import Enum, auto
from typing import Callable

import numpy as np

from hikvision_camera.sdk.bindings import MvCamera, SDK_AVAILABLE
from hikvision_camera.sdk.structures import (
    MV_CC_DEVICE_INFO,
    MV_CC_DEVICE_INFO_LIST,
    MV_FRAME_OUT,
)
from hikvision_camera.sdk.constants import (
    MV_GIGE_DEVICE,
    MV_USB_DEVICE,
    MV_TRIGGER_MODE_OFF,
)
from hikvision_camera.sdk.errors import check_sdk_error, SdkError


class CameraState(Enum):
    """Состояние камеры."""

    CLOSED = auto()  # Нет подключения
    OPEN = auto()  # Камера открыта, но не захватывает
    GRABBING = auto()  # Активный захват кадров


class HikvisionCamera:
    """Камера Hikvision с state machine.

    Переходы состояний::

        CLOSED  ─open()──►  OPEN  ─start_grabbing()──►  GRABBING
                             │                              │
                         close()                       stop_grabbing()
                             ▼                              ▼
                          CLOSED                          OPEN
                                                            │
        GRABBING ─close()──► (stop → close) ──►          CLOSED

    Параметры
    ---------
    on_status : callable, optional
        Callback для статусных сообщений (str).
    on_error : callable, optional
        Callback для ошибок (str). Все ошибки логируются через этот callback,
        а не подавляются молча.
    """

    def __init__(
        self,
        on_status: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_status = on_status or (lambda _: None)
        self._on_error = on_error or (lambda _: None)

        self._camera: MvCamera | None = None
        self._state = CameraState.CLOSED
        self._camera_index: int = 0
        self._buf_lock = threading.Lock()

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self) -> CameraState:
        """Текущее состояние камеры."""
        return self._state

    @property
    def sdk_available(self) -> bool:
        """True если Hikvision SDK загружен."""
        return SDK_AVAILABLE

    @property
    def camera_index(self) -> int:
        """Индекс камеры, с которой работаем."""
        return self._camera_index

    # ── Управление жизненным циклом ────────────────────────────────────

    def open(self, camera_index: int = 0) -> bool:
        """Открыть камеру по индексу. CLOSED → OPEN.

        Если уже OPEN или GRABBING — возвращает True (идемпотентно).
        Для GigE устанавливает оптимальный размер пакета.
        Выключает trigger mode, включает frame rate enable.

        Returns
        -------
        bool
            True если камера открыта успешно.
        """
        if not SDK_AVAILABLE:
            self._on_error("Hikvision SDK не доступен")
            return False

        # Идемпотентность: уже открыта
        if self._state in (CameraState.OPEN, CameraState.GRABBING):
            return True

        try:
            # Перечисление устройств
            device_list = MV_CC_DEVICE_INFO_LIST()
            check_sdk_error(
                MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list),
                "enum_devices",
            )

            if device_list.nDeviceNum == 0:
                self._on_error("Камеры не найдены")
                return False

            if camera_index >= device_list.nDeviceNum:
                self._on_error(f"Индекс камеры {camera_index} недоступен (всего {device_list.nDeviceNum})")
                return False

            self._camera_index = camera_index

            # Получаем информацию об устройстве
            from ctypes import cast as c_cast

            st_dev = c_cast(
                device_list.pDeviceInfo[camera_index],
                POINTER(MV_CC_DEVICE_INFO),
            ).contents

            # Создаём handle и открываем устройство
            self._camera = MvCamera()

            check_sdk_error(
                self._camera.MV_CC_CreateHandle(st_dev),
                "create_handle",
            )

            try:
                check_sdk_error(
                    self._camera.MV_CC_OpenDevice(),
                    "open_device",
                )
            except SdkError:
                # Если открытие не удалось — уничтожаем handle
                self._camera.MV_CC_DestroyHandle()
                self._camera = None
                raise

            # GigE: оптимальный размер пакета
            if st_dev.nTLayerType == MV_GIGE_DEVICE:
                n_pkt = self._camera.MV_CC_GetOptimalPacketSize()
                if int(n_pkt) > 0:
                    self._camera.MV_CC_SetIntValue("GevSCPSPacketSize", n_pkt)

            # Базовые настройки: без триггера, с контролем fps
            self._camera.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            self._camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)

            self._state = CameraState.OPEN
            self._on_status("Камера открыта успешно")
            return True

        except SdkError as exc:
            self._on_error(f"Ошибка открытия камеры: {exc}")
            return False
        except Exception as exc:
            self._on_error(f"Непредвиденная ошибка при открытии камеры: {exc}")
            return False

    def close(self) -> None:
        """Закрыть камеру. Любое состояние → CLOSED.

        Если камера в GRABBING — сначала останавливает захват.
        Безопасно вызывать из любого состояния, включая CLOSED.
        """
        if self._state == CameraState.GRABBING:
            self.stop_grabbing()

        if self._camera is not None:
            try:
                self._camera.MV_CC_CloseDevice()
            except Exception as exc:
                self._on_error(f"Ошибка при закрытии устройства: {exc}")
            try:
                self._camera.MV_CC_DestroyHandle()
            except Exception as exc:
                self._on_error(f"Ошибка при уничтожении handle: {exc}")
            self._camera = None

        self._state = CameraState.CLOSED

    def start_grabbing(self) -> bool:
        """Начать захват кадров. OPEN → GRABBING.

        Если CLOSED — автоматически пытается open() с текущим camera_index.
        Если уже GRABBING — возвращает True (идемпотентно).

        Returns
        -------
        bool
            True если захват запущен.
        """
        if not SDK_AVAILABLE:
            self._on_error("Hikvision SDK не доступен")
            return False

        # Идемпотентность
        if self._state == CameraState.GRABBING:
            return True

        # Автоматическое открытие из CLOSED
        if self._state == CameraState.CLOSED:
            if not self.open(self._camera_index):
                return False

        if self._camera is None:
            self._on_error("Камера не инициализирована")
            return False

        try:
            check_sdk_error(
                self._camera.MV_CC_StartGrabbing(),
                "start_grabbing",
            )
            self._state = CameraState.GRABBING
            self._on_status("Захват запущен")
            return True
        except SdkError as exc:
            self._on_error(f"Ошибка запуска захвата: {exc}")
            return False

    def stop_grabbing(self) -> None:
        """Остановить захват. GRABBING → OPEN.

        Безопасно вызывать из любого состояния.
        """
        if self._state != CameraState.GRABBING or self._camera is None:
            return

        try:
            self._camera.MV_CC_StopGrabbing()
        except Exception as exc:
            self._on_error(f"Ошибка остановки захвата: {exc}")

        self._state = CameraState.OPEN
        self._on_status("Захват остановлен")

    # ── Захват кадров ──────────────────────────────────────────────────

    def capture_frame(self, timeout_ms: int = 1000) -> tuple[np.ndarray | None, int]:
        """Захватить один кадр.

        Parameters
        ----------
        timeout_ms : int
            Таймаут ожидания кадра в миллисекундах.

        Returns
        -------
        tuple[np.ndarray | None, int]
            (raw_frame, pixel_type).
            raw_frame — сырой массив (2D для Bayer/Gray), None при ошибке.
            pixel_type — тип пикселя из SDK (0 при ошибке).
        """
        if self._state != CameraState.GRABBING or self._camera is None:
            return None, 0

        try:
            st_out = MV_FRAME_OUT()
            memset(byref(st_out), 0, sizeof(st_out))

            ret = self._camera.MV_CC_GetImageBuffer(st_out, timeout_ms)
            if ret != 0:
                return None, 0

            try:
                info = st_out.stFrameInfo
                frame_len = info.nFrameLen
                height = info.nHeight
                width = info.nWidth
                pixel_type = info.enPixelType

                # Копирование через numpy вместо ctypes memcpy
                with self._buf_lock:
                    raw = np.ctypeslib.as_array(st_out.pBufAddr, shape=(frame_len,)).copy()

                # Reshaping: 1D → 2D (Bayer/Grayscale)
                if raw.ndim == 1:
                    raw = raw.reshape(height, width)

                return raw, pixel_type
            finally:
                # Освобождаем буфер SDK в любом случае
                self._camera.MV_CC_FreeImageBuffer(st_out)

        except Exception as exc:
            self._on_error(f"Ошибка захвата кадра: {exc}")
            return None, 0
