"""HikvisionCameraPlugin -- source-плагин для промышленных камер Hikvision.

produce() возвращает BGR-кадры.
SHM write и IPC send выполняет SourceProducer (GenericProcess).

Lifecycle:
    configure() -- создание HikvisionCamera, параметры из конфига
    start()     -- auto_start если задан
    produce()   -- захват и конвертация кадра
    shutdown()  -- освобождение камеры
"""

from __future__ import annotations

import subprocess  # nosec B404 — запуск собственного SDK App фиксированной командой, без untrusted input
import sys
import threading
import time
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin

from Services.hikvision_camera.core.camera import HikvisionCamera
from Services.hikvision_camera.core.converter import FrameConverter

from .registers import HikvisionCameraRegisters

# Модуль frame_id для wrap-around (совместим с camera_service)
_FRAME_ID_MODULO = 121

# Кооперативный таймаут захвата (мс). Контракт source-плагина: produce() НЕ должен
# блокировать дольше ~2 интервалов кадра, иначе SourceProducer.run_loop не увидит
# stop_event и worker не остановится за дедлайн → terminate() (5с-лаг switch +
# незакрытая камера). При 25fps кадр приходит каждые 40мс, поэтому 200мс с запасом
# хватает (кадры НЕ теряются — таймаут просто вернёт [] и цикл перечитает stop_event),
# а остановка видна ≤200мс вместо 1000мс. См. docs/audits/2026-06-16_switch-routing-stale.md.
_CAPTURE_TIMEOUT_MS = 200


