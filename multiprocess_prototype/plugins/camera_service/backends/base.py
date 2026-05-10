"""CameraBackend Protocol — интерфейс для всех backend'ов камеры."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class CameraBackend(Protocol):
    """Протокол backend'а камеры.

    Контракт:
        start()         — подготовить устройство к захвату
        capture_frame() — захватить один кадр (BGR ndarray или None)
        stop()          — приостановить захват (ресурсы удерживаются)
        close()         — полностью освободить устройство
        handle_command()— обработать специфичную для backend'а команду
    """

    def capture_frame(self) -> np.ndarray | None:
        """Захватить один кадр. None если нет данных."""
        ...

    def start(self) -> None:
        """Запустить захват."""
        ...

    def stop(self) -> None:
        """Приостановить захват (ресурсы удерживаются)."""
        ...

    def close(self) -> None:
        """Полностью освободить устройство."""
        ...

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """Обработать команду, специфичную для backend'а.

        Args:
            cmd: имя команды (например, "enum_devices")
            data: параметры команды

        Returns:
            Результат или None если команда не поддерживается.
        """
        ...
