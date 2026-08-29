# -*- coding: utf-8 -*-
"""Три процессных хука: исключения потоков, исключения главного потока, `warnings`.

Находка C3 ревью 2026-08-28: `threading.excepthook`, `sys.excepthook` и
`warnings.showwarning` не встречались в репозитории ни разу. Следствие
воспроизведено запуском: исключение в рабочем потоке давало 728 байт в stderr и
**ноль** записей в трёх плоскостях наблюдаемости — то есть отказ, который никто
не увидит ни в `errors.log`, ни в сторе, ни в `system_overview`.

Что делает модуль
-----------------
:func:`install_process_hooks` ставит три тонких хука. Каждый собирает
``(имя потока, исключение, трасса)``, делает ОДНУ доставку через утиный протокол
``services`` и передаёт событие ПРЕЖНЕМУ хуку (для исключений) — трасса в stderr
и обёртки pytest продолжают работать как раньше.

Почему модуль живёт в `logger_module`, а не в `process_module`
--------------------------------------------------------------
Хуки — процессные слоты интерпретатора, и знать про `ProcessModule` им незачем:
здесь нет ни одного импорта `process_module`/`error_module`. Адресат описан
утиным протоколом (см. ниже), поэтому механизм одинаково ставится и на боевой
процесс, и на минимальный фейк в тесте. Обратное размещение (внутри
`process_module`) сделало бы фреймворковый механизм недоступным тому, у кого
процесса нет, — лаунчеру и одиночным утилитам.

Протокол ``services`` (утиный, ничего импортировать не надо)
------------------------------------------------------------
============================================  =================================
член                                          назначение
============================================  =================================
``name: str``                                 имя процесса — штамп записей
``report_error(exc, context, **fields)``      дорога инцидента: health-счётчик +
                                              плоскость ошибок + строка журнала
``_log_warning(message, **kwargs)``           плоскость логов (WARNING)
``get_manager(name)``                         ``get_manager("error")`` — где
                                              живут счётчики (см. ниже)
============================================  =================================

Где живут три числа
-------------------
Источник числа ОДИН. Если у процесса есть ``ErrorManager``, счётчики пишутся
прямо в его ``stats`` — тот же словарь, который публикует
``ErrorManager.get_stats()`` и пересылает наружу ``PLANE_COUNTER_KEYS``. Своей
копии здесь нет намеренно: две копии одного числа расходятся молча, и тогда
``hooks.counters()`` и ``introspect.observability`` отвечали бы разное на один
вопрос. Процесс без плоскости ошибок (``config={}``) считает в приватный
словарь — хуки ставятся и там, просто числа видны только через
:meth:`ProcessHooks.counters`.

Чего модуль НЕ ловит (названо, а не умолчано)
---------------------------------------------
* ``SystemExit`` / ``KeyboardInterrupt`` — не инцидент, как и у stdlib: они
  штатный способ остановить поток и процесс;
* предупреждения, отфильтрованные машинерией ``warnings`` (фильтры хук не
  трогает: смена фильтров процессом — самостоятельное решение оператора, а не
  побочный эффект установки наблюдателя);
* нативный stderr (падение C-расширения, ``abort()``) — это fd-перехват,
  задача 9.2 роадмапа, здесь её нет.
"""

from __future__ import annotations

import sys
import threading
import traceback
import warnings
from typing import Any, Callable, Dict, Optional, Tuple

from ..._fallback import emergency_log

__all__ = ["HOOK_COUNTER_KEYS", "ProcessHooks", "install_process_hooks", "installed_hooks"]


#: Три числа механизма. Кортеж — единственный реестр имён: его читают
#: ``ErrorManager`` (объявление в ``stats``), ``PLANE_COUNTER_KEYS`` (пересылка
#: наружу) и сверщик документов. Своя копия строк в любом из трёх мест —
#: расхождение, которое молчит.
HOOK_COUNTER_KEYS: Tuple[str, ...] = ("thread_exceptions", "warnings_captured", "hook_delivery_failures")

#: Имя stdlib-логгера аварийного выхода — ровно имя этого модуля, чтобы записи об
#: отказе доставки искались там, где они происходят (тот же приём, что в
#: ``process_lifecycle.py``).
_EMERGENCY_NAME = __name__

