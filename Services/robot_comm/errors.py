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
    """Клиент робота не подключён.

    Возникает, когда операция требует подключённого RobotClient, но процесс
    devices ещё не установил соединение (device_connect не вызван или failed).
    """


class RobotJobError(RobotCommError):
    """Ошибка постановки/исполнения CVT-задания (координата вне лимита и т.п.)."""
