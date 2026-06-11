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
"""

from Services.modbus import MODBUS_AVAILABLE as ROBOT_AVAILABLE

from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.core.datatypes import DrawPoint, JobEcho, RobotPosition, Telemetry
from Services.robot_comm.core.registers import build_register_map
from Services.robot_comm.errors import RobotCommError, RobotJobError, RobotNotConnectedError
from Services.robot_comm.interfaces import DeviceTransport, RobotClientProtocol

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


def __getattr__(name: str):
    """Ленивая загрузка service-слоя (тянет multiprocess_framework)."""
    if name == "RobotCommService":
        from Services.robot_comm.service import RobotCommService

        return RobotCommService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
