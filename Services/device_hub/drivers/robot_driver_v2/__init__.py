"""Пакет драйвера робота Delta v2 (T5.3f f2): ``RobotDriverV2`` и его внутренние модули.

Purpose:
    Путь ``Services.device_hub.drivers.robot_driver_v2`` прежний (``manager.py`` его не меняет); модуль-файл стал
    пакетом: ``driver`` (класс, подключение, тик), ``state`` (состояние под одним замком), ``texts``, ``args``, ``tlm``
    и миксины операций. Реэкспорт — только шесть имён ниже; константы и ``save_params`` читаются из своих модулей.

Public API:
    ``RobotDriverV2``; ``RobotState``, ``RobotStateView``, ``JogView``, ``_JogRun`` и ``_parse_tlm`` — внутренние
    имена, на которые опираются тесты (не SPI хаба).

Stability: lite
"""

from Services.device_hub.drivers.robot_driver_v2.state import JogView, RobotState, RobotStateView, _JogRun
from Services.device_hub.drivers.robot_driver_v2.tlm import _parse_tlm
from Services.device_hub.drivers.robot_driver_v2.driver import RobotDriverV2

__all__ = ["JogView", "RobotDriverV2", "RobotState", "RobotStateView", "_JogRun", "_parse_tlm"]