#: Модуль-источник записи предупреждения. Тем же именем пользуется
#: ``logging.captureWarnings`` — оператор, знающий stdlib, найдёт записи по
#: привычному слову.
_WARNINGS_MODULE = "py.warnings"

#: Один хук на процесс. Глобаль, потому что слоты интерпретатора тоже глобальны:
#: два объекта, поочерёдно занявшие один слот, дали бы одно событие дважды.
_installed: Optional["ProcessHooks"] = None
_install_lock = threading.Lock()

#: Сторож реентрантности — ПОТОКОВЫЙ. Событие, случившееся внутри самой доставки
#: (логгер бросил предупреждение, плоскость ошибок упала), приходит в тот же
#: поток; без сторожа это рекурсия до предела стека ровно в тот момент, когда
#: маршрут наблюдаемости уже сломан.
_local = threading.local()


class ProcessHooks:
    """Установленные хуки процесса. Создаётся только :func:`install_process_hooks`."""

    def __init__(self, services: Any) -> None:
        self._services = services
        self._counters = _resolve_counter_store(services)
        self._counter_lock = threading.Lock()
        self._installed = False
        self._prev_threading: Optional[Callable[..., Any]] = None
        self._prev_sys: Optional[Callable[..., Any]] = None
        self._prev_showwarning: Optional[Callable[..., Any]] = None
        # Связанные методы держим ПО ССЫЛКЕ: ``self._on_thread_exception``
        # порождает новый объект на каждом обращении, и сравнение
        # ``threading.excepthook is self._on_thread_exception`` было бы False
        # ВСЕГДА — то есть снятие «только если слот всё ещё наш» не сработало бы
        # никогда, а чужая замена затиралась бы молча.
        self._hook_thread = self._on_thread_exception
        self._hook_sys = self._on_sys_exception
        self._hook_warning = self._on_warning

    # ------------------------------------------------------------------
    # Публичная поверхность
    # ------------------------------------------------------------------

    @property
    def installed(self) -> bool:
        """Стоят ли хуки. ``uninstall()`` переводит в False необратимо для этого объекта."""
        return self._installed

    def counters(self) -> Dict[str, int]:
        """Копия трёх чисел. ВСЕГДА все три ключа, даже нулями.

        Копия, а не живой словарь: при живом ``ErrorManager`` источник — его
        ``stats``, где лежит ещё три десятка чужих счётчиков, и отдать его
        наружу значило бы отдать чужое состояние на правку.
        """
        with self._counter_lock:
            return {key: int(self._counters.get(key, 0)) for key in HOOK_COUNTER_KEYS}

    def uninstall(self) -> None:
        """Вернуть три слота прежним значениям. Идемпотентно.

        Слот восстанавливается, ТОЛЬКО если он всё ещё наш: если поверх нас
        что-то поставил кто-то другой, откат вернул бы значение позапрошлой
        эпохи и снёс бы чужой хук молча.
        """
        global _installed
        with _install_lock:
            if not self._installed:
                return
            if threading.excepthook is self._hook_thread and self._prev_threading is not None:
                threading.excepthook = self._prev_threading
            if sys.excepthook is self._hook_sys and self._prev_sys is not None:
                sys.excepthook = self._prev_sys
            if warnings.showwarning is self._hook_warning and self._prev_showwarning is not None:
                warnings.showwarning = self._prev_showwarning
            self._installed = False
            if _installed is self:
                _installed = None

    # ------------------------------------------------------------------
    # Установка (зовёт только install_process_hooks, под _install_lock)
    # ------------------------------------------------------------------

    def _install(self) -> None:
        self._prev_threading = threading.excepthook
        self._prev_sys = sys.excepthook
        self._prev_showwarning = warnings.showwarning
        threading.excepthook = self._hook_thread
        sys.excepthook = self._hook_sys
        warnings.showwarning = self._hook_warning
        self._installed = True

    def _slots_are_ours(self) -> bool:
        """Все три слота всё ещё заняты нами.

        Нужно ПРИ ПОВТОРНОЙ установке: тестовая фикстура (и любая чужая уборка)
        возвращает слоты, не зная про нас, и объект-одиночка остался бы
        «установленным» при пустых слотах — следующий ``install`` вернул бы его
        же, и хуки не встали бы вовсе.
        """
        return (
            threading.excepthook is self._hook_thread
            and sys.excepthook is self._hook_sys
            and warnings.showwarning is self._hook_warning
        )

    def _forget(self) -> None:
        """Признать себя недействующим, не трогая слоты (их занял кто-то другой)."""
        self._installed = False

    # ------------------------------------------------------------------
    # Хуки
    # ------------------------------------------------------------------

    def _on_thread_exception(self, args: Any) -> None:
        """``threading.excepthook``: исключение, вышедшее из ``Thread.run``."""
        exc = getattr(args, "exc_value", None)
        exc_type = getattr(args, "exc_type", None)
        tb = getattr(args, "exc_traceback", None)
        thread = getattr(args, "thread", None)
        name = getattr(thread, "name", None) or threading.current_thread().name
        self._handle_exception(exc_type, exc, tb, str(name), "threading.excepthook")
        self._call_previous(self._prev_threading, args)

    def _on_sys_exception(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """``sys.excepthook``: исключение, дошедшее до верха ГЛАВНОГО потока."""
        self._handle_exception(exc_type, exc, tb, threading.current_thread().name, "sys.excepthook")
        self._call_previous(self._prev_sys, exc_type, exc, tb)

    def _on_warning(
        self,
        message: Any,
        category: Any,
        filename: Any,
        lineno: Any,
        file: Any = None,
        line: Any = None,
    ) -> None:
        """``warnings.showwarning``: то, что фильтры ``warnings`` пропустили.

        Прежний ``showwarning`` НЕ зовётся — та же семантика, что у
        ``logging.captureWarnings``: предупреждение перехвачено и уехало в
        плоскость логов, второй раз в stderr его печатать незачем.
        """
        if getattr(_local, "busy", False):
            self._count_reentrant("warnings_captured")
            return
        self._bump("warnings_captured")
        self._deliver_warning(message, category, filename, lineno)

    # ------------------------------------------------------------------
    # Общая механика
    # ------------------------------------------------------------------

    def _handle_exception(self, exc_type: Any, exc: Any, tb: Any, thread_name: str, hook: str) -> None:
        if exc is None:
            # Поток гасят на выходе интерпретатора: значения нет, инцидента тоже.
            return
        if isinstance(exc, (SystemExit, KeyboardInterrupt)):
            # Не инцидент — ровно как решает stdlib: это штатный способ выйти.
            return
        if getattr(_local, "busy", False):
            self._count_reentrant("thread_exceptions")
            return
        self._bump("thread_exceptions")
        self._deliver_error(exc, exc_type, tb, thread_name, hook)

    def _deliver_error(self, exc: Any, exc_type: Any, tb: Any, thread_name: str, hook: str) -> None:
        _local.busy = True
        try:
            report = getattr(self._services, "report_error", None)
            if not callable(report):
                raise AttributeError(f"{type(self._services).__name__} без report_error")
            # Трасса собирается ИЗ АРГУМЕНТОВ, а не через traceback.format_exc():
            # у sys.excepthook активного исключения уже нет (sys.exc_info() пуст),
            # и format_exc() вернул бы «NoneType: None» — запись без трассы, то
            # есть ровно то, чего механизм и не должен допускать.
            trace = "".join(traceback.format_exception(exc_type, exc, tb))
            report(
                exc,
                context=f"thread:{thread_name}",
                thread=thread_name,
                traceback=trace,
                hook=hook,
            )
        except BaseException as delivery_exc:  # noqa: BLE001 — хук не имеет права бросить наружу
            self._bump("hook_delivery_failures")
            emergency_log(
                _EMERGENCY_NAME,
                "ERROR",
                "%s: инцидент потока %r не доставлен в плоскость ошибок (%r)",
                hook,
                thread_name,
                delivery_exc,
            )
        finally:
            _local.busy = False

    def _deliver_warning(self, message: Any, category: Any, filename: Any, lineno: Any) -> None:
        thread_name = threading.current_thread().name
        _local.busy = True
        try:
            log_warning = getattr(self._services, "_log_warning", None)
            if not callable(log_warning):
                raise AttributeError(f"{type(self._services).__name__} без _log_warning")
            name = getattr(category, "__name__", None) or str(category)
            log_warning(
                f"{name}: {message}",
                module=_WARNINGS_MODULE,
                category=name,
                filename=str(filename),
                lineno=lineno,
                thread=thread_name,
            )
        except BaseException as delivery_exc:  # noqa: BLE001 — хук не имеет права бросить наружу
            self._bump("hook_delivery_failures")
            emergency_log(
                _EMERGENCY_NAME,
                "ERROR",
                "warnings.showwarning: предупреждение потока %r не доставлено в плоскость логов (%r)",
                thread_name,
                delivery_exc,
            )
        finally:
            _local.busy = False

    def _count_reentrant(self, event_key: str) -> None:
        """Событие пришло ВО ВРЕМЯ доставки другого — в том же потоке.

        Считаются ОБА числа, и это решение, а не удвоение. ``event_key`` растёт,
        потому что событие действительно произошло: счётчик событий, молчащий
        про вложенные, перестал бы отвечать на вопрос «сколько их было».
        ``hook_delivery_failures`` растёт, потому что доставки не будет —
        рекурсия в уже сломанном маршруте хуже потерянной записи. Пара чисел
        различает «дорога упала» и «дорога сама себя разбудила»: во втором
        случае они выросли одновременно.
        """
        with self._counter_lock:
            self._counters[event_key] = int(self._counters.get(event_key, 0)) + 1
            self._counters["hook_delivery_failures"] = int(self._counters.get("hook_delivery_failures", 0)) + 1

    def _bump(self, key: str) -> None:
        with self._counter_lock:
            self._counters[key] = int(self._counters.get(key, 0)) + 1

    @staticmethod
    def _call_previous(previous: Optional[Callable[..., Any]], *args: Any) -> None:
        """Отдать событие прежнему хуку. Его отказ — не наш инцидент, но и не тишина."""
        if previous is None:
            return
        try:
            previous(*args)
        except BaseException as exc:  # noqa: BLE001 — второе исключение поверх первого недопустимо
            emergency_log(_EMERGENCY_NAME, "ERROR", "прежний хук %r отказал: %r", previous, exc)


def _resolve_counter_store(services: Any) -> Dict[str, Any]:
    """Словарь, в котором живут три числа: ``ErrorManager.stats`` или приватный.

    Приватный — законное состояние, а не запасной путь: процесс без секции
    ошибок (``config={}``) плоскости ошибок не имеет вовсе, и объявлять её числа
    было бы враньём. Числа при этом не пропадают — их отдаёт
    :meth:`ProcessHooks.counters`.
    """
    get_manager = getattr(services, "get_manager", None)
    manager = None
    if callable(get_manager):
        try:
            manager = get_manager("error")
        except Exception:  # noqa: BLE001 — установка хуков не имеет права упасть из-за реестра
            manager = None
    stats = getattr(manager, "stats", None) if manager is not None else None
    if isinstance(stats, dict):
        for key in HOOK_COUNTER_KEYS:
            stats.setdefault(key, 0)
        return stats
    return {key: 0 for key in HOOK_COUNTER_KEYS}


def install_process_hooks(services: Any) -> ProcessHooks:
    """Поставить три процессных хука. Один объект на процесс.

    Повторный вызов при живых хуках возвращает ТОТ ЖЕ объект (``is``) и слоты не
    трогает: наслоение дало бы одну запись на событие дважды.
    """
    global _installed
    with _install_lock:
        current = _installed
        if current is not None:
            if current.installed and current._slots_are_ours():
                return current
            # Слоты забрал кто-то другой (фикстура теста, чужая библиотека).
            # Восстанавливать нечего, но и считать себя действующим нельзя.
            current._forget()
        hooks = ProcessHooks(services)
        hooks._install()
        _installed = hooks
        return hooks


def installed_hooks() -> Optional[ProcessHooks]:
    """Установленный одиночка процесса или ``None``.

    Нужен тем, у кого ссылки на объект нет: командам ``diag.*`` и любому
    readback'у. ``None`` — законный ответ «хуки не стоят», а не ошибка.
    """
    hooks = _installed
    return hooks if hooks is not None and hooks.installed else None
