"""HikvisionDriver — control-only драйвер камеры Hikvision для device_hub.

Lazy import Services.hikvision_camera (без SDK -> call возвращает ошибку).
Кадры НЕ здесь (capture-плагин -> SHM, как сейчас).

Операции: enum, open, close, get_params, set_params, release.
tick() — лёгкий snapshot (opened/serial).
"""

from __future__ import annotations

from typing import Any

from Services.device_hub.drivers.base import BaseDeviceDriver


class HikvisionDriver(BaseDeviceDriver):
    """Драйвер камеры Hikvision: control-only (enum/open/close/params).

    Args:
        entry:    DeviceEntry с kind=hikvision.
        protocol: None (hikvision не использует YAML-протоколы).
    """

    kind = "hikvision"

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(entry, protocol, **kwargs)
        self._camera: Any = None
        self._serial: str = entry.params.get("serial", "")
        self._sdk_available: bool = False

        # Проверяем доступность SDK (lazy)
        try:
            from Services.hikvision_camera import HikvisionCamera  # noqa: F401

            self._sdk_available = True
        except Exception:
            self._sdk_available = False

    # ------------------------------------------------------------------ #
    # Соединение
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        """Камера открыта."""
        if self._camera is None:
            return False
        try:
            from Services.hikvision_camera import CameraState

            # A-14 (bug-hunt 2026-07-20): CameraState.OPENED не существует
            # (реальные значения: CLOSED/OPEN/GRABBING) — AttributeError
            # глотался нижним except, is_connected был всегда False.
            # "Открыта" = OPEN (настроена, но не захватывает) ИЛИ GRABBING
            # (активный захват) — оба состояния означают открытый handle.
            return self._camera.state in (CameraState.OPEN, CameraState.GRABBING)
        except Exception:
            return False

    def connect(self) -> bool:
        """Открыть камеру по serial."""
        if not self._sdk_available:
            self._last_quality = "bad"
            return False
        try:
            from Services.hikvision_camera import HikvisionCamera

            if self._camera is None:
                self._camera = HikvisionCamera()
            self._camera.open(self._serial)
            self._last_quality = "good"
            return True
        except Exception:
            self._record_err()
            self._last_quality = "bad"
            return False

    def disconnect(self) -> None:
        """Закрыть камеру."""
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception:
                pass
        self._last_quality = "bad"

    # ------------------------------------------------------------------ #
    # Tick
    # ------------------------------------------------------------------ #

    def tick(self, stop_event: Any = None) -> dict | None:
        """Лёгкий snapshot: opened/serial."""
        return self.snapshot(
            data={"opened": self.is_connected, "serial": self._serial},
            quality="good" if self.is_connected else "bad",
        )

    # ------------------------------------------------------------------ #
    # Call
    # ------------------------------------------------------------------ #

    def call(self, op: str, args: dict) -> dict:
        """Диспетчер операций Hikvision."""
        if not self._sdk_available:
            return {"status": "error", "message": "SDK Hikvision недоступен"}
        handler = self._OPS.get(op)
        if handler is None:
            return {"status": "error", "message": f"Неизвестная операция Hikvision: {op!r}"}
        try:
            return handler(self, args)
        except Exception as exc:
            self._record_err()
            return {"status": "error", "message": str(exc)}

    def _op_enum(self, _args: dict) -> dict:
        from Services.hikvision_camera import enum_devices

        devices = enum_devices()
        return {
            "status": "ok",
            "devices": [{"serial": d.serial_number, "model": d.model_name, "ip": d.ip_address} for d in devices],
        }

    def _op_open(self, args: dict) -> dict:
        serial = args.get("serial", self._serial)
        if not serial:
            return {"status": "error", "message": "не указан serial"}
        self._serial = serial
        ok = self.connect()
        return {"status": "ok" if ok else "error"}

    def _op_close(self, _args: dict) -> dict:
        self.disconnect()
        return {"status": "ok"}

    def _op_get_params(self, _args: dict) -> dict:
        if self._camera is None or not self.is_connected:
            return {"status": "error", "message": "камера не открыта"}
        from Services.hikvision_camera import CameraParameters

        params = CameraParameters(self._camera)
        return {"status": "ok", "params": params.get_all()}

    def _op_set_params(self, args: dict) -> dict:
        if self._camera is None or not self.is_connected:
            return {"status": "error", "message": "камера не открыта"}
        from Services.hikvision_camera import CameraParameters

        params = CameraParameters(self._camera)
        for key, value in args.items():
            if key != "device_id":
                params.set(key, value)
        return {"status": "ok"}

    def _op_release(self, _args: dict) -> dict:
        self.disconnect()
        self._camera = None
        return {"status": "ok"}

    _OPS: dict[str, Any] = {
        "enum": _op_enum,
        "open": _op_open,
        "close": _op_close,
        "get_params": _op_get_params,
        "set_params": _op_set_params,
        "release": _op_release,
    }
