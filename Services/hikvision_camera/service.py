"""HikvisionCameraService — минимальный shell-класс для ServiceRegistry.

Реализует интерфейс IService (Phase 3): start / stop / get_status.
Детальная реализация с реальным SDK Hikvision (ISAPI/HCNetSDK) — Phase 4+.
"""

from __future__ import annotations

from multiprocess_framework.modules.service_module import IService, register_service


@register_service(name="Services.hikvision_camera")
class HikvisionCameraService:
    """Shell-сервис камеры Hikvision.

    Хранит статус подключения; реальный бэкенд (HCNetSDK/ISAPI) — Phase 4+.

    Атрибуты:
        name   — идентификатор сервиса для ServiceRegistry.
        status — текущее состояние ("stopped" | "running").
    """

    name: str = "Services.hikvision_camera"

    def __init__(self) -> None:
        """Инициализация."""
        self.status: str = "stopped"

    # ------------------------------------------------------------------
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------

    def start(self, config: dict) -> bool:
        """Запустить сервис с заданной конфигурацией.

        Args:
            config: параметры подключения (ip, port, user, password и т.п.).

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        # TODO Phase 4+: инициализация HCNetSDK / ISAPI-подключения
        self.status = "running"
        return True

    def stop(self) -> bool:
        """Остановить сервис.

        Returns:
            True при успехе (shell всегда возвращает True).
        """
        # TODO Phase 4+: освободить ресурсы SDK
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Вернуть текущее состояние сервиса.

        Returns:
            Словарь с ключами state и service.
        """
        return {"state": self.status, "service": self.name}

    def __repr__(self) -> str:
        return f"HikvisionCameraService(status={self.status!r})"


# Явная проверка структурной совместимости (runtime, не ABC)
assert isinstance(HikvisionCameraService(), IService), "HikvisionCameraService не удовлетворяет IService Protocol"