@register_plugin(
    "hikvision",
    category="source",
    description="Промышленная камера Hikvision (MVS SDK)",
)
class HikvisionCameraPlugin(ProcessModulePlugin):
    """Source-плагин для промышленных камер Hikvision.

    Специализированный Hikvision-only сервис с прямым доступом к SDK.
    В отличие от camera_service (multi-backend), этот плагин использует
    HikvisionCamera напрямую, без прослойки CameraBackend.

    Команды:
        open / close         -- управление подключением
        start_capture / stop_capture -- управление захватом
        enum_devices         -- перечисление доступных устройств
        get_parameters / set_parameters -- чтение/запись всех параметров
        set_exposure / set_gain / set_frame_rate -- точечные параметры
        set_resolution       -- изменение целевого разрешения
    """

    name = "hikvision"
    category = "source"

    inputs: list[Port] = []
    outputs: list[Port] = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="BGR-кадр с камеры Hikvision",
        ),
    ]

    commands: dict[str, str] = {
        # Управление камерой
        "open": "cmd_open",
        "close": "cmd_close",
        "start_capture": "cmd_start_capture",
        "stop_capture": "cmd_stop_capture",
        # Устройства
        "enum_devices": "cmd_enum_devices",
        # Параметры
        "get_parameters": "cmd_get_parameters",
        "set_parameters": "cmd_set_parameters",
        "set_exposure": "cmd_set_exposure",
        "set_gain": "cmd_set_gain",
        "set_frame_rate": "cmd_set_frame_rate",
        # Разрешение
        "set_resolution": "cmd_set_resolution",
        # SDK App (автономное GUI для отладки)
        "open_sdk_app": "cmd_open_sdk_app",
        "close_sdk_app": "cmd_close_sdk_app",
    }

    # Register-класс для GUI-биндинга (RegistersManager)
    register_class = HikvisionCameraRegisters

    # --- Lifecycle ---

    def configure(self, ctx: PluginContext) -> None:
        """Настроить плагин: создать HikvisionCamera, прочитать конфиг.

        ctx.config всегда плоский (нормализация формата pdef — в
        PluginOrchestrator._extract_plugin_config).
        """
        cfg = ctx.config
        self._ctx = ctx

        # Параметры из конфига
        self._camera_id: int = cfg.get("camera_id", 0)
        self._camera_index: int = cfg.get("camera_index", 0)
        self._width: int = cfg.get("resolution_width", 1920)
        self._height: int = cfg.get("resolution_height", 1080)
        self._resize_mode: str = cfg.get("resize_mode", "letterbox")
        self._fps: int = cfg.get("fps", 25)
        self._auto_start: bool = cfg.get("auto_start", False)

        # Состояние
        self._camera: HikvisionCamera | None = None
        self._camera_lock = threading.Lock()
        self._is_capturing: bool = False
        self._frame_count: int = 0
        self._sdk_process: subprocess.Popen | None = None

        # Register (runtime-параметры, управляемые из GUI)
        self._reg: HikvisionCameraRegisters = self._init_register(ctx)

        # Создаём камеру с логированием через контекст
        self._camera = HikvisionCamera(
            on_status=lambda t: ctx.log_info(f"[hikvision_{self._camera_id}] {t}"),
            on_error=lambda t: ctx.log_error(f"[hikvision_{self._camera_id}] {t}"),
        )

        ctx.log_info(
            f"HikvisionCameraPlugin[{self._camera_id}]: configured "
            f"(index={self._camera_index}, {self._width}x{self._height})"
        )

    def start(self, ctx: PluginContext) -> None:
        """Автозапуск захвата если auto_start=True."""
        if self._auto_start:
            result = self._do_start_capture()
            if result["status"] != "ok":
                ctx.log_error(
                    f"HikvisionCameraPlugin[{self._camera_id}]: auto_start failed: {result.get('error', 'unknown')}"
                )

    def produce(self) -> list[dict]:
        """Захватить один кадр с камеры.

        Возвращает [{"frame": ndarray, ...metadata}] или [].
        SHM write и IPC send выполняет SourceProducer (GenericProcess).
        """
        if not self._is_capturing or self._camera is None:
            return []

        with self._camera_lock:
            # Кооперативный таймаут: короткое ожидание → быстрый возврат управления
            # циклу (проверка stop_event), без потери кадров. См. _CAPTURE_TIMEOUT_MS.
            raw_frame, pixel_type = self._camera.capture_frame(timeout_ms=_CAPTURE_TIMEOUT_MS)

        if raw_frame is None:
            return []

        # Конвертация в BGR
        frame = FrameConverter.to_bgr(raw_frame, pixel_type)
        if frame is None:
            self._ctx.log_error(
                f"HikvisionCameraPlugin[{self._camera_id}]: не удалось сконвертировать кадр (pixel_type={pixel_type})"
            )
            return []

        # Resize до целевого разрешения (letterbox по умолчанию — не искажает
        # геометрию объектов; см. H2)
        frame = FrameConverter.resize(frame, self._width, self._height, self._resize_mode)

        self._frame_count = (self._frame_count + 1) % _FRAME_ID_MODULO

        return [
            {
                "frame": frame,
                "camera_id": self._camera_id,
                "seq_id": self._frame_count,
                "frame_id": self._frame_count,
                "timestamp": time.monotonic(),
                "camera_type": "hikvision",
                "width": self._width,
                "height": self._height,
                "channels": 3,
                "dtype": "uint8",
            }
        ]

    def shutdown(self, ctx: PluginContext) -> None:
        """Освободить камеру: остановить захват, закрыть подключение, SDK App."""
        ctx.log_info(f"HikvisionCameraPlugin[{self._camera_id}]: shutdown")
        self._is_capturing = False
        # Закрыть SDK App если запущен
        self._kill_sdk_process()
        with self._camera_lock:
            if self._camera:
                self._camera.close()
                self._camera = None

    # --- Внутренние методы ---

    def _do_start_capture(self) -> dict[str, Any]:
        """Открыть камеру и запустить захват.

        Returns:
            {"status": "ok"} или {"status": "error", "error": "..."}
        """
        with self._camera_lock:
            if not self._camera:
                return {"status": "error", "error": "Камера не инициализирована"}
            if not self._camera.open(self._camera_index):
                return {"status": "error", "error": "Не удалось открыть камеру"}
            if not self._camera.start_grabbing():
                return {"status": "error", "error": "Не удалось запустить захват"}
        self._is_capturing = True
        self._ctx.log_info(f"HikvisionCameraPlugin[{self._camera_id}]: захват запущен")
        return {"status": "ok"}

    def _do_stop_capture(self) -> dict[str, Any]:
        """Остановить захват (камера остаётся открытой).

        Returns:
            {"status": "ok"}
        """
        self._is_capturing = False
        with self._camera_lock:
            if self._camera:
                self._camera.stop_grabbing()
        self._ctx.log_info(f"HikvisionCameraPlugin[{self._camera_id}]: захват остановлен")
        return {"status": "ok"}

    def _apply_parameters_from_register(self) -> None:
        """Применить параметры из register к камере через SDK."""
        if not self._camera or not self._reg:
            return

        from Services.hikvision_camera.core.parameters import (
            CameraParameters,
            set_parameters,
        )

        params = CameraParameters(
            frame_rate=self._reg.frame_rate,
            exposure_time=self._reg.exposure_time,
            gain=self._reg.gain,
        )

        # Доступ к внутреннему MvCamera для set_parameters
        with self._camera_lock:
            if hasattr(self._camera, "_camera") and self._camera._camera is not None:
                ok = set_parameters(self._camera._camera, params)
                if not ok:
                    self._ctx.log_error(
                        f"HikvisionCameraPlugin[{self._camera_id}]: не удалось применить параметры из register"
                    )

    # --- Команды (авторегистрация через commands dict) ---

    def cmd_open(self, data: dict) -> dict:
        """Открыть камеру по индексу."""
        idx = data.get("camera_index", self._camera_index)
        self._camera_index = idx
        with self._camera_lock:
            if not self._camera:
                return {"status": "error", "error": "Камера не инициализирована"}
            ok = self._camera.open(idx)
        return {"status": "ok" if ok else "error"}

    def cmd_close(self, data: dict) -> dict:
        """Закрыть камеру."""
        self._is_capturing = False
        with self._camera_lock:
            if self._camera:
                self._camera.close()
        return {"status": "ok"}

    def cmd_start_capture(self, data: dict) -> dict:
        """Запустить захват кадров."""
        if "camera_index" in data:
            self._camera_index = data["camera_index"]
        return self._do_start_capture()

    def cmd_stop_capture(self, data: dict) -> dict:
        """Остановить захват кадров."""
        return self._do_stop_capture()

    def cmd_enum_devices(self, data: dict) -> dict:
        """Перечислить доступные Hikvision камеры (GigE/USB)."""
        from Services.hikvision_camera.core.discovery import enum_devices

        devices = enum_devices()
        return {"status": "ok", "devices": [d.to_dict() for d in devices]}

    def cmd_get_parameters(self, data: dict) -> dict:
        """Получить текущие параметры камеры из SDK."""
        from Services.hikvision_camera.core.parameters import get_parameters

        with self._camera_lock:
            if not self._camera or not hasattr(self._camera, "_camera") or self._camera._camera is None:
                return {"status": "error", "error": "Камера не открыта"}
            params = get_parameters(self._camera._camera)

        if params is None:
            return {"status": "error", "error": "Не удалось получить параметры"}

        return {
            "status": "ok",
            "parameters": {
                "frame_rate": params.frame_rate,
                "exposure_time": params.exposure_time,
                "gain": params.gain,
            },
        }

    def cmd_set_parameters(self, data: dict) -> dict:
        """Установить все параметры камеры (frame_rate, exposure_time, gain)."""
        from Services.hikvision_camera.core.parameters import (
            CameraParameters,
            set_parameters,
        )

        fr = data.get("frame_rate")
        exp = data.get("exposure_time")
        gain_val = data.get("gain")

        if fr is None or exp is None or gain_val is None:
            return {
                "status": "error",
                "error": "Не хватает параметров (frame_rate, exposure_time, gain)",
            }

        params = CameraParameters(
            frame_rate=float(fr),
            exposure_time=float(exp),
            gain=float(gain_val),
        )

        with self._camera_lock:
            if not self._camera or not hasattr(self._camera, "_camera") or self._camera._camera is None:
                return {"status": "error", "error": "Камера не открыта"}
            ok = set_parameters(self._camera._camera, params)

        if ok and self._reg:
            self._reg.frame_rate = params.frame_rate
            self._reg.exposure_time = params.exposure_time
            self._reg.gain = params.gain

        return {"status": "ok" if ok else "error"}

    def cmd_set_exposure(self, data: dict) -> dict:
        """Установить время экспозиции."""
        val = data.get("exposure_time", data.get("exposure"))
        if val is None:
            return {"status": "error", "error": "Не указан exposure_time"}
        if self._reg:
            self._reg.exposure_time = float(val)
        self._apply_parameters_from_register()
        return {"status": "ok", "exposure_time": float(val)}

    def cmd_set_gain(self, data: dict) -> dict:
        """Установить усиление."""
        val = data.get("gain")
        if val is None:
            return {"status": "error", "error": "Не указан gain"}
        if self._reg:
            self._reg.gain = float(val)
        self._apply_parameters_from_register()
        return {"status": "ok", "gain": float(val)}

    def cmd_set_frame_rate(self, data: dict) -> dict:
        """Установить частоту кадров."""
        val = data.get("frame_rate", data.get("fps"))
        if val is None:
            return {"status": "error", "error": "Не указан frame_rate"}
        self._fps = max(1, min(120, int(val)))
        if self._reg:
            self._reg.frame_rate = float(self._fps)
        self._apply_parameters_from_register()
        return {"status": "ok", "frame_rate": self._fps}

    def cmd_set_resolution(self, data: dict) -> dict:
        """Установить целевое разрешение (resize после захвата)."""
        self._width = int(data.get("width", self._width))
        self._height = int(data.get("height", self._height))
        return {"status": "ok", "width": self._width, "height": self._height}

    # --- SDK App (автономное GUI для отладки) ---

    def cmd_open_sdk_app(self, data: dict) -> dict:
        """Запустить SDK App — автономное GUI для отладки камеры.

        SDK App работает в отдельном процессе и напрямую с HikvisionCamera,
        независимо от основного pipeline.
        """
        if self._sdk_process is not None and self._sdk_process.poll() is None:
            return {"status": "ok", "message": "SDK App уже запущен"}
        try:
            # Корень проекта (для python -m hikvision_camera)
            project_root = Path(__file__).resolve().parent.parent.parent
            cmd = [sys.executable, "-m", "Services.hikvision_camera"]
            self._sdk_process = subprocess.Popen(  # nosec B603 — фиксированный cmd-список, shell=False, без пользовательского ввода
                cmd,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ctx.log_info(f"HikvisionCameraPlugin[{self._camera_id}]: SDK App запущен")
            return {"status": "ok", "message": "SDK App запущен"}
        except Exception as exc:
            self._ctx.log_error(f"HikvisionCameraPlugin[{self._camera_id}]: не удалось запустить SDK App: {exc}")
            return {"status": "error", "error": str(exc)}

    def cmd_close_sdk_app(self, data: dict) -> dict:
        """Закрыть SDK App."""
        self._kill_sdk_process()
        return {"status": "ok"}

    def _kill_sdk_process(self) -> None:
        """Завершить процесс SDK App если запущен."""
        if self._sdk_process is None:
            return
        try:
            self._sdk_process.terminate()
            self._sdk_process.wait(timeout=5)
        except Exception:
            try:
                self._sdk_process.kill()
            except Exception:
                pass
        finally:
            self._sdk_process = None
