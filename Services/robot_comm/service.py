"""RobotCommService — карточка сервиса в каталоге, БЕЗ собственного соединения.

ВАЖНО: владелец соединения — процесс ``devices`` (always-on, DeviceHubPlugin).
Раньше владельцем был плагин robot_io через runtime.py (co-location),
теперь runtime.py удалён — все операции идут по IPC через DeviceHubClient.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module import register_service

from Services.robot_comm.core.config import RobotConfig


@register_service(name="robot_comm")
class RobotCommService:
    """Карточка робота Delta для каталога сервисов (метаданные + статус)."""

    name: str = "robot_comm"

    def __init__(self) -> None:
        self.status: str = "stopped"
        self._config: RobotConfig | None = None

    def start(self, config: dict) -> bool:
        """Принять конфиг (host/port/...) как метаданные. Соединение НЕ открывается."""
        self._config = RobotConfig.from_dict(config or {})
        self.status = "ready"
        return True

    def stop(self) -> bool:
        """Сбросить карточку. Живое соединение (если есть) закрывает процесс devices."""
        self._config = None
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Статус карточки (метаданные)."""
        data: dict[str, Any] = {"state": self.status, "service": self.name, "owner": "process devices"}
        if self._config is not None:
            data["robot"] = self._config.describe()
        return data
