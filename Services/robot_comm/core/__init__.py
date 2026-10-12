"""core-слой robot_comm — клиент, карта регистров, конфиг, типы."""

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
