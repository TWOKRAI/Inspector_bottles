"""Ошибки сервиса robot_comm.

Транспортные ошибки (обрыв, таймаут, exception-ответ) приходят из
``Services.modbus`` как ``ModbusDriverError`` и НЕ оборачиваются — единая
иерархия транспорта на все сервисы устройств. Здесь — только доменные ошибки
уровня робота.
"""

from __future__ import annotations


class RobotCommError(Exception):
    """Базовая доменная ошибка robot_comm."""


class RobotNotConnectedError(RobotCommError):
    """Клиент робота не опубликован владельцем.

    Возникает в ``runtime.get_client()``, когда плагин-владелец (robot_io) ещё
    не создал/не подключил RobotClient. Потребители (vfd_control, robot_draw,
    calibration) обязаны жить в ОДНОМ процессе с владельцем — runtime-holder
    process-local и через границу процессов не виден.
    """


class RobotJobError(RobotCommError):
    """Ошибка постановки/исполнения CVT-задания (координата вне лимита и т.п.)."""
