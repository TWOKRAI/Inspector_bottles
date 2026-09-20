# -*- coding: utf-8 -*-
"""robot_host — хост ``SimRobotServer`` (Modbus TCP) для процесса ``robot`` сима.

Импорт пакета исполняет ``@register_plugin`` и НЕ тянет ``pymodbus`` в
``sys.modules`` — SDK трогает только ``Services/robot_comm/server/sim_robot.py``,
лениво, внутри ``configure``/``start`` плагина (Task 1.1 плана ``line-sim``).
"""

from .plugin import SimRobotHostPlugin

__all__ = ["SimRobotHostPlugin"]
