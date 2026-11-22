"""HikvisionCameraService — минимальный shell-класс для ServiceRegistry.

Реализует интерфейс IService (Phase 3): start / stop / get_status. Захват камеры — плагин `hikvision`.
"""

from __future__ import annotations

import logging

from multiprocess_framework.modules.service_module import IService, register_service


logger = logging.getLogger(__name__)


@register_service(name="hikvision_camera")
class HikvisionCameraService:
    """Оболочка сервиса камеры Hikvision (F22).

    Захват ведёт плагин `hikvision` (`plugin/plugin.py`, ядро `camera_device`), а не этот класс:
    сервис ничего не запускает и честно называет себя оболочкой.

    Атрибуты:
        name   — идентификатор сервиса для ServiceRegistry.
        status — состояние оболочки; всегда "shell".
    """

    name: str = "hikvision_camera"
    status: str = "shell"

    def __repr__(self) -> str:
        return f"HikvisionCameraService(status={self.status!r})"

    # ------------------------------------------------------------------
    # Публичный API (IService-совместимый)
    # ------------------------------------------------------------------

    def start(self, config: dict) -> bool:
        """Не запускает ничего: оболочка, захват — плагин `hikvision`.

        Returns:
            False всегда.
        """
        logger.warning("HikvisionCameraService.start(): оболочка, захват — плагин `hikvision`")
        return False

    def stop(self) -> bool:
        """Остановка оболочки: освобождать нечего.

        Returns:
            True (повторная остановка безвредна).
        """
        return True

    def get_status(self) -> str:
        """Состояние оболочки.

        Returns:
            "shell" — сервис не ведёт захват.
        """
        return self.status


# Явная проверка структурной совместимости (runtime, не ABC)
assert isinstance(HikvisionCameraService(), IService), "HikvisionCameraService не удовлетворяет IService Protocol"
