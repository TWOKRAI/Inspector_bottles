"""RobotCommService — карточка сервиса в каталоге, БЕЗ собственного соединения.

ВАЖНО: в отличие от эталонного ModbusService, этот сервис НЕ создаёт device и
НЕ коннектится. Владелец соединения — исключительно плагин robot_io (модель
владельца, см. runtime.py): второй TCP-master к одному mailbox робота дал бы
гонку по проводу, которую локальные Lock'и не снимают. Все операции с роботом
из GUI — round-trip командами к плагину.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module import register_service

from Services.robot_comm import runtime
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
        """Сбросить карточку. Живое соединение (если есть) закрывает владелец-плагин."""
        self._config = None
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Статус карточки + (если владелец опубликовал клиент) живой статус транспорта."""
        data: dict[str, Any] = {"state": self.status, "service": self.name, "owner": "plugin robot_io"}
        if self._config is not None:
            data["robot"] = self._config.describe()
        client = runtime.peek_client()
        if client is not None:
            data["client"] = client.get_status()
        return data
