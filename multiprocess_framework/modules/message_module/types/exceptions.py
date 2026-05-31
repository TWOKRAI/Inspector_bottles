# -*- coding: utf-8 -*-
"""
Исключения модуля Message.
"""


class MessageValidationError(ValueError):
    """Исключение для ошибок валидации сообщений."""

    pass


class AddressValidationError(MessageValidationError):
    """Невалидный иерархический адрес в Message.targets.

    Наследует MessageValidationError, поэтому существующие обработчики
    валидации сообщений ловят его без изменений.
    """

    pass
