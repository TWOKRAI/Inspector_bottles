# -*- coding: utf-8 -*-
"""mjpeg_sink — раздача последнего кадра по HTTP MJPEG (Ф1 плана ``line-sim``).

Пара с ``Plugins/sim/robot_host`` внутри одного семейства сим-плагинов: сток
конца цепочки процесса ``camera`` (после ``camera_service``), без сети в
``configure()`` — сервер поднимается только в ``start()`` (Task 1.2 плана).
"""

from .plugin import MjpegSinkPlugin

__all__ = ["MjpegSinkPlugin"]
