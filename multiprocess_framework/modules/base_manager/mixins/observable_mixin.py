"""
Универсальный mixin для добавления наблюдаемости к любому менеджеру.

ObservableMixin позволяет менеджеру прозрачно взаимодействовать
с logger_manager, stats_manager, error_manager и любым пользовательским
менеджером через единый интерфейс.

## Режимы работы

1. Приватные методы (всегда доступны, pickle-совместимы):
    >>> class MyManager(BaseManager, ObservableMixin):
    ...     def __init__(self, name, logger=None):
    ...         BaseManager.__init__(self, name)
    ...         ObservableMixin.__init__(self, managers={'logger': logger})
    ...
    ...     def process(self):
    ...         self._log_info("Обработка данных")
    ...         self._record_metric("operations.count")

2. Публичные прокси-методы (auto_proxy=True, удобнее но не pickle-совместимы):
    >>> ObservableMixin.__init__(
    ...     self,
    ...     managers={'logger': logger, 'stats': stats},
    ...     auto_proxy=True   # создаст self.log_info(), self.record_metric() и т.д.
    ... )

## Гарантии pickle

Приватные методы (_log_*, _record_*, _track_*) реализованы как методы класса
и полностью совместимы с pickle (multiprocessing на Windows, spawn-режим).

Публичные прокси-методы (log_*, record_*, ...) автоматически восстанавливаются
при __setstate__, но managers после unpickle пустые — вызовы тихо возвращают None.
"""

import logging

from typing import Callable, Optional, Dict, Any, Set, List
from contextlib import contextmanager

from .core.manager_registry import ManagerRegistry
from .proxies.proxy_creator import ProxyCreator
from ..interfaces import IObservableMixin


#: Имена, занятые ПРОТОКОЛОМ дорог наблюдаемости — не деталями инцидента.
#: Поле сайта с таким именем не доезжает как поле, и по-разному на каждой двери:
#:
#: * ``message`` — позиционный параметр ``_log_error(message, **kwargs)`` (голос
#:   упал бы TypeError'ом) И протокольный ключ ``ErrorManager.track_error``,
#:   который его ``pop``-ает в приставку к тексту (в записи поля бы не осталось);
#: * ``manager_name`` / ``method_name`` — параметры второго хопа
#:   ``_call_manager(manager_name, method_name, *args, **kwargs)``: голос терялся
#:   бы целиком, оставляя факт и счётчик ``manager_call_failures``.
#:
#: Набор выведен из ВСЕЙ цепочки, а не из одной подписи — первая редакция
#: смотрела один хоп из двух и называла себя полной. Сверяется запуском:
#: ``TestFieldNamesCannotCollideWithTheReceiversSignature``.
#:
#: ``module`` сюда НЕ входит сознательно: это законный сквозной штамп источника,
#: его передают 14 сайтов одного только ``dispatch_module``.
_RESERVED_FIELD_NAMES = frozenset({"message", "manager_name", "method_name"})


