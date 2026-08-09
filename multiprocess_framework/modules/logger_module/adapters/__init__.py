# -*- coding: utf-8 -*-
"""Виды поверх единственного писателя.

Здесь лежит ровно один публичный вид — :class:`StdLoggerFacade` и его фабрика
``get_std_logger``: именованная точка входа со stdlib-подобным интерфейсом, за
которой стоит тот же ``LoggerCore``.

Прежний `LoggerAdapter` снят в 2.2: у него не было ни одного потребителя
(`setup()` не вызывался, `log_with_auto_scope` никто не звал), зато внутри
жила **вторая таблица** «уровень → scope», расходившаяся с канонической по
``DEBUG`` (``business`` против ``debug``). Подключи его кто-нибудь — и
DEBUG-записи молча уехали бы в чужой scope.
"""

from .std_facade import StdLoggerFacade, get_std_logger

__all__ = [
    "StdLoggerFacade",
    "get_std_logger",
]
