"""Команды и register-хендлеры для CameraProcess.

Фабричные функции получают зависимости как аргументы и возвращают dict.
process.py вызывает build_command_table / build_register_handlers при инициализации.
"""
from __future__ import annotations

import time


def build_command_table(service, worker_mgr) -> dict:
    """Возвращает {command_name: handler} для command_manager.register_command().

    Args:
        service: CameraService instance.
        worker_mgr: WorkerManager для управления capture_worker.
    """

    # --- Wrapper-функции (доп. логика: пауза/resume воркера, cross-backend) ---

    def cmd_set_camera_type(data: dict) -> dict:
        """Переключить тип камеры. Пауза воркера → switch → auto-resume если был захват."""
        was_capturing = service.is_capturing
        worker_mgr.pause_worker("capture_worker")
        time.sleep(0.05)  # дать воркеру завершить текущую итерацию
        result = service.switch_camera_type(data.get("camera_type", "simulator"))
        # Авто-возобновить захват после успешного переключения
        if was_capturing and result.get("status") == "ok":
            start_result = service.start_capture({})
            if start_result and start_result.get("status") != "error":
                worker_mgr.resume_worker("capture_worker")
        return result

    def cmd_start_capture(data: dict) -> dict:
        """Запустить захват: делегация в сервис + resume воркера."""
        result = service.start_capture(data)
        if result and result.get("status") != "error":
            if not worker_mgr.is_worker_running("capture_worker"):
                worker_mgr.start_worker("capture_worker")
            worker_mgr.resume_worker("capture_worker")
        return result or {"status": "error"}

    def cmd_stop_capture(data: dict) -> dict:
        """Остановить захват: пауза воркера + делегация в сервис."""
        if worker_mgr:
            worker_mgr.pause_worker("capture_worker")
        time.sleep(0.05)
        return service.stop_capture(data)

    def cmd_enum_devices(data: dict) -> dict:
        """Перечисление устройств. Cross-backend enum может паузить воркер."""
        payload = dict(data or {})
        backend_hint = payload.get("backend")
        # Если cross-backend enum hikvision при активном webcam — паузим воркер
        if (
            backend_hint == "hikvision"
            and service.current_type == "webcam"
        ):
            worker_mgr.pause_worker("capture_worker")
            result = service.enumerate_devices(payload)
            worker_mgr.resume_worker("capture_worker")
            return result
        return service.enumerate_devices(payload)

    return {
        # С доп. логикой (пауза/resume воркера, cross-backend)
        "set_camera_type": cmd_set_camera_type,
        "start_capture": cmd_start_capture,
        "stop_capture": cmd_stop_capture,
        "enum_devices": cmd_enum_devices,
        "start_grabbing": cmd_start_capture,    # alias (Hikvision SDK)
        "stop_grabbing": cmd_stop_capture,       # alias (Hikvision SDK)
        # Чистая делегация в сервис
        "get_camera_type": lambda _: {"status": "ok", "camera_type": service.current_type},
        "set_fps": service.set_fps,
        "set_resolution": service.set_resolution,
        "set_device_id": service.set_device_id,
        "set_camera_index": service.set_camera_index,
        "set_hikvision_resolution": service.set_hikvision_resolution,
        "open": lambda d: service.handle_hikvision_command("open", d),
        "close": lambda d: service.handle_hikvision_command("close", d),
        "get_parameters": lambda d: service.handle_hikvision_command("get_parameters", d),
        "set_parameters": lambda d: service.handle_hikvision_command("set_parameters", d),
    }


def build_state_config_handlers(service, cmd_set_camera_type) -> dict:
    """Маппинг config field suffix → handler для StateProxy callback.

    Ключи = суффиксы после cameras.{id}.config., значения = callable(value).
    Реюзает те же хендлеры что и build_register_handlers.

    Args:
        service: CameraService instance.
        cmd_set_camera_type: wrapper-функция из build_command_table (нужна для
            поля camera_type, т.к. переключение типа требует паузы воркера).
    """
    return {
        "camera_type": lambda v: cmd_set_camera_type({"camera_type": v}),
        "fps": lambda v: service.set_fps({"fps": v}),
        "resolution_width": lambda v: service.set_resolution({"width": v}),
        "resolution_height": lambda v: service.set_resolution({"height": v}),
        "device_id": lambda v: service.set_device_id({"device_id": v}),
        "camera_index": lambda v: service.set_camera_index({"camera_index": v}),
        "hikvision_resolution_width": lambda v: service.set_hikvision_resolution(
            {"width": v}
        ),
        "hikvision_resolution_height": lambda v: service.set_hikvision_resolution(
            {"height": v}
        ),
        "hikvision_frame_rate": lambda v: service.patch_hikvision_params(
            {"frame_rate": v}
        ),
        "hikvision_exposure_time": lambda v: service.patch_hikvision_params(
            {"exposure_time": v}
        ),
        "hikvision_gain": lambda v: service.patch_hikvision_params({"gain": v}),
    }


def build_register_handlers(service, cmd_set_camera_type) -> dict:
    """Возвращает {field_name: handler} для apply_register_update().

    Маппинг полей регистра на обработчики. Имена полей не совпадают с именами
    команд, payload — одно значение (а не dict).

    Args:
        service: CameraService instance.
        cmd_set_camera_type: wrapper-функция из build_command_table (нужна для
            поля camera_type, т.к. переключение типа требует паузы воркера).
    """
    return {
        "camera_type": lambda v: cmd_set_camera_type({"camera_type": v}),
        "fps": lambda v: service.set_fps({"fps": v}),
        "resolution_width": lambda v: service.set_resolution({"width": v}),
        "resolution_height": lambda v: service.set_resolution({"height": v}),
        "device_id": lambda v: service.set_device_id({"device_id": v}),
        "camera_index": lambda v: service.set_camera_index({"camera_index": v}),
        "hikvision_resolution_width": lambda v: service.set_hikvision_resolution(
            {"width": v}
        ),
        "hikvision_resolution_height": lambda v: service.set_hikvision_resolution(
            {"height": v}
        ),
        "hikvision_frame_rate": lambda v: service.patch_hikvision_params(
            {"frame_rate": v}
        ),
        "hikvision_exposure_time": lambda v: service.patch_hikvision_params(
            {"exposure_time": v}
        ),
        "hikvision_gain": lambda v: service.patch_hikvision_params({"gain": v}),
    }