class ObservableMixin(IObservableMixin):
    """
    Mixin для подключения любого менеджера к logger, stats, error и кастомным сервисам.

    Используйте совместно с BaseManager:

        class MyManager(BaseManager, ObservableMixin):
            def __init__(self, name, logger=None, stats=None):
                BaseManager.__init__(self, name)
                ObservableMixin.__init__(
                    self,
                    managers={'logger': logger, 'stats': stats},
                    config={'logger': True, 'stats': True},
                )

    Встроенные приватные методы (всегда доступны):
        self._log(level, message)
        self._log_debug/info/warning/error/critical(message)
        self._record_metric(name, value, tags)
        self._record_timing(name, duration, tags)
        self._track_error(error, context)

    С auto_proxy=True появляются публичные методы:
        self.log_debug/info/warning/error/critical(message)
        self.record_metric/increment/record_timing/gauge(...)
        self.track_error/record_error(...)
    """

    def __init__(
        self,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_proxy: bool = False,
        source_name: Optional[str] = None,
    ):
        """
        Args:
            managers:   Словарь {имя: менеджер}, например {'logger': logger_mgr}
            config:     Включение/выключение менеджеров.
                        Простая форма:  {'logger': True}
                        Подробная форма: {'logger': {'enabled': True}}
            auto_proxy: Создать публичные прокси-методы (log_info, record_metric …)
            source_name: Имя источника для штампа ``module`` (Ф2.1). Если не
                        задано — берётся ``manager_name`` от BaseManager.
        """
        self._registry = ManagerRegistry(managers, config)
        self._auto_proxy = auto_proxy
        if source_name:
            self._source_name_override = source_name

        if auto_proxy:
            self._proxy_created = True
            self._create_proxy_methods()
        else:
            self._proxy_created = False

    # =========================================================================
    # ВСТРОЕННЫЕ МЕТОДЫ НАБЛЮДАЕМОСТИ
    # Реализованы как методы класса — полностью pickle-совместимы.
    # Если соответствующий manager не зарегистрирован или выключен — тихо
    # возвращают None, не генерируя исключений.
    # =========================================================================

    def _observability_source(self) -> str:
        """Имя источника для штампа ``module`` (Ф2.1).

        Порядок: явный ``source_name`` из ``__init__`` → ``manager_name``
        (ставит ``BaseManager.__init__``) → ``"main"``.

        Читается из ``__dict__``, а не через ``getattr``: путь горячий (каждая
        запись лога), а дескрипторы и обход MRO здесь ничего не дают —
        оба имени кладутся как обычные атрибуты экземпляра.

        Резолв ЛЕНИВЫЙ, не в ``__init__``, потому что порядок инициализации
        миксина и ``BaseManager`` в наследниках не одинаков: часть зовёт
        ``ObservableMixin.__init__`` первым, и на тот момент ``manager_name``
        ещё нет.
        """
        d = self.__dict__
        return d.get("_source_name_override") or d.get("manager_name") or "main"

    def _log(self, level: str, message: str, **kwargs) -> None:
        """Логирование через logger manager (любой уровень)."""
        kwargs.setdefault("module", self._observability_source())
        self._call_manager("logger", level, message, **kwargs)

    def _log_debug(self, message: "str | Callable[[], str]", **kwargs) -> None:
        """Логирование уровня DEBUG через logger manager.

        Сообщение может быть ОТЛОЖЕННЫМ (Ф1.4): ``lambda: f"…"`` вместо
        ``f"…"``. Разница не стилистическая — она в том, кто платит за сборку
        строки при ВЫКЛЮЧЕННОМ DEBUG. ``f``-строка собирается на call-site, то
        есть до входа в логгер, и никаким гейтом внутри не снимается; лямбда
        зовётся только после гейта и ровно один раз.

        Правило (baseline §2.5, задача Ф7.1): точка на пути КАЖДОГО сообщения
        обязана быть отложенной. Точке с постоянным текстом лямбда не нужна —
        собирать там нечего, и замыкание было бы чистой ценой.
        """
        kwargs.setdefault("module", self._observability_source())
        self._call_manager("logger", "debug", message, **kwargs)

    def _log_info(self, message: str, **kwargs) -> None:
        """Логирование уровня INFO через logger manager."""
        kwargs.setdefault("module", self._observability_source())
        self._call_manager("logger", "info", message, **kwargs)

    def _log_warning(self, message: str, **kwargs) -> None:
        """Логирование уровня WARNING через logger manager."""
        kwargs.setdefault("module", self._observability_source())
        self._call_manager("logger", "warning", message, **kwargs)

    def _log_error(self, message: str, **kwargs) -> None:
        """Логирование уровня ERROR через logger manager."""
        kwargs.setdefault("module", self._observability_source())
        self._call_manager("logger", "error", message, **kwargs)

    def _log_critical(self, message: str, **kwargs) -> None:
        """Логирование уровня CRITICAL через logger manager."""
        kwargs.setdefault("module", self._observability_source())
        self._call_manager("logger", "critical", message, **kwargs)

    # Публичные алиасы — для внешнего кода, который принимает менеджер
    # как зависимость (например, ChainContext.logger). _log_* остаются
    # каноничным «семейным» путём для наследников BaseManager.
    def log_debug(self, message: str, **kwargs) -> None:
        self._log_debug(message, **kwargs)

    def log_info(self, message: str, **kwargs) -> None:
        self._log_info(message, **kwargs)

    def log_warning(self, message: str, **kwargs) -> None:
        self._log_warning(message, **kwargs)

    def log_error(self, message: str, **kwargs) -> None:
        self._log_error(message, **kwargs)

    def log_critical(self, message: str, **kwargs) -> None:
        self._log_critical(message, **kwargs)

    # =========================================================================
    # ОКНО ГОЛОСА НА КЛЮЧ (Ф1.4, M17)
    # Механизм живёт в ``logger_module/core/windowed_voice.py``; здесь — РАЗЪЁМ
    # для наследников BaseManager. Импорт ленивый: ``logger_module`` тянет
    # ``base_manager`` (LoggerManager — тоже BaseManager), и импорт на уровне
    # модуля замкнул бы цикл на пакетных ``__init__``.
    # =========================================================================

    def _voices(self) -> Any:
        """Держатель окон ЭТОГО менеджера (ленивый, свой у каждого экземпляра).

        Свой, а не процессный: ключ ``"send_error:no_route"`` у двух роутеров
        в одном процессе — два разных события, и общий держатель заглушил бы
        второй голос первым.

        Установка — через ``setdefault``, а не «проверил и присвоил». Прежняя
        пара операций была check-then-set: два потока, впервые голосящие
        одновременно, получали РАЗНЫХ держателей, и один из них тут же
        становился сиротой вместе со своим счётом подавлений. Естественным
        прогоном это не воспроизводится (ревью Task 1.4: 0 из 200), а при
        искусственно расширенном окне — воспроизводится; ``dict.setdefault``
        закрывает окно целиком и стоит одной строки. Лишний экземпляр в гонке
        создаётся и выбрасывается — он пуст, терять в нём нечего.
        """
        holder = self.__dict__.get("_windowed_voices")
        if holder is None:
            from ...logger_module.core.windowed_voice import WindowedVoices

            holder = self.__dict__.setdefault("_windowed_voices", WindowedVoices())
        return holder

    def should_voice(self, key: str, interval: Optional[float] = None) -> "tuple[bool, int]":
        """Решение о голосе по ключу — **без записи и без учёта**.

        Разделение обязательств здесь и есть смысл механизма: **факт** (счётчик,
        запись в плоскость ошибок) вызывающий учитывает ВСЕГДА, окно его не
        касается; **голос** (строка в журнал) идёт не чаще ``interval``.

            voiced, suppressed = self.should_voice(key)
            self._inc_stat("errors")          # факт — всегда
            if voiced:                        # голос — по окну
                self._log_error(f"…(подавлено: {suppressed})")

        Склейка их в один вызов уже стоила проекту дефекта: в
        ``process_module/health/state.py`` запись в плоскость ошибок стоит ВНУТРИ
        ветки «окно позволило», потому что своего окна у плоскости ошибок не было
        и был взят дроссель журнала — повтор в окне не оставляет там ни трассы,
        ни контекста, только число.

        Returns:
            ``(голосить?, подавлено с прошлой записи)``.
        """
        return self._voices().take(key, interval)

    def log_windowed(
        self,
        key: str,
        interval: Optional[float] = None,
        level: str = "warning",
        message: str = "",
        **ctx: Any,
    ) -> bool:
        """Сказать вслух не чаще окна на ключ. Удобство для «нужен только голос».

        Контекст едет СТРУКТУРНЫМИ полями (в отличие от свободной функции
        :func:`~...logger_module.core.windowed_voice.log_windowed`, у которой
        приёмник — stdlib-логгер без структурного места). Переменную часть клади
        сюда, а не в ``message``: текст обязан быть постоянным, иначе ключ окна и
        текст разъезжаются (находка m2 про ``trace_id``).

        Returns:
            ``True``, если голос прозвучал.
        """
        voiced, suppressed = self.should_voice(key, interval)
        if not voiced:
            return False
        text = message if not suppressed else f"{message} (подавлено с прошлой записи: {suppressed})"
        if suppressed:
            ctx.setdefault("suppressed_since_last", suppressed)
        self._log(level, text, **ctx)
        return True

    def report_error(
        self,
        exc: BaseException,
        context: Optional[str] = None,
        throttle: Optional[float] = None,
        **fields: Any,
    ) -> None:
        """Учесть отказ: **факт ВСЕГДА**, голос — по окну. Одна дверь на оба обязательства.

        Зеркало :meth:`HealthState.report_error` для тех, у кого нет
        ``ctx.health``: менеджеров фреймворка (роутер, диспетчер, командный
        менеджер, топология) и сервисов. Оба держателя механизма говорят одним
        языком — сайт зовёт ОДИН метод и не расставляет порядок сам.

        **Перекрывается сознательно у ``ProcessModule``** (тот же метод, дорога
        богаче: health-счётчик, ``last_error``, breaker). MRO отдаёт приоритет
        классу, и это верно: у процесса есть health, у голого менеджера — нет.
        Сторож на MRO — ``TestProcessModuleKeepsItsRicherRoad``.

        **Почему метод, а не дисциплина вызывающего (Task 1.3b, вердикт).**
        До него сайт собирал связку руками — ``should_voice`` → ``if voiced:
        _log_error`` → ``_track_error``, — и вся корректность держалась на
        ПОРЯДКЕ трёх вызовов. Порядок не удержался: в
        ``RouterManager._report_send_error`` ``return`` при закрытом окне стоял
        ВЫШЕ ``_track_error``, и замер дал **5 вхождений отказа → 5 в
        счётчиках, 1 запись в плоскости ошибок, 4 потеряны целиком**. Написал
        это тот, кто правило знал: инвариант, охраняемый порядком трёх вызовов
        на 47 адресах, — генератор дефектов, а охраняемый телом одного метода —
        структурное свойство.

        Ключ окна — ``(класс отказа, context)``, та же формула, что у
        ``HealthState``. Дробность решает САЙТ: нужен голос на устройство —
        кладёт идентификатор в ``context`` (``f"create_worker@{dev_id}"``).
        Фреймворк форму ключа фиксирует, а язык сборки ключей не заводит —
        это был бы второй словарь политики. Отвергнут (Task 1.3b) вариант
        «identity инстанса в ключе всегда»: хаб на 20 устройствах, отпавших
        одной причиной, дал бы 20 строк — ровно шторм, против которого окно и
        заведено. Различимость при этом не теряется: факт пер-вхождение и
        несёт ``**fields``.

        ``**fields`` уезжают в контекст записи плоскости ошибок И в поля
        голоса: деталь, снятая вместе с соседним ``_log_error`` при миграции
        Task 1.3b, обязана остаться структурной, а не раствориться в тексте.

        Голос несёт маркер дедупа путей ``origin=error_manager`` ТОЛЬКО когда
        факт действительно уехал в плоскость (см. ``_track_error`` → ``bool``).
        Маркер — утверждение о ЧУЖОЙ строке стора; безусловный, он ложен там,
        где плоскости нет, и тогда логгер-tap пропускает голос, а инцидент
        исчезает целиком (находка Major 1 ревью Task 1.3a).
        """
        from ...channel_routing_module.observability.store_tap import ORIGIN_ERROR_MANAGER, ORIGIN_FIELD
        from ...logger_module.core.windowed_voice import compose_voice_text
        from ...logger_module.utils import safe_exception_message

        etype = type(exc).__name__
        ctx = str(context) if context else ""

        # ФАКТ — первым и безусловно. Всё, что ниже, зовёт ЧУЖИЕ механизмы
        # (держатель окон, логгер): упади любой из них — факт уже учтён.
        #
        # ``context`` кладётся ПОСЛЕ полей — СТРАХОВКА, а не закрытие дыры.
        # Проверено запуском: подмены здесь быть не может, потому что
        # ``context`` — именованный параметр этого метода, и одноимённое поле
        # сайта до ``fields`` просто не долетает (Python роняет вызов ещё на
        # сайте). Первая редакция комментария объявляла тихую подмену реальной
        # опасностью — неправда, снято. Порядок оставлен: он ничего не стоит и
        # переживёт день, когда ``context`` перестанет быть параметром.
        # Разводка имён — ОДИН раз, на входе, до обеих дорог. Первая редакция
        # разводила только голос, и это само было дефектом: одно и то же поле
        # приезжало в журнал как ``field_x``, а в плоскость ошибок как ``x``,
        # то есть фильтр по полю зависел от того, куда смотришь. Хуже: на дороге
        # факта имя ``message`` не роняет вызов, а ТИХО СЪЕДАЕТСЯ протоколом
        # ``track_error`` (уходит в приставку к тексту), и поля не остаётся
        # вовсе — найдено ревью Task 1.3b запуском против настоящего
        # ``ErrorManager``, тогда как мой сторож проверял это против фейка.
        safe_fields: Dict[str, Any] = {
            (f"field_{k}" if k in _RESERVED_FIELD_NAMES else k): v for k, v in fields.items()
        }

        recorded = self._track_error(exc, {**safe_fields, "context": ctx} if (ctx or safe_fields) else None)

        # ГОЛОС — целиком под защитой. Зеркалить здесь HealthState нельзя: там
        # бросок держателя окон уходит вызывающему сознательно (процессные хуки
        # его ловят и считают потерей доставки). У ЭТОЙ двери вызывающий — по
        # построению миграции Task 1.3b тело ``except``, и бросок отсюда
        # ПОДМЕНИЛ БЫ исходную ошибку своей. Факт выше уже учтён, а голос
        # дешевле любого искажения разбора.
        try:
            voiced, suppressed = self.should_voice(f"{etype}|{ctx}", throttle)
            if not voiced:
                return
            where = f" @ {ctx}" if ctx else ""
            voice_fields: Dict[str, Any] = dict(safe_fields)
            if recorded:
                # Маркер кладётся ПОВЕРХ полей, а не рядом: ``**fields, **marker``
                # роняет вызов TypeError'ом на сайте, который сам передал поле
                # ``origin``. Здесь маркер обязан выигрывать — он не деталь
                # инцидента, а утверждение о строке стора.
                voice_fields[ORIGIN_FIELD] = ORIGIN_ERROR_MANAGER
            self._log_error(
                compose_voice_text(f"{etype}{where}: {safe_exception_message(exc)}", suppressed),
                **voice_fields,
            )
        except Exception as voice_exc:  # noqa: BLE001 — голос не стоит подмены исходной ошибки
            self._note_manager_call_failure("logger", "report_error.voice", exc=voice_exc)

    def _record_metric(self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """Запись метрики через stats manager."""
        self._call_manager("stats", "record_metric", metric_name, value, tags or {})

    def _record_timing(self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Запись времени выполнения через stats manager."""
        self._call_manager("stats", "record_timing", metric_name, duration, tags or {})

    def _error_context(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Контекст инцидента со штампом источника — ЕДИНСТВЕННАЯ позиция штампа.

        Ф2.1: имя источника кладётся в КОНТЕКСТ, а не в kwargs — у слота
        ``error`` сигнатура другая (``track_error(error, context)``), и
        ``ErrorManager.track_error`` читает имя именно из ``ctx["module"]``,
        подставляя ``"unknown"`` при его отсутствии. Без этой строки плоскость
        ошибок осталась бы без штампа при заштампованной плоскости логов —
        то есть у самой важной из трёх. Найдено ревью Ф2.1.

        Н-14 (приёмка F1): штамп стоял ТОЛЬКО в :meth:`_track_error`, а публичные
        прокси ``track_error``/``record_error`` звали менеджер напрямую — и
        инцидент от ``health.report`` уезжал ``module="unknown"`` при
        заштампованной лог-дороге той же пары. Причём именно публичный путь и
        выбирает ``HealthState`` (``_resolve_track`` предпочитает ``track_error``),
        то есть штамп был мёртв ровно там, где он нужнее всего.
        Вынесено сюда, чтобы позиция осталась одна: два ``setdefault`` в двух
        файлах разошлись бы молча — этим дефект и был.
        """
        ctx = dict(context) if context else {}
        ctx.setdefault("module", self._observability_source())
        return ctx

    def _track_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> bool:
        """Отслеживание ошибки через error manager (каноничный слот 'error').

        Returns:
            Ушёл ли факт ПРИЁМНИКУ. ``False`` — слота нет, он выключен или у
            менеджера нет ни ``track_error``, ни ``record_error``. По этому и
            только по этому признаку :meth:`report_error` решает, вешать ли на
            голос маркер дедупа путей: маркер утверждает, что строка стора у
            инцидента уже есть, и на процессе без ErrorManager это утверждение
            ложно (Major 1 ревью Task 1.3a).

            Потолок назван прямо: ``True`` — «приёмник протокола нашёлся», а не
            «запись легла на диск». Отказ ВНУТРИ менеджера считается отдельно
            (``manager_call_failures``), сюда он не доезжает.
        """
        ctx = self._error_context(context)
        # Task 5.14: имя error-гнезда каноникализировано на 'error'. Legacy-fallback
        # на слот 'errors' убран — все точки регистрации переведены на 'error'.
        #
        # Task Т.1: ветка выбирается ПО ПРОТОКОЛУ приёмника, а не по возвращённому
        # значению. Прежняя лесенка «track_error вернул None → пробуем
        # record_error» неотличима от успеха: ``ErrorManager.track_error``
        # объявлен ``-> None`` и возвращает None ИМЕННО на штатной записи, так что
        # вторая ступень срабатывала ВСЕГДА — и молча не находила метода
        # (``ErrorManager`` его не имеет; ``record_error`` есть у duck-typed
        # плоскостей вроде ``ObservabilityHub``). Пока отсутствующий метод был
        # тихим, это ничего не стоило; со счётчиком Т.1 здоровый путь давал
        # 9 ложных «потерь» за прогон гейта, и счётчик перестал бы значить
        # «запись потеряна». Предпочтение прежнее: track_error, если он есть.
        error = self._as_incident(error, ctx)
        if self._manager_has_method("error", "track_error"):
            self._call_manager("error", "track_error", error, ctx)
            return True
        reachable = self._manager_has_method("error", "record_error")
        # Вызов идёт ДАЖЕ при отсутствии метода — намеренно: ``_call_manager``
        # на этой ветке считает потерю и предупреждает один раз на пару (Т.1),
        # то есть дефект проводки остаётся видимым. Тихо пропустить вызов
        # значило бы обменять счётчик потерь на ровный ноль.
        self._call_manager("error", "record_error", error, ctx)
        return reachable

    def _as_incident(self, error: Any, ctx: Dict[str, Any]) -> BaseException:
        """Гарантировать, что дальше поедет исключение, и НЕ бросить, если это не так.

        Дорога наблюдаемости не имеет права бросать: её зовут из веток «мы
        поймали исключение», и отказ учёта, ставший вторым исключением поверх
        первого, ПОДМЕНЯЕТ исходную ошибку своей — худший из возможных исходов.

        Найдено Task 1.3b запуском: четыре адреса
        (``dispatcher.py:153,184``, ``command_manager.py:134,157``) звали
        ``self._track_error("dispatcher.initialization.failed", error=e)`` —
        ``error`` передан и позиционно, и по имени. Результат:
        ``TypeError: _track_error() got multiple values for argument 'error'``
        внутри ``except`` — то есть на месте настоящего отказа подъёма
        подсистемы наружу уходила бы ошибка про сигнатуру. Не стреляло только
        потому, что сами ветки ``except`` мертвы (тело ``try`` — присваивание и
        лог), и НИ ОДИН тест через них не проходил.

        Мусор не глотается: он становится ТИПИЗИРОВАННЫМ фактом
        (``ObservabilityMisuse``) и считается в книге misuse, которая обязана
        читаться наружу — иначе тихий счётчик заменил бы громкий отказ и стал
        бы новым местом, где дефект живёт незамеченным (условие к вердикту
        Q5, Task 1.3b).
        """
        if isinstance(error, BaseException):
            return error
        # Ленивый импорт: base_manager — нижний ярус и не тянет error_module
        # на уровне модуля (тот наследует BaseManager — вышел бы цикл).
        from ...error_module.failures import ObservabilityMisuse

        misuse: Dict[str, int] = self.__dict__.setdefault("_track_error_misuse", {})
        key = str(ctx.get("module") or self._observability_source())
        misuse[key] = misuse.get(key, 0) + 1
        return ObservabilityMisuse(f"_track_error получил не исключение, а {type(error).__name__}: {error!r:.200}")

    # =========================================================================
    # ПУБЛИЧНЫЙ API — УПРАВЛЕНИЕ МЕНЕДЖЕРАМИ
    # =========================================================================

    def register_manager(self, name: str, manager: Any, enabled: bool = True) -> None:
        """
        Зарегистрировать менеджер после инициализации.

        Если auto_proxy был включён — прокси-методы будут пересозданы.

        Args:
            name:    Имя менеджера ('logger', 'stats', 'error' и т.д.)
            manager: Экземпляр менеджера
            enabled: Включён ли сразу после регистрации
        """
        self._registry.register(name, manager, enabled)

        if getattr(self, "_proxy_created", False) or getattr(self, "_auto_proxy", False):
            self._proxy_created = True
            self._create_proxy_methods()

    def unregister_manager(self, name: str) -> None:
        """Удалить менеджер из реестра."""
        self._registry.unregister(name)

    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени (None если не найден)."""
        return self._registry.get(name)

    def has_manager(self, name: str) -> bool:
        """Проверить наличие зарегистрированного менеджера."""
        return self._registry.has(name)

    # =========================================================================
    # ПУБЛИЧНЫЙ API — УПРАВЛЕНИЕ СОСТОЯНИЕМ
    # =========================================================================

    def enable(self, manager_name: str, enabled: bool = True) -> None:
        """Включить или выключить менеджер."""
        self._registry.enable(manager_name, enabled)

    def disable(self, manager_name: str) -> None:
        """Выключить менеджер (вызовы через _call_manager будут тихо игнорироваться)."""
        self._registry.disable(manager_name)

    def is_enabled(self, manager_name: str) -> bool:
        """True если менеджер зарегистрирован и включён."""
        return self._registry.is_enabled(manager_name)

    def get_enabled_managers(self) -> Set[str]:
        """Множество имён включённых менеджеров."""
        return self._registry.get_enabled()

    @contextmanager
    def context(self, manager_name: str, enabled: bool = True):
        """
        Контекстный менеджер для временного изменения состояния.

        Пример:
            with self.context('logger', enabled=False):
                ...  # логирование отключено
            # здесь логирование снова работает
        """
        with self._registry.context(manager_name, enabled):
            yield

    # =========================================================================
    # ПУБЛИЧНЫЙ API — КОНФИГУРАЦИЯ
    # =========================================================================

    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновить конфигурацию менеджеров."""
        self._registry.update_config(config)

    def get_config(self) -> Dict[str, Any]:
        """Получить копию текущей конфигурации."""
        return self._registry.get_config()

    def get_state(self) -> Dict[str, Any]:
        """
        Снимок текущего состояния mixin.

        Returns:
            dict с ключами: config, enabled, managers, enabled_managers,
            manager_call_failures (Ф2.3 — проглоченные отказы _call_manager)
        """
        state = self._registry.get_state()
        state["manager_call_failures"] = self.manager_call_failures
        return state

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ДИАГНОСТИКА
    # =========================================================================

    def get_available_methods(self) -> Dict[str, List[str]]:
        """
        Список доступных методов, менеджеров и адаптеров.

        Полезно при отладке для понимания, что было создано автоматически.

        Returns:
            dict с ключами 'private', 'public', 'managers', 'adapters'
        """
        methods: Dict[str, List[str]] = {
            "private": [],
            "public": [],
            "managers": list(self._registry.managers.keys()),
            "adapters": list(getattr(self, "_adapters", {}).keys()),
        }
        for attr_name in dir(self):
            if attr_name.startswith("__"):
                continue
            if attr_name.startswith("_"):
                methods["private"].append(attr_name)
            else:
                methods["public"].append(attr_name)
        return methods

    def print_available_methods(self) -> None:
        """Вывести список доступных методов через логгер (для отладки)."""
        import json

        methods = self.get_available_methods()
        self._log_debug(f"Доступные методы и менеджеры:\n{json.dumps(methods, indent=2, ensure_ascii=False)}")

    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # =========================================================================

    @property
    def manager_call_failures(self) -> Dict[str, int]:
        """Счётчики проглоченных отказов _call_manager: 'manager.method' -> N (Ф2.3)."""
        return dict(self.__dict__.get("_manager_call_failures", {}))

    @property
    def track_error_misuse(self) -> Dict[str, int]:
        """Кривые вызовы ``_track_error`` (не исключение на входе): источник -> N.

        Ненулевое значение — дефект вызывающего кода, а не рантайма: дорога
        наблюдаемости отработала, но сайт передал ей мусор (Task 1.3b,
        :meth:`_as_incident`). Пусто, пока такого вызова не было ни одного.

        **Долг, названный прямо:** книга читается только отсюда — в
        ``introspect.observability`` она попадёт вместе с протоколом readback
        (Ф4.3 плана ``observability-closure``). До тех пор «ноль на живом
        стенде» проверяется тестом чистого подъёма, а не ручкой пульта.
        """
        return dict(self.__dict__.get("_track_error_misuse", {}))

    def _manager_has_method(self, manager_name: str, method_name: str) -> bool:
        """Есть ли в слоте ВКЛЮЧЁННЫЙ менеджер с вызываемым ``method_name``.

        Нужно ровно там, где ветка выбирается по протоколу приёмника, а не по
        результату вызова: ``None`` от менеджера — законный успех, и отличить
        его от «метода нет» по возвращённому значению невозможно (см.
        :meth:`_track_error`).

        Вопрос, а не вызов: ничего не считает и ничего не пишет в лог.
        """
        registry: Optional[ManagerRegistry] = self.__dict__.get("_registry")
        if registry is None or not registry.is_enabled(manager_name):
            return False
        manager = registry.get(manager_name)
        # `is None`, а не truthiness — тот же довод, что в ``_call_manager``, и
        # здесь он ЖЁСТЧЕ: эта функция ВЫБИРАЕТ ВЕТКУ в ``_track_error``.
        # Менеджер с ложным ``__bool__``/``__len__`` (например error-менеджер,
        # у которого ``__len__`` — «сколько ошибок накоплено»: пустой = ложь)
        # читался как «слота нет», ветка падала на запасную ступень
        # ``record_error``, которой у него может не быть, и запись терялась —
        # а счётчик отказов приписывал потере ЛОЖНУЮ причину («в слот подан
        # объект чужого протокола»), хотя протокол объект как раз реализует.
        # Найдено ревью Ф1+Ф2: правка `0c06712d` убрала truthiness в
        # ``_call_manager``, но эта функция появилась в том же коммите Т.1 и
        # осталась со старым сравнением.
        if manager is None:
            return False
        return callable(getattr(manager, method_name, None))

    def _call_manager(self, manager_name: str, method_name: str, *args, **kwargs) -> Any:
        """
        Универсальная точка вызова метода зарегистрированного менеджера.

        Безопасен при отсутствии _registry (после unpickle) — возвращает None.
        Исключение внутри менеджера не роняет вызывающего, но больше НЕ
        глотается молча (Ф2.3): счётчик manager_call_failures + WARNING.

        Task Т.1: то же самое теперь верно и для второго способа потерять
        запись — менеджер В СЛОТЕ ЕСТЬ, но нужного метода у него НЕТ. Раньше
        управление просто проваливалось до ``return None``, и ни счётчик, ни
        лог этого не видели. Это не допуск, а дефект проводки: в слот
        ``logger`` подан объект с ``log_warning`` вместо ``warning``, и КАЖДАЯ
        запись такого компонента исчезает (измерено: StateProxy дал 0 строк на
        60 живых лог-файлах). Считается и предупреждается на тех же книгах,
        что и исключение.

        Три допуска остаются ТИХИМИ (их отсутствие — легальное состояние,
        а не поломка): слота нет, менеджер None, слот выключен.

        Returns:
            Результат вызова или None (если менеджер недоступен/выключен/
            упал/не имеет метода)
        """
        registry: Optional[ManagerRegistry] = self.__dict__.get("_registry")
        if registry is None or not registry.is_enabled(manager_name):
            return None

        manager = registry.get(manager_name)
        # `is None`, а не truthiness — по тому же доводу, что ниже у метода, и
        # найдено матрицей инъекций Т.1: заплата «считать отказом и manager
        # is None» не покраснила НИ ОДНОГО теста, потому что до этой строки
        # None не доходит вообще (``ManagerRegistry`` ставит
        # ``_enabled[name] = manager is not None and enabled``, и такой слот
        # отсекается гейтом выше). Значит единственный достижимый случай здесь —
        # менеджер НАСТОЯЩИЙ, но с ложным ``__bool__``/``__len__``: его записи
        # уходили в никуда и НЕ считались, потому что выглядели как «слот пуст».
        if manager is None:
            return None

        try:
            method = getattr(manager, method_name, None)
            # `is not None`, а не truthiness: вызываемый объект с ложным
            # __bool__ (Mock, функтор с __len__) иначе уехал бы в ветку
            # «метода нет» и был бы посчитан отказом, которым не является.
            if method is not None and callable(method):
                return method(*args, **kwargs)
        except Exception as exc:
            self._note_manager_call_failure(manager_name, method_name, exc=exc)
            return None

        # Сюда попадаем ровно в одном случае: менеджер есть и включён, метода
        # нет (или он не вызываем). exc=None отличает этот отказ от падения
        # внутри менеджера — чинятся они по-разному.
        self._note_manager_call_failure(manager_name, method_name, manager=manager)
        return None

    def _note_manager_call_failure(
        self,
        manager_name: str,
        method_name: str,
        exc: Optional[BaseException] = None,
        manager: Any = None,
    ) -> None:
        """Учёт отказа менеджера: счётчик всегда, WARNING — раз на пару (Ф2.3).

        Лог — через stdlib logging, НЕ через _log_* (отказать мог сам
        logger-менеджер — вызов через себя дал бы рекурсию). WARNING пишется
        один раз на пару manager.method, дальше растёт только счётчик
        (_call_manager стоит на hot-path каждого лога/метрики — спам недопустим).

        Два рода отказа лежат в одном словаре, но текст WARNING у них разный
        (Task Т.1): ``exc is not None`` — менеджер БРОСИЛ (чинят приёмник);
        ``exc is None`` — у менеджера НЕТ такого метода (чинят проводку: в слот
        подан объект не того протокола). Общий счётчик — сознательно: обе
        ситуации означают «запись потеряна», и внешнему наблюдателю нужна
        именно сумма потерь на паре.
        """
        failures: Dict[str, int] = self.__dict__.setdefault("_manager_call_failures", {})
        key = f"{manager_name}.{method_name}"
        first_failure = key not in failures
        failures[key] = failures.get(key, 0) + 1
        if not first_failure:
            return

        module_logger = logging.getLogger(__name__)
        if exc is not None:
            module_logger.warning(
                "ObservableMixin: вызов %s провалился (%s: %s) — "
                "дальнейшие отказы пары считаются в manager_call_failures",
                key,
                type(exc).__name__,
                exc,
            )
        else:
            module_logger.warning(
                "ObservableMixin: вызов %s невозможен — у менеджера слота "
                "'%s' (%s) нет вызываемого метода '%s'; запись потеряна. "
                "Это дефект проводки: в слот подан объект чужого протокола — "
                "дальнейшие потери пары считаются в manager_call_failures",
                key,
                manager_name,
                type(manager).__name__,
                method_name,
            )

    def _create_proxy_methods(self) -> None:
        """Создать публичные прокси-методы (log_info, record_metric, …)."""
        ProxyCreator.create_proxy_methods(
            self,
            self._registry.managers,
            self._call_manager,
        )

    # =========================================================================
    # PICKLE SUPPORT
    # Приватные методы (_log_*, _record_*, _track_*) — методы класса, пикл-совместимы.
    # Публичные прокси-методы — замыкания в __dict__, исключаются из pickle
    # и восстанавливаются в __setstate__.
    # =========================================================================

    def __getstate__(self) -> Dict[str, Any]:
        """Pickle: исключить непикл-совместимые элементы из состояния."""
        state = self.__dict__.copy()
        _EXCLUDE = (
            # Публичные прокси-методы (замыкания)
            "log_debug",
            "log_info",
            "log_warning",
            "log_error",
            "log_critical",
            "record_metric",
            "increment",
            "record_timing",
            "gauge",
            "track_error",
            "record_error",
            # Внутренние компоненты (содержат ссылки на менеджеры)
            "_registry",
            "_proxy_created",
            # Ф1.4: держатель окон голоса держит threading.Lock — непикл-совместим,
            # а менеджеры этого миксина уезжают в дочерние процессы (spawn на
            # Windows). Пересоздаётся лениво на первом обращении; окна при этом
            # начинаются заново, что и правильно: в новом процессе это новые
            # события, а не продолжение чужих.
            "_windowed_voices",
        )
        for key in _EXCLUDE:
            state.pop(key, None)
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """
        Unpickle: восстановить объект.

        После восстановления:
        - _log_*/record_*/track_* работают (методы класса), но тихо возвращают None
          пока managers не будут перерегистрированы.
        - Публичные прокси-методы (log_info, …) воссоздаются если _auto_proxy=True.
        """
        self.__dict__.update(state)
        # Rebuild internal components with empty state.
        # Managers are NOT restored — they hold non-picklable resources (sockets, queues…)
        # and must be re-injected by the owner after unpickle.
        self._registry = ManagerRegistry()
        # Recreate proxy methods shell (they call _call_manager which returns None for empty registry)
        if getattr(self, "_auto_proxy", False):
            self._proxy_created = True
            self._create_proxy_methods()
        else:
            self._proxy_created = False
