"""Пакет драйвера робота Delta v2 (T5.3f f2): ``RobotDriverV2`` и его внутренние модули.

Purpose:
    Путь ``Services.device_hub.drivers.robot_driver_v2`` прежний (``manager.py`` его не меняет); модуль-файл стал
    пакетом: ``driver`` (ядро ``_RobotDriverCore``: подключение, тик), ``state`` (состояние под одним замком),
    ``texts``, ``args``, ``tlm`` и миксины операций. ``RobotDriverV2`` собирается здесь из ядра и миксинов;
    реэкспорт — только шесть имён ниже; константы и ``save_params`` читаются из своих модулей.

Public API:
    ``RobotDriverV2``; ``RobotState``, ``RobotStateView``, ``JogView``, ``_JogRun`` и ``_parse_tlm`` — внутренние
    имена, на которые опираются тесты (не SPI хаба).

Stability: lite
"""

from Services.device_hub.drivers.robot_driver_v2.jobs import JobMixin
from Services.device_hub.drivers.robot_driver_v2.jog import JogMixin
from Services.device_hub.drivers.robot_driver_v2.ops import OPS, OpsMixin
from Services.device_hub.drivers.robot_driver_v2.params import ParamMixin
from Services.device_hub.drivers.robot_driver_v2.programs import ProgramMixin
from Services.device_hub.drivers.robot_driver_v2.state import JogView, RobotState, RobotStateView, _JogRun
from Services.device_hub.drivers.robot_driver_v2.stop import StopMixin
from Services.device_hub.drivers.robot_driver_v2.tlm import _parse_tlm
from Services.device_hub.drivers.robot_driver_v2.driver import _RobotDriverCore

__all__ = ["JogView", "RobotDriverV2", "RobotState", "RobotStateView", "_JogRun", "_parse_tlm"]


class RobotDriverV2(StopMixin, JogMixin, ProgramMixin, JobMixin, ParamMixin, OpsMixin, _RobotDriverCore):
    """Драйвер робота Delta v2: ядро ``_RobotDriverCore`` (``driver``) и миксины операций; описание — в ``driver``."""


RobotDriverV2._OPS = OPS
