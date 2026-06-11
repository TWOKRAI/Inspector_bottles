"""Ошибки сервиса vfd_comm.

Транспортные ошибки приходят из ``Services.modbus`` как ``ModbusDriverError``
и не оборачиваются. Здесь — только доменные ошибки уровня ПЧ.
"""

from __future__ import annotations


class VfdCommError(Exception):
    """Базовая доменная ошибка vfd_comm."""


class VfdFrequencyError(VfdCommError):
    """Частота вне допустимого диапазона конфига."""


class VfdBridgeStaleError(VfdCommError):
    """Зеркало ПЧ устарело: heartbeat моста не растёт между опросами.

    Через мост робота зеркало 0x1210+ обновляется только при обработке
    VFD_FLAG — если heartbeat замер при регулярном poll(), значит робот
    (Lua-мост) или линия RS-485 не отвечают.
    """
