"""Мелкие утилиты лог-слоя + re-export FallbackLogger для старых импортов."""

from typing import Any, Callable, Tuple, Union

from .._fallback import FallbackLogger

#: Что принимает ``LoggerCore.log`` вместо готовой строки (Ф1.4).
#: Callable вызывается ТОЛЬКО после гейта — в этом смысл типа.
LogMessage = Union[str, Callable[[], str]]

__all__ = ["FallbackLogger", "LogMessage", "apply_format", "safe_exception_message"]

#: Обрезка длинных сообщений исключений (защита state-дерева от гигантских строк).
MAX_EXCEPTION_MESSAGE_LEN = 500


def safe_exception_message(exc: BaseException) -> str:
    """Текст исключения, НЕ веря его ``__str__``.

    ``str(exc)`` — чужой код: у исключения с самодельным ``__str__`` он имеет
    право бросить. Ревью Task 1.3a воспроизвело цену этого доверия: строка
    стояла первой в ``HealthState.report_error``, до лока и до записи в
    плоскость ошибок, и исключение с бросающим ``__str__`` уносило наружу
    ``ValueError`` при ``errors=0`` и нуле записей — то есть отказ ЧУЖОГО
    механизма стоил ВЕСЬ факт.

    Живёт здесь, а не в ``health/state.py``, с Task 1.3b: тот же вход появился
    у второго держателя механизма «факт всегда + голос по окну»
    (``ObservableMixin.report_error``), а две копии защиты разъехались бы молча
    — ровно тем дефектом, которым в Task 1.3a оказалось число снятых ручных
    копий окна, записанное словом в трёх местах.
    """
    try:
        return str(exc)[:MAX_EXCEPTION_MESSAGE_LEN]
    except Exception:  # noqa: BLE001 — текст не имеет права стоить учёт факта
        return f"<{type(exc).__name__}: __str__ недоступен>"


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
