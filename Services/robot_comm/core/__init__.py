"""core-слой robot_comm — клиент, карта регистров, конфиг, типы.

Импорт ленивый (PEP 562, T3.6): ``import Services.robot_comm.core.protocol_v2`` не грузит
клиентов и pymodbus; имя из ``__all__`` загружается при первом обращении.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Services.robot_comm.core.client import RobotClient
    from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2
    from Services.robot_comm.core.config import RobotConfig
    from Services.robot_comm.core.datatypes import DrawPoint, JobEcho, RobotPosition, Telemetry
    from Services.robot_comm.core.registers import build_register_map

__all__ = [
    "RobotClient",
    "RobotClientV2",
    "ClientV2Config",
    "RobotConfig",
    "RobotPosition",
    "Telemetry",
    "JobEcho",
    "DrawPoint",
    "build_register_map",
]

# Имя -> (модуль, атрибут).
_LAZY: dict[str, tuple[str, str]] = {
    "RobotClient": ("Services.robot_comm.core.client", "RobotClient"),
    "RobotClientV2": ("Services.robot_comm.core.client_v2", "RobotClientV2"),
    "ClientV2Config": ("Services.robot_comm.core.client_v2", "ClientV2Config"),
    "RobotConfig": ("Services.robot_comm.core.config", "RobotConfig"),
    "RobotPosition": ("Services.robot_comm.core.datatypes", "RobotPosition"),
    "Telemetry": ("Services.robot_comm.core.datatypes", "Telemetry"),
    "JobEcho": ("Services.robot_comm.core.datatypes", "JobEcho"),
    "DrawPoint": ("Services.robot_comm.core.datatypes", "DrawPoint"),
    "build_register_map": ("Services.robot_comm.core.registers", "build_register_map"),
}


# Под `not TYPE_CHECKING`: модульный __getattr__ иначе делает для pyright любое имя существующим (Any),
# и опечатка в импорте перестаёт ловиться (ревью T3.6 р.1).
if not TYPE_CHECKING:

    def __getattr__(name: str) -> Any:
        """Загрузить имя при первом обращении и закэшировать в пространстве модуля."""
        target = _LAZY.get(name)
        if target is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(importlib.import_module(target[0]), target[1])
        globals()[name] = value
        return value

    def __dir__() -> list[str]:
        return sorted(set(globals()) | set(__all__))
