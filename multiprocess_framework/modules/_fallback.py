"""Цикло-безопасная дверь к именованному виду наблюдаемости.

**Это НЕ писатель (2.2).** Раньше `FallbackLogger` был третьей реализацией
одной мысли: держал имя, лениво искал процессный `LoggerManager` и уходил в
stdlib, если менеджера нет, — ровно то, что делает
:class:`~.logger_module.adapters.std_facade.StdLoggerFacade`. Две копии одной
мысли уже стоили Ф2.1 трёх отдельных починок ОДНОГО дефекта (запись теряла имя
источника). Теперь здесь остался лишь ленивый **handle**: он делегирует
единственному виду и ничего сам не решает.

**Зачем handle вообще нужен, если есть `get_std_logger`.** Модули вроде
`base_manager/adapters/base_adapter.py` создают логгер НА УРОВНЕ МОДУЛЯ, а
импортировать в этот момент `logger_module` нельзя. Это не осторожность, это
воспроизведено слом-инъекцией 2026-07-27 — подъём импорта на уровень модуля
даёт::

    ImportError: cannot import name 'ObservableMixin' from partially
    initialized module 'multiprocess_framework.modules.base_manager'
    (most likely due to a circular import)

Цепочка: `logger_module/__init__` → `channel_routing_module` → `base_manager` →
`base_adapter` → сюда, когда `base_manager` собран наполовину.

**Мало держать импорт внутри метода — нельзя резолвить и в конструкторе.**
Вторая инъекция (импорт оставлен в методе, но вызван из `__init__`) даёт ту же
ошибку: `base_adapter` создаёт handle на уровне модуля, то есть `__init__`
исполняется внутри того же окна. Отсюда точное правило: объект конструируется
без единого импорта, вид подтягивается **при первой записи**. Ровно так же
поступал прежний `FallbackLogger._lm()` — приём сохранён, дублирование убрано.

Использование не изменилось:

    from ..._fallback import FallbackLogger
    _logger = FallbackLogger(__name__)

Что изменилось по поведению:

* ``%``-склейка больше НЕ выполняется до гейта. Прежний ``_fmt`` собирал строку
  перед передачей менеджеру — то есть все 13 utility-классов платили полное
  форматирование за записи, которые гейт отклоняет. Это тот же дефект, что Ф1.5
  чинила в фасаде; сюда исправление доехало только сейчас.
* имя stdlib-логгера сохранено ТОЧНО (``multiprocess_framework.modules...``),
  без префикса ``mpf.`` — иначе после падения менеджера записи ушли бы под
  другим именем, и искать их пришлось бы не там.
"""

from typing import Any, Optional

__all__ = ["FallbackLogger", "emergency_log"]


def emergency_log(name: str, level: str, message: str, *args: Any) -> None:
    """Аварийный выход: stdlib НАПРЯМУЮ, никогда через менеджер.

    Второй (и последний) писатель системы. Нужен там, где о поломке сообщает
    тот, кто сломался: маршрут наблюдаемости не может рассказать о собственном
    отказе собой же — получилась бы рекурсия ровно в момент, когда всё уже
    плохо.

    Ни гейта, ни роутинга, ни конфига, ни формата: у аварийного выхода не
    должно быть ничего, что можно сломать. Падать здесь запрещено — деть
    исключение отсюда уже некуда.
    """
    import logging

    try:
        getattr(logging.getLogger(name), level.lower(), logging.getLogger(name).warning)(message, *args)
    except Exception:  # nosec B110 — последний рубеж
        pass


class FallbackLogger:
    """Ленивый handle к именованному виду. Сам ничего не пишет.

    Конструируется без импортов (см. шапку модуля), вид подтягивает при первой
    записи и держит его дальше. Лишний кадр делегирования — цена цикло-
    безопасности; по замеру 2026-07-27 путь всё равно вдвое дешевле прежнего
    (~810 нс против 1409 у старой реализации с резолвом на каждой записи).
    """

    __slots__ = ("_name", "_view")

    def __init__(self, name: str) -> None:
        self._name = name
        self._view: Optional[Any] = None

    def _resolve(self) -> Any:
        """Подтянуть вид. Импорт ВНУТРИ метода — то самое снятие цикла."""
        view = self._view
        if view is None:
            from .logger_module.adapters.std_facade import get_std_logger

            # fallback_name=self._name: имя stdlib-логгера обязано остаться
            # точным, иначе записи «без менеджера» уедут под чужим именем.
            view = self._view = get_std_logger(self._name, fallback_name=self._name)
        return view

    def debug(self, msg: str, *args: Any) -> None:
        self._resolve().debug(msg, *args)

    def info(self, msg: str, *args: Any) -> None:
        self._resolve().info(msg, *args)

    def warning(self, msg: str, *args: Any) -> None:
        self._resolve().warning(msg, *args)

    def error(self, msg: str, *args: Any) -> None:
        self._resolve().error(msg, *args)

    def critical(self, msg: str, *args: Any) -> None:
        self._resolve().critical(msg, *args)
