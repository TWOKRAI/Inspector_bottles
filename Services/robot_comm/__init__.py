"""robot_comm — сервис устройства «робот Delta» поверх Services/modbus.

Тонкая надстройка над универсальным modbus-модулем: карта регистров
(universal3, пара к cvt_universal_full.lua) + доменные методы. Транспорт —
ModbusDevice (TCP); сам клиент реализует RegisterTransport и служит МОСТОМ
для vfd_comm (ПК -> робот по TCP, робот -> ПЧ по RS-485).

Слои пакета:
    core/    — config, карта регистров, клиент, типы (без фреймворка)
    server/  — sim_core (чистая логика фейк-робота) + TCP sim_robot
    testing/ — FakeRobotTransport для тестов без сети
    service.py — карточка в каталоге сервисов (БЕЗ собственного соединения)
    runtime.py — process-local holder (модель владельца: robot_io)

Graceful degradation: пакет импортируется без pymodbus (ROBOT_AVAILABLE=False);
карта/кодеки/sim_core/FakeRobotTransport работают всегда.

Импорт ленивый (PEP 562, T3.6): пакет и ``core`` не грузят клиента, ``Services.modbus``
и pymodbus, пока не запрошено имя, которое из них приходит. ``import
Services.robot_comm.programs`` поэтому лёгкий.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Services.modbus import MODBUS_AVAILABLE as ROBOT_AVAILABLE
    from Services.robot_comm.core.client import RobotClient
    from Services.robot_comm.core.config import RobotConfig
    from Services.robot_comm.core.datatypes import DrawPoint, JobEcho, RobotPosition, Telemetry
    from Services.robot_comm.core.registers import build_register_map
    from Services.robot_comm.errors import RobotCommError, RobotJobError, RobotNotConnectedError
    from Services.robot_comm.interfaces import DeviceTransport, RobotClientProtocol
    from Services.robot_comm.service import RobotCommService as RobotCommService

__all__ = [
    "RobotClient",
    "RobotConfig",
    "RobotPosition",
    "Telemetry",
    "JobEcho",
    "DrawPoint",
    "RobotClientProtocol",
    "DeviceTransport",
    "RobotCommError",
    "RobotJobError",
    "RobotNotConnectedError",
    "build_register_map",
    "ROBOT_AVAILABLE",
]

# Имя -> (модуль, атрибут). RobotCommService вне __all__: service-слой тянет multiprocess_framework.
_LAZY: dict[str, tuple[str, str]] = {
    "RobotClient": ("Services.robot_comm.core.client", "RobotClient"),
    "RobotConfig": ("Services.robot_comm.core.config", "RobotConfig"),
    "RobotPosition": ("Services.robot_comm.core.datatypes", "RobotPosition"),
    "Telemetry": ("Services.robot_comm.core.datatypes", "Telemetry"),
    "JobEcho": ("Services.robot_comm.core.datatypes", "JobEcho"),
    "DrawPoint": ("Services.robot_comm.core.datatypes", "DrawPoint"),
    "RobotClientProtocol": ("Services.robot_comm.interfaces", "RobotClientProtocol"),
    "DeviceTransport": ("Services.robot_comm.interfaces", "DeviceTransport"),
    "RobotCommError": ("Services.robot_comm.errors", "RobotCommError"),
    "RobotJobError": ("Services.robot_comm.errors", "RobotJobError"),
    "RobotNotConnectedError": ("Services.robot_comm.errors", "RobotNotConnectedError"),
    "build_register_map": ("Services.robot_comm.core.registers", "build_register_map"),
    "ROBOT_AVAILABLE": ("Services.modbus", "MODBUS_AVAILABLE"),
    "RobotCommService": ("Services.robot_comm.service", "RobotCommService"),
}


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
