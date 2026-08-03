"""Мелкие утилиты лог-слоя + re-export FallbackLogger для старых импортов."""

from typing import Any, Callable, Tuple, Union

from .._fallback import FallbackLogger

#: Что принимает ``LoggerCore.log`` вместо готовой строки (Ф1.4).
#: Callable вызывается ТОЛЬКО после гейта — в этом смысл типа.
LogMessage = Union[str, Callable[[], str]]

__all__ = ["FallbackLogger", "LogMessage", "apply_format"]


def apply_format(message: str, args: Tuple[Any, ...]) -> str:
    """Применить ``%``-формат так же, как stdlib, но не теряя сообщение на сбое.

    Кривой формат (``"%d" % "строка"``) в stdlib поднимает шум в ``sys.stderr``
    и запись НЕ пишет. Здесь сообщение и аргументы отдаются как есть: потерять
    строку из-за опечатки в шаблоне хуже, чем записать её некрасиво. Это
    поведение уже было у фасада (бывший ``StdLoggerFacade._format``, удалён в
    Ф6.х.2 как мёртвый) — при Ф1.4 форматирование
    переехало внутрь менеджера (после гейта), и правило поехало вместе с ним,
    а не размножилось второй копией.
    """
    if not args:
        return message
    try:
        return message % args
    except (TypeError, ValueError):
        return f"{message} {args!r}"
