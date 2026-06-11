"""VfdCommService — карточка сервиса ПЧ в каталоге, БЕЗ собственного транспорта.

ПЧ висит за мостом робота: транспортом владеет плагин robot_io (runtime
robot_comm), клиента ПЧ создаёт плагин vfd_control. Сервис — метаданные/статус.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.service_module import register_service

from Services.vfd_comm.core.config import VfdConfig


@register_service(name="vfd_comm")
class VfdCommService:
    """Карточка ПЧ INVT GD20 для каталога сервисов."""

    name: str = "vfd_comm"

    def __init__(self) -> None:
        self.status: str = "stopped"
        self._config: VfdConfig | None = None

    def start(self, config: dict) -> bool:
        """Принять доменный конфиг как метаданные. Транспорт НЕ открывается."""
        self._config = VfdConfig.from_dict(config or {})
        self.status = "ready"
        return True

    def stop(self) -> bool:
        """Сбросить карточку."""
        self._config = None
        self.status = "stopped"
        return True

    def get_status(self) -> dict:
        """Статус карточки."""
        data: dict[str, Any] = {
            "state": self.status,
            "service": self.name,
            "transport": "bridge via robot_comm (RegisterTransport)",
        }
        if self._config is not None:
            data["config"] = self._config.to_dict()
        return data
