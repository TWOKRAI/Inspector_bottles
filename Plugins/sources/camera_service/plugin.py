"""CameraServicePlugin -- multi-backend камера.

Source-плагин: produce() возвращает BGR-кадры от выбранного backend'а.
SHM write и IPC send выполняет GenericProcess (SourceProducer).
"""

from __future__ import annotations

import time
import threading

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .backends import (
    CameraBackend,
    create_backend,
    hw_release_delay,
    CAMERA_TYPES,
    DEFAULT_CAMERA_TYPE,
)
from .registers import CameraServiceRegisters

# Модуль frame_id для wrap-around
_FRAME_ID_MODULO = 121

# Публикация actual-телеметрии — раз в N кадров (чтобы не спамить state store)
_ACTUAL_PUBLISH_EVERY = 30


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

    register_class = CameraServiceRegisters

    inputs = []
    outputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="BGR-кадр с камеры",
        ),
    ]

    commands = {
        "start_capture": "cmd_start_capture",
        "stop_capture": "cmd_stop_capture",
        "set_camera_type": "cmd_set_camera_type",
        "set_fps": "cmd_set_fps",
        "set_resolution": "cmd_set_resolution",
        "set_device_id": "cmd_set_device_id",
        "set_camera_index": "cmd_set_camera_index",
        "enum_devices": "cmd_enum_devices",
        # Live-управление параметрами (Phase 2): register subset → set_config,
        # полный каталог (Services-фасад) → set_param. actual → get_actual.
        "set_config": "cmd_set_config",
        "set_param": "cmd_set_param",
        "set_mjpg": "cmd_set_mjpg",
        "get_actual": "cmd_get_actual",
        "hik_open": "cmd_hik_open",
        "hik_close": "cmd_hik_close",
        "hik_start_grabbing": "cmd_hik_start_grabbing",
        "hik_stop_grabbing": "cmd_hik_stop_grabbing",
        "hik_get_parameters": "cmd_hik_get_parameters",
        "hik_set_parameters": "cmd_hik_set_parameters",
    }

    # --- Lifecycle ---

    def configure(self, ctx: PluginContext) -> None:
        """Настроить параметры камеры."""
        cfg = ctx.config

        # Tunable subset — через managed register (GUI видит, live-правка).
        self._reg = self._init_register(ctx)

        self._camera_type: str = cfg.get("camera_type", DEFAULT_CAMERA_TYPE)
        self._camera_id: int = cfg.get("camera_id", 0)
        self._device_id: int = cfg.get("device_id", 0)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._auto_start: bool = cfg.get("auto_start", False)
        self._camera_index: int = cfg.get("camera_index", 0)
        self._hik_width: int = cfg.get("hikvision_resolution_width", 1920)
        self._hik_height: int = cfg.get("hikvision_resolution_height", 1080)
        self._sim_image: str | None = cfg.get("simulator_image_path")
        self._file_path: str = cfg.get("file_source_path", "")
        # Полный набор CAP_PROP-параметров из рецепта (desired, применяются при open).
        self._params: dict = dict(cfg.get("params", {}) or {})

        # StateProxy для публикации actual-телеметрии (может быть None)
        self._state_proxy = ctx.state_proxy

        # Состояние
        self._backend: CameraBackend | None = None
        self._backend_lock = threading.Lock()
        self._is_capturing = False
        self._frame_count = 0
        self._ctx = ctx

        ctx.log_info(
            f"CameraServicePlugin[{self._camera_id}]: type={self._camera_type}, "
            f"{self._width}x{self._height}, fps={self._reg.fps}, mjpg={self._reg.mjpg}"
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

        # Публикация actual-параметров (что камера реально применила) в state store.
        if self._frame_count % _ACTUAL_PUBLISH_EVERY == 0:
            self._publish_actual()

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
            # Webcam-специфичные tunable (игнорируются другими backend'ами)
            "fps": self._reg.fps,
            "mjpg": self._reg.mjpg,
            "params": dict(self._params),
        }

    def _do_start_capture(self, ctx: PluginContext) -> None:
        """Создать backend (если нет) и запустить захват."""
        if self._is_capturing:
            return

        # Арбитраж: если hikvision — попросить hub освободить handle (best-effort)
        if self._camera_type == "hikvision":
            self._hik_release_best_effort(ctx)

        with self._backend_lock:
            if self._backend is None:
                self._backend = create_backend(self._camera_type, **self._backend_kwargs())
            self._backend.start()

        self._is_capturing = True
        ctx.log_info(f"CameraServicePlugin[{self._camera_id}]: захват запущен (backend={self._camera_type})")

    def _hik_release_best_effort(self, ctx: PluginContext) -> None:
        """Попросить devices-hub освободить hikvision handle (best-effort, retry 1).

        Деградация: hub недоступен/нет handle → warning, НЕ блокировать старт.
        Контракт: вызывается из командного потока (configure/start), НЕ из produce().
        """
        try:
            from Plugins.hub.device_hub.client import DeviceHubClient

            client = DeviceHubClient(ctx, default_timeout=1.0)
        except Exception:
            ctx.log_info("CameraServicePlugin: DeviceHubClient недоступен, пропускаем hik_release")
            return

        device_id = getattr(self, "_device_id", None) or ""
        args = {"device_id": device_id} if device_id else {}

        for attempt in range(2):  # попытка 0 + retry 1
            try:
                result = client.request("hik_release", args, timeout=1.0)
                if result.get("status") == "ok":
                    ctx.log_info("CameraServicePlugin: hik_release ok")
                    return
                # Ответ error — hub не имеет handle, это нормально
                ctx.log_info(f"CameraServicePlugin: hik_release ответ: {result.get('message', 'ok')}")
                return
            except Exception as exc:
                if attempt == 0:
                    ctx.log_info(f"CameraServicePlugin: hik_release попытка 1 неудачна: {exc}, retry")
                else:
                    ctx.log_warning(f"CameraServicePlugin: hik_release недоступен после retry: {exc}")

    def _do_stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват (backend остаётся, но stop)."""
        self._is_capturing = False
        with self._backend_lock:
            if self._backend:
                self._backend.stop()
        ctx.log_info(f"CameraServicePlugin[{self._camera_id}]: захват остановлен")

    def _do_switch_camera_type(self, new_type: str) -> dict:
        """Горячее переключение backend'а.

        Последовательность: stop → close → hw_delay → create → auto-restart.
        """
        if new_type not in CAMERA_TYPES:
            return {
                "status": "error",
                "error": f"Неизвестный тип камеры: {new_type!r}. Допустимые: {CAMERA_TYPES}",
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
            self._backend = create_backend(self._camera_type, **self._backend_kwargs())

        # Если захват был активен — перезапустить
        if was_capturing:
            with self._backend_lock:
                if self._backend:
                    self._backend.start()
            self._is_capturing = True

        self._ctx.log_info(f"CameraServicePlugin[{self._camera_id}]: переключение {old_type} → {new_type}")
        return {"status": "ok", "camera_type": new_type}

    # --- Live-управление параметрами (Phase 2) ---

    def _webcam_be(self):
        """Вернуть backend, если он поддерживает live-параметры (webcam), иначе None."""
        be = self._backend
        if be is not None and hasattr(be, "set_param"):
            return be
        return None

    def _apply_field(self, name: str, value) -> bool:
        """Применить один tunable-параметр: desired (register/params) + live в backend.

        Источник правды desired: register-поля (для subset) + self._params (полный
        набор CAP_PROP). Применяется на камеру только если backend = webcam и открыт;
        иначе остаётся desired и применится при следующем open (_backend_kwargs).
        """
        if name in type(self._reg).model_fields:
            try:
                setattr(self._reg, name, value)
            except Exception:
                pass
        if name not in ("fps", "mjpg"):
            self._params[name] = value

        with self._backend_lock:
            be = self._webcam_be()
            if be is None:
                return False
            if name == "fps":
                return bool(be.set_fps(int(value)))
            if name == "mjpg":
                return bool(be.set_mjpg(bool(value)))
            return bool(be.set_param(name, value))

    def _publish_actual(self) -> None:
        """Опубликовать actual-параметры (cap.get) в state store."""
        if self._state_proxy is None:
            return
        with self._backend_lock:
            be = self._webcam_be()
            actual = be.get_actual() if be is not None else {}
        if not actual:
            return
        path = f"processes.{self._ctx.process_name}.state.cam.actual"
        self._state_proxy.merge(path, actual)

    # --- Команды (авторегистрация через commands dict) ---

    def cmd_start_capture(self, data: dict) -> dict:
        self._do_start_capture(self._ctx)
        return {"status": "ok"}

    def cmd_stop_capture(self, data: dict) -> dict:
        self._do_stop_capture(self._ctx)
        return {"status": "ok"}

    def cmd_set_camera_type(self, data: dict) -> dict:
        new_type = data.get("camera_type", "")
        return self._do_switch_camera_type(new_type)

    def cmd_set_fps(self, data: dict) -> dict:
        fps = max(1, min(120, int(data.get("fps", self._reg.fps))))
        self._apply_field("fps", fps)
        return {"status": "ok", "fps": fps}

    def cmd_set_resolution(self, data: dict) -> dict:
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

    def cmd_set_device_id(self, data: dict) -> dict:
        self._device_id = int(data.get("device_id", self._device_id))
        return {"status": "ok", "device_id": self._device_id}

    def cmd_set_camera_index(self, data: dict) -> dict:
        self._camera_index = int(data.get("camera_index", self._camera_index))
        return {"status": "ok", "camera_index": self._camera_index}

    def cmd_enum_devices(self, data: dict) -> dict:
        with self._backend_lock:
            if self._backend:
                result = self._backend.handle_command("enum_devices", data)
                return result or {"status": "ok", "devices": []}
        return {"status": "ok", "devices": []}

    def cmd_set_config(self, data: dict) -> dict:
        """Generic field-set (inspector subset): {field: value} → _apply_field.

        Переопределяет авто-generic из ProcessModulePlugin: помимо записи в register
        выполняет side-effect на камеру (cap.set).
        """
        applied: dict = {}
        for field_name, value in data.items():
            self._apply_field(field_name, value)
            applied[field_name] = value
        return {"status": "ok", "applied": applied}

    def cmd_set_param(self, data: dict) -> dict:
        """Применить один параметр из полного каталога (Services-фасад).

        data: {"name": <ключ WEBCAM_PARAMS>, "value": <значение>}.
        """
        name = data.get("name", "")
        if not name:
            return {"status": "error", "error": "name required"}
        ok = self._apply_field(name, data.get("value"))
        return {"status": "ok", "applied": ok, "name": name}

    def cmd_set_mjpg(self, data: dict) -> dict:
        """Переключить MJPG-кодек."""
        on = bool(data.get("on", True))
        self._apply_field("mjpg", on)
        return {"status": "ok", "mjpg": on}

    def cmd_get_actual(self, data: dict) -> dict:
        """Прочитать actual-параметры камеры (cap.get) on-demand."""
        with self._backend_lock:
            be = self._webcam_be()
            actual = be.get_actual(data.get("names")) if be is not None else {}
        return {"status": "ok", "actual": actual}

    # hik_* passthrough команды — делегирование в backend (strip hik_ prefix)

    def _hik_passthrough(self, hik_cmd: str, data: dict) -> dict:
        """Общий обработчик hik_* команд."""
        if self._camera_type != "hikvision":
            return {
                "status": "error",
                "error": f"Команда {hik_cmd} доступна только для hikvision backend",
            }
        backend_cmd = hik_cmd[4:]  # strip "hik_" prefix
        with self._backend_lock:
            if self._backend:
                result = self._backend.handle_command(backend_cmd, data)
                return result or {"status": "ok"}
        return {"status": "error", "error": "Backend не инициализирован"}

    def cmd_hik_open(self, data: dict) -> dict:
        return self._hik_passthrough("hik_open", data)

    def cmd_hik_close(self, data: dict) -> dict:
        return self._hik_passthrough("hik_close", data)

    def cmd_hik_start_grabbing(self, data: dict) -> dict:
        return self._hik_passthrough("hik_start_grabbing", data)

    def cmd_hik_stop_grabbing(self, data: dict) -> dict:
        return self._hik_passthrough("hik_stop_grabbing", data)

    def cmd_hik_get_parameters(self, data: dict) -> dict:
        return self._hik_passthrough("hik_get_parameters", data)

    def cmd_hik_set_parameters(self, data: dict) -> dict:
        return self._hik_passthrough("hik_set_parameters", data)
