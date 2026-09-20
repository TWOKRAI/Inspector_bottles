# -*- coding: utf-8 -*-
"""Авторские hazard-тесты механизма ``process_hooks`` (Task 1.1, C3).

Приёмка тестера (``process_module/tests/test_process_hooks_acceptance.py``)
сторожит КОНТРАКТ: событие → запись → счётчик. Здесь — то, что видно только
изнутри конструкции и чего критерии приёмки не называют:

* хук исполняется **в гибнущем потоке**, синхронно, — значит медленная дорога
  доставки задерживает завершение потока, и это свойство надо не обещать
  обратным, а зафиксировать числом;
* событие может прийти ВНУТРИ доставки другого — рекурсия в уже сломанном
  маршруте хуже потерянной записи;
* у ``sys.excepthook`` активного исключения нет (``sys.exc_info()`` пуст), и
  трасса обязана собираться из аргументов, а не из ``format_exc()``;
* хранилище счётчиков выбирается ОДИН раз, при установке, — «менеджер появился
  позже» имеет наблюдаемую цену, и она названа;
* ``uninstall`` не имеет права снести чужую замену слота, а ``install`` после
  ``uninstall`` не имеет права выдать прежний (уже недействующий) объект.

Ни один тест здесь не заменяет приёмку: они добавочные (правило трёх ролей
авторства в ``.claude/CLAUDE.md``).
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
import warnings

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.process_hooks import (
    HOOK_COUNTER_KEYS,
    install_process_hooks,
    installed_hooks,
)

#: Сколько ждать гибнущий поток. С запасом: любое превышение — это «хук завис»,
#: а зависший тест хуже отсутствующего (он прячет регрессию за таймаутом).
JOIN_DEADLINE_SEC = 5.0


@pytest.fixture(autouse=True)
def _restore_global_hooks():
    """Три слота возвращаются к значению ДО теста независимо от исхода."""
    prev_threading = threading.excepthook
    prev_sys = sys.excepthook
    prev_warn = warnings.showwarning
    yield
    threading.excepthook = prev_threading
    sys.excepthook = prev_sys
    warnings.showwarning = prev_warn


def _manager_config(tmp_path, app: str) -> dict:
    return {
        "app_name": app,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / f"{app}.log")}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


def _raise_named_error(message: str) -> None:
    """Именованная цель потока — её имя обязано оказаться в трассе."""
    raise RuntimeError(message)


def _join_or_fail(thread: threading.Thread, timeout: float = JOIN_DEADLINE_SEC) -> float:
    started = time.perf_counter()
    thread.join(timeout=timeout)
    elapsed = time.perf_counter() - started
    assert not thread.is_alive(), f"поток {thread.name!r} не завершился за {timeout} с — хук завис"
    return elapsed


class _Services:
    """Минимальный носитель утиного протокола ``services``.

    Всё поведение — на замену полей: тесты подменяют ``report_error`` /
    ``_log_warning``, чтобы воспроизвести конкретную опасность.
    """

    def __init__(self, name: str, error_manager=None) -> None:
        self.name = name
        self.error_manager = error_manager
        self.reports: list = []
        self.warnings: list = []

    def report_error(self, exc, context=None, **fields) -> None:
        self.reports.append((exc, context, fields))

    def _log_warning(self, message, **kwargs) -> None:
        self.warnings.append((message, kwargs))

    def get_manager(self, name: str):
        return self.error_manager if name == "error" else None


# ---------------------------------------------------------------------------
# Реентрантность
# ---------------------------------------------------------------------------


class TestReentrancy:
    def test_warning_raised_inside_error_delivery_is_counted_not_recursed(self) -> None:
        """Предупреждение ВНУТРИ доставки инцидента не уходит второй дорогой.

        Опасность конструкции: обе дороги живут в одном потоке, и доставка
        инцидента (плоскость ошибок → логгер → каналы) сама вправе позвать
        ``warnings.warn``. Без потокового сторожа это вход в хук предупреждений
        из хука исключений — и дальше как повезёт: от лишней записи до рекурсии.
        """
        services = _Services("reentrant-error")

        def _report_error(exc, context=None, **fields):
            services.reports.append((exc, context, fields))
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn("предупреждение изнутри доставки", UserWarning)

        services.report_error = _report_error  # type: ignore[method-assign]

        hooks = install_process_hooks(services)
        try:
            thread = threading.Thread(target=_raise_named_error, args=("nested",), name="nested-worker", daemon=True)
            thread.start()
            _join_or_fail(thread)

            counters = hooks.counters()
            assert counters["thread_exceptions"] == 1
            # Событие произошло — счётчик событий честен...
            assert counters["warnings_captured"] == 1
            # ...но доставки не было: вложенное предупреждение в плоскость логов
            # не поехало, и это зафиксировано числом, а не молчанием.
            assert counters["hook_delivery_failures"] == 1
            assert services.warnings == [], f"вложенное предупреждение всё-таки уехало: {services.warnings}"
            assert len(services.reports) == 1
        finally:
            hooks.uninstall()

    def test_warning_raised_inside_warning_delivery_does_not_recurse(self) -> None:
        """Дорога предупреждений, сама предупреждающая, не уходит в рекурсию.

        Самый неприятный из двух случаев: у него нет естественного дна.
        Ограничитель в фейке (``depth``) стоит НЕ вместо проверки, а чтобы
        сломанная реализация падала ``AssertionError``, а не вешала прогон
        рекурсией — тест, который висит, хуже отсутствующего.
        """
        services = _Services("reentrant-warning")
        depth = {"n": 0}

        def _log_warning(message, **kwargs):
            services.warnings.append((message, kwargs))
            depth["n"] += 1
            if depth["n"] > 3:
                return
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn(f"вложенное-{depth['n']}", UserWarning)

        services._log_warning = _log_warning  # type: ignore[method-assign]

        hooks = install_process_hooks(services)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn("внешнее", UserWarning)

            assert len(services.warnings) == 1, f"дорога позвана повторно: {services.warnings}"
            counters = hooks.counters()
            assert counters["warnings_captured"] == 2, "вложенное предупреждение обязано быть посчитано"
            assert counters["hook_delivery_failures"] == 1
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# Трасса без активного исключения
# ---------------------------------------------------------------------------


class TestTracebackWithoutExcInfo:
    def test_sys_excepthook_builds_the_trace_from_its_arguments(self) -> None:
        """``sys.excepthook`` зовут, когда ``sys.exc_info()`` уже пуст.

        ``traceback.format_exc()`` в этот момент вернул бы «NoneType: None», то
        есть запись без трассы — и дефект был бы виден только глазами, в поле,
        которое «почему-то пустое». Проверяем не отсутствие пустоты, а наличие
        имени функции, поднявшей исключение.

        **Прежний хук подменён спаем НАМЕРЕННО, и это не обход проверки.** В
        слоте ``sys.excepthook`` под прогоном сидит перехватчик ``pytest-qt``
        («Exceptions caught in Qt event loop»), и любой вызов слота он засчитает
        тесту как отказ — воспроизведено: тест краснел с трассой самого зонда.
        Спай на его месте делает вторую половину свойства ПРОВЕРЯЕМОЙ: событие
        обязано уйти прежнему хуку тем же кортежем, а не только нам.
        """
        services = _Services("sys-hook")
        passed_through: list = []

        def _previous(exc_type, exc_value, tb) -> None:
            passed_through.append((exc_type, exc_value, tb))

        sys.excepthook = _previous
        hooks = install_process_hooks(services)
        try:
            try:
                _raise_named_error("from-main")
            except RuntimeError as exc:
                exc_type, exc_value, tb = type(exc), exc, exc.__traceback__
            # Ключевая часть: активного исключения больше нет.
            assert sys.exc_info() == (None, None, None)
            sys.excepthook(exc_type, exc_value, tb)

            assert len(services.reports) == 1
            _exc, context, fields = services.reports[0]
            assert context == "thread:MainThread"
            assert fields["thread"] == "MainThread"
            assert fields["hook"] == "sys.excepthook"
            assert "_raise_named_error" in fields["traceback"], fields["traceback"]
            assert hooks.counters()["thread_exceptions"] == 1
            assert passed_through == [(exc_type, exc_value, tb)], "событие не доехало прежнему хуку"
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# Что НЕ инцидент
# ---------------------------------------------------------------------------


class TestNonIncidents:
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_system_exit_in_a_thread_is_not_counted(self) -> None:
        """``SystemExit`` — штатный выход, а не отказ (то же решение, что у stdlib).

        Если бы он считался, счётчик ``thread_exceptions`` рос бы на КАЖДОМ
        штатном останове потока, и ненулевое значение перестало бы означать
        «в процессе что-то упало» — то есть подсказка ``system_overview``
        светилась бы на здоровой системе постоянно.
        """
        services = _Services("system-exit")
        hooks = install_process_hooks(services)
        try:
            for exc_factory, name in ((SystemExit, "exit-worker"), (KeyboardInterrupt, "interrupt-worker")):

                def _quit(factory=exc_factory) -> None:
                    raise factory()

                thread = threading.Thread(target=_quit, name=name, daemon=True)
                thread.start()
                _join_or_fail(thread)

            assert hooks.counters() == {key: 0 for key in HOOK_COUNTER_KEYS}
            assert services.reports == []
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# Слоты: чужая замена, повторная установка
# ---------------------------------------------------------------------------


class TestSlotOwnership:
    def test_uninstall_does_not_touch_a_slot_taken_by_someone_else(self) -> None:
        """Чужой хук поверх нашего не сносится откатом.

        Иначе ``uninstall`` вернул бы значение позапрошлой эпохи и снёс бы
        чужого наблюдателя молча — класс дефекта, который ищут неделями, потому
        что виновник к тому моменту уже завершился.
        """
        services = _Services("slot-owner")
        prev_sys = sys.excepthook
        prev_warn = warnings.showwarning
        hooks = install_process_hooks(services)

        def _foreign(args) -> None:  # чужой наблюдатель, поставленный ПОСЛЕ нас
            return None

        threading.excepthook = _foreign
        hooks.uninstall()

        assert threading.excepthook is _foreign, "откат снёс чужую замену слота"
        assert sys.excepthook is prev_sys
        assert warnings.showwarning is prev_warn

    def test_install_after_uninstall_returns_a_new_object(self) -> None:
        """Снятый объект не воскрешается: ``install`` после ``uninstall`` — НОВЫЙ.

        ``installed`` у снятого остаётся False навсегда, и вернуть его значило бы
        отдать наружу объект, чьи ``_prev_*`` описывают уже неактуальную эпоху.
        """
        services = _Services("reinstall")
        first = install_process_hooks(services)
        first.uninstall()
        assert first.installed is False
        assert installed_hooks() is None

        second = install_process_hooks(services)
        try:
            assert second is not first
            assert installed_hooks() is second
        finally:
            second.uninstall()

    def test_install_recovers_when_the_slots_were_restored_behind_our_back(self) -> None:
        """Слоты вернули мимо нас — следующий ``install`` обязан встать заново.

        Ровно это делает автофикстура тестового файла (и любая чужая уборка):
        она кладёт в слоты прежние значения, ничего не зная про наш объект. Без
        распознавания такого состояния одиночка навсегда остался бы
        «установленным» при пустых слотах, и хуки не встали бы больше никогда —
        в прогоне, где падение одного теста молча обезоруживает все следующие.
        """
        services = _Services("stale-singleton")
        prev_threading = threading.excepthook
        first = install_process_hooks(services)
        # Уборка «мимо нас»: слоты возвращены, uninstall() не звали.
        threading.excepthook = prev_threading

        second = install_process_hooks(services)
        try:
            assert second is not first, "install вернул объект, чьих хуков в слотах уже нет"
            assert threading.excepthook is second._hook_thread
        finally:
            second.uninstall()


# ---------------------------------------------------------------------------
# Хранилище счётчиков
# ---------------------------------------------------------------------------


class TestCounterStore:
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_manager_that_appears_after_install_does_not_get_the_numbers(self, tmp_path) -> None:
        """Хранилище выбирается ОДИН раз — при установке. Цена названа.

        Это не дефект, а свойство с последствием для проводки: поставь фреймворк
        хуки ДО подъёма плоскости ошибок — записи в неё пошли бы (дорога
        ``report_error`` жива), а ЧИСЛА остались бы в приватном словаре, и
        ``introspect.observability`` показывал бы ноль при непустом
        ``errors.log``. Отсюда порядок в ``_apply_managers_bundle``: хуки после
        менеджеров. Тест сторожит именно наблюдаемое следствие, чтобы порядок
        нельзя было переставить молча.
        """
        error_mgr = ErrorManager(manager_name="late-error", config=_manager_config(tmp_path, "late_error"))
        error_mgr.initialize()
        services = _Services("late-manager")
        hooks = install_process_hooks(services)
        try:
            services.error_manager = error_mgr  # менеджер появился ПОСЛЕ установки

            thread = threading.Thread(target=_raise_named_error, args=("late",), name="late-worker", daemon=True)
            thread.start()
            _join_or_fail(thread)

            assert hooks.counters()["thread_exceptions"] == 1
            assert error_mgr.get_stats()["thread_exceptions"] == 0, (
                "число уехало в менеджер, которого при установке не было — хранилище выбирается лениво?"
            )
        finally:
            hooks.uninstall()
            error_mgr.shutdown()

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_counters_survive_manager_reconfigure(self, tmp_path) -> None:
        """``reconfigure`` пересобирает каналы, но НЕ словарь счётчиков.

        Хранилище хуков — ``ErrorManager.stats``, тот же объект, что живёт с
        конструктора. Пересоздай его пересборка (как пересоздаётся дерево
        правил), и хуки продолжили бы писать в осиротевший словарь: числа росли
        бы у ``hooks.counters()`` и стояли бы у ``get_stats()`` — расхождение,
        которое видно только тому, кто спросит оба.
        """
        error_mgr = ErrorManager(manager_name="reconf-error", config=_manager_config(tmp_path, "reconf_error"))
        error_mgr.initialize()
        services = _Services("reconfigure", error_manager=error_mgr)
        hooks = install_process_hooks(services)
        try:
            thread = threading.Thread(target=_raise_named_error, args=("before",), name="before-worker", daemon=True)
            thread.start()
            _join_or_fail(thread)
            assert error_mgr.get_stats()["thread_exceptions"] == 1

            assert error_mgr.reconfigure({"app_name": "reconf_error_2"}) is True

            assert error_mgr.get_stats()["thread_exceptions"] == 1, "пересборка обнулила счётчик хуков"
            assert hooks.counters()["thread_exceptions"] == 1

            thread = threading.Thread(target=_raise_named_error, args=("after",), name="after-worker", daemon=True)
            thread.start()
            _join_or_fail(thread)
            assert error_mgr.get_stats()["thread_exceptions"] == 2, "после пересборки числа пишутся мимо менеджера"
            assert hooks.counters()["thread_exceptions"] == 2
        finally:
            hooks.uninstall()
            error_mgr.shutdown()


# ---------------------------------------------------------------------------
# Цена доставки
# ---------------------------------------------------------------------------


class TestDeliveryCost:
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_a_slow_road_holds_the_dying_thread(self) -> None:
        """Хук СИНХРОНЕН и держит гибнущий поток ровно столько, сколько дорога.

        Обратной гарантии («хук не блокирует») здесь нет, и выдумывать её нельзя:
        ``threading.excepthook`` исполняется внутри ``Thread._bootstrap_inner``
        гибнущего потока, и не держать его можно было бы только через очередь и
        отдельного писателя — механизм, которого задача 1.1 сознательно не
        строит. Вместо обещания зафиксировано ЧИСЛО: медленная доставка
        задерживает завершение потока на своё время.

        Практическое следствие, ради которого тест и написан: приёмка (и
        ``diag.thread_raise``) ждут поток с конечным пределом, поэтому дорога
        доставки не имеет права быть медленной — а если станет, покраснеет
        здесь, а не таймаутом в чужом тесте.
        """
        delay = 0.3
        services = _Services("slow-road")

        def _slow_report(exc, context=None, **fields):
            time.sleep(delay)
            services.reports.append((exc, context, fields))

        services.report_error = _slow_report  # type: ignore[method-assign]

        hooks = install_process_hooks(services)
        try:
            thread = threading.Thread(target=_raise_named_error, args=("slow",), name="slow-worker", daemon=True)
            thread.start()
            elapsed = _join_or_fail(thread)

            # Половина задержки, а не вся: гранулярность таймера Windows — 15.6 мс,
            # и точное сравнение здесь мерило бы планировщик, а не свойство.
            assert elapsed >= delay / 2, f"поток завершился за {elapsed:.3f} с — доставка ушла в сторону?"
            assert len(services.reports) == 1
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# Дороги нет вовсе
# ---------------------------------------------------------------------------


class TestMissingRoad:
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_services_without_report_error_counts_a_delivery_failure(self, caplog) -> None:
        """``services`` без ``report_error`` — отказ доставки, а не падение хука.

        Отличается от «дорога бросила» (A3 приёмки) причиной, но обязано
        отличаться и от ТИШИНЫ: без счётчика процесс с неполным протоколом
        выглядел бы как процесс без исключений.
        """

        class _Bare:
            name = "bare-services"

            def get_manager(self, name):
                return None

        services = _Bare()
        thread_name = f"bare-worker-{uuid.uuid4().hex[:8]}"
        hooks = install_process_hooks(services)
        try:
            with caplog.at_level("ERROR", logger="multiprocess_framework.modules.logger_module.core.process_hooks"):
                thread = threading.Thread(target=_raise_named_error, args=("bare",), name=thread_name, daemon=True)
                thread.start()
                _join_or_fail(thread)

            counters = hooks.counters()
            assert counters["thread_exceptions"] == 1
            assert counters["hook_delivery_failures"] == 1
            assert any(thread_name in r.getMessage() for r in caplog.records if r.levelname == "ERROR"), [
                r.getMessage() for r in caplog.records
            ]
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# Проброс прежнему хуку (ревью Ф0, T1)
# ---------------------------------------------------------------------------


class TestPreviousHookReceivesTheEvent:
    """T1 (находка ревью): §3.2 контракта обещает проброс ПРЕЖНЕМУ хуку ПОСЛЕ
    доставки, а сторожа на это свойство не было — только на то, что доставка
    состоялась, и отдельно (в приёмке) на сам факт вызова прежнего sys-хука.
    Здесь обе половины (доставка И проброс) проверяются ОДНИМ тестом на
    ОДНО событие — иначе можно было бы сломать любую из двух половин и не
    заметить по другой.
    """

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_threading_excepthook_delivers_and_forwards_to_the_previous_hook(self) -> None:
        """Спай кладётся в слот ДО установки — тогда он и есть ``_prev_threading``,
        и прежний pytest'овский сборщик (который в трассу не пишет и событие не
        отдаёт) в тест не вмешивается вовсе.
        """
        services = _Services("prev-threading")
        received: list = []

        def _previous(args) -> None:
            received.append(args)

        threading.excepthook = _previous
        hooks = install_process_hooks(services)
        try:
            thread = threading.Thread(
                target=_raise_named_error, args=("prev-hook",), name="prev-hook-worker", daemon=True
            )
            thread.start()
            _join_or_fail(thread)

            assert len(services.reports) == 1, "доставка в services не состоялась"
            assert len(received) == 1, "прежний threading.excepthook не был позван"
            assert received[0].exc_value is services.reports[0][0], (
                "прежнему хуку ушёл не тот же объект исключения, что уехал в доставку"
            )
        finally:
            hooks.uninstall()

    def test_sys_excepthook_delivers_and_forwards_to_the_previous_hook(self) -> None:
        """``sys.excepthook`` зовут напрямую (не через реальный крах главного
        потока) — тем же приёмом, что в ``TestTracebackWithoutExcInfo``, но
        предмет здесь другой: не форма трассы, а сам факт проброса кортежа.
        """
        services = _Services("prev-sys")
        received: list = []

        def _previous(exc_type, exc_value, tb) -> None:
            received.append((exc_type, exc_value, tb))

        sys.excepthook = _previous
        hooks = install_process_hooks(services)
        try:
            try:
                _raise_named_error("prev-sys-hook")
            except RuntimeError as exc:
                exc_type, exc_value, tb = type(exc), exc, exc.__traceback__
            sys.excepthook(exc_type, exc_value, tb)

            assert len(services.reports) == 1, "доставка в services не состоялась"
            assert received == [(exc_type, exc_value, tb)], "прежний sys.excepthook не получил тот же кортеж"
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# counters() — копия (ревью Ф0, T6)
# ---------------------------------------------------------------------------


class TestCountersReturnsACopy:
    """T6 (находка ревью): ``counters()`` документирован как копия, но сторожа
    на это не было — только на форму (три ключа). С реальным ``ErrorManager``,
    чтобы источником чисел был именно его ``stats``, а не приватный словарь.
    """

    def test_mutating_the_returned_dict_does_not_touch_the_source(self, tmp_path) -> None:
        error_mgr = ErrorManager(manager_name="t6-error", config=_manager_config(tmp_path, "t6_error"))
        error_mgr.initialize()
        services = _Services("t6-copy", error_manager=error_mgr)
        hooks = install_process_hooks(services)
        try:
            counters = hooks.counters()
            assert set(counters) == set(HOOK_COUNTER_KEYS)

            counters["thread_exceptions"] = 999

            assert error_mgr.get_stats()["thread_exceptions"] != 999, "правка возвращённого dict уехала в источник"
            assert hooks.counters()["thread_exceptions"] != 999, "второй вызов counters() увидел чужую правку"
        finally:
            hooks.uninstall()
            error_mgr.shutdown()
