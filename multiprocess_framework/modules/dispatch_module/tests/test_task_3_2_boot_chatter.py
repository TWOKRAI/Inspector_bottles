# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.2 плана ``observability-closure`` — К1-К4 на ``Dispatcher``.

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t32-tester``) на коммите ``9d9cb8e1`` — ДО правки Task 3.2,
не видел diff/реализацию, не читал ``_impl/`` (директории с таким именем в этом
дереве нет). Источник критериев — раздел «### Task 3.2» в
``plans/observability-closure/phase-3-store-and-signal.md`` (контракт К1-К8), а НЕ
сегодняшнее поведение кода.

======================================================================
Что здесь проверяется (К1-К4, половина «Dispatcher» из брифа)
======================================================================

* К1 — на буте при INFO ноль строк ``Handler '…' registered successfully``.
* К2 — вместо них ровно ОДНА INFO-сводка с ЛИТЕРАЛЬНЫМ числом (**ДОГАДКА
  тестера** — см. класс ``TestK2…`` ниже).
* К3 — при DEBUG строка возвращается (контроль/анкор для К1: ноль на INFO без
  этого контроля неотличим от «логгер выключили целиком»).
* К4 — сообщение в ``_log_debug`` ОТЛОЖЕНО (``callable``), а не собранная
  f-строка (Ф7.1).

Что НЕ проверяется здесь (сознательно):
* К5/К7 «живьём» — нет доступа к запущенному стенду у тестера, это стадия
  лида.
* К1 «счёт строк в СТОРЕ» (в буквальном смысле — через ``ObservabilityStore``,
  а не через спай на ``_log_info``) — отдельный, более сквозной тест лежит в
  ``channel_routing_module/tests/test_task_3_2_boot_chatter_store.py``
  (см. докстринг того файла — почему он в отдельной директории).
* Раскладка ``CommandManager`` (``command_manager.py:213``) — параллельный
  набор в ``command_module/tests/test_task_3_2_boot_chatter.py``. Регистрация
  команды дёргает и `CommandManager._log_info`, и (внутри) `Dispatcher._log_info`
  собственного вложенного диспетчера — здесь проверяется ТОЛЬКО прямой вызов
  `Dispatcher.register_handler`, не композиция через `CommandManager`.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.dispatch_module.core.dispatcher import Dispatcher


def _resolve(msg: Any) -> str:
    """Превратить сообщение (готовая строка ИЛИ Ф1.4-``callable``) в текст.

    Вызов callable здесь безопасен: ни один аргумент в этом файле не имеет
    побочных эффектов (чистые ``lambda: f"…"``), а тесты K3/K4 обязаны
    прочитать РЕЗУЛЬТАТ, не только факт callable-ности.
    """
    return msg() if callable(msg) else msg


@pytest.fixture
def dispatcher():
    mgr = Dispatcher("probe_dispatcher")
    mgr.initialize()
    yield mgr
    mgr.shutdown()


class TestK1NoInfoRowForHandlerRegisteredWording:
    """К1: ноль строк ``Handler '…' registered successfully`` на INFO.

    Сегодня ``dispatcher.py:269`` зовёт ``self._log_info(f"Handler '{key}' "
    f"registered successfully", module=LOG_SOURCE)`` на КАЖДУЮ регистрацию —
    тест обязан упасть здесь и падает (проверено прогоном, см. отчёт тестера).

    Существование-анкор для этого «ноль» — класс ``TestK3…`` НИЖЕ в этом же
    файле: он подтверждает, что ноль означает «перенесено на DEBUG», а не
    «логгер сломан целиком» (правило проекта: негативное утверждение о
    содержимом лога требует парной проверки достижимости в том же наборе).
    """

    def test_registering_a_handler_does_not_log_info_wording(self, dispatcher) -> None:
        dispatcher._log_info = MagicMock()

        ok = dispatcher.register_handler("foo", lambda m: m)
        assert ok is True, "предусловие теста: регистрация обязана пройти успешно"

        texts = [_resolve(c.args[0]) for c in dispatcher._log_info.call_args_list]
        matches = [t for t in texts if "registered successfully" in t]
        assert matches == [], (
            "К1 нарушен: 'Handler ... registered successfully' всё ещё уходит "
            f"в _log_info (должно быть DEBUG, см. К3): {texts!r}"
        )


class TestK2OneInfoSummaryWithTheLiteralHandlerCount:
    """К2: сводка — РОВНО одна на процесс, с ЛИТЕРАЛЬНЫМ числом (не ``len()``).

    **ДОГАДКА ТЕСТЕРА (единственная во всём файле, названа громко для лида).**
    Ни ``dispatcher.py``, ни план Task 3.2 не называют имя хука, которым
    процесс просит менеджер подвести итог регистрации (сама сводка обязана
    случиться РОВНО ОДИН раз за процесс, а ``register_handler`` вызывается
    N раз — значит, эмиссия сводки требует отдельной точки входа, которой
    сегодня в коде нет: ``grep -n "summary" dispatcher.py`` — ноль совпадений).
    Метод назван ``log_registration_summary()`` по аналогии с уже
    существующими глагол-объект методами того же класса (``get_all_handlers``,
    ``get_stats`` у соседнего ``CommandManager``). Если реализация выберет
    другое имя — тест ниже останется красным по ``AttributeError`` даже после
    ПРАВИЛЬНОЙ реализации; лиду достаточно переименовать ОДИН вызов в тесте
    (см. память tester'а: red-without-interface-needs-one-named-guessed-hook).

    ``AttributeError`` сегодня на вызове ``log_registration_summary()`` — это
    ожидаемый и единственно верный красный для ЭТОЙ догадки (аналог
    ``NotImplementedError`` для ещё не появившегося символа), поэтому исключение
    НЕ оборачивается в ``pytest.raises`` — оно обязано пробить тест наружу.
    """

    def test_three_registrations_then_summary_mentions_the_literal_three(self, dispatcher) -> None:
        # Три РАЗНЫХ ключа — иначе неотличимо от «переписали тот же ключ трижды».
        dispatcher.register_handler("alpha", lambda m: m)
        dispatcher.register_handler("beta", lambda m: m)
        dispatcher.register_handler("gamma", lambda m: m)

        # Сброс ПОСЛЕ регистраций: построчные вызовы (сегодняшние INFO, будущие
        # DEBUG) не должны путаться со сводкой — интересует только эмиссия
        # самого log_registration_summary().
        dispatcher._log_info = MagicMock()

        dispatcher.log_registration_summary()  # ДОГАДКА — см. докстринг класса

        dispatcher._log_info.assert_called_once()
        (msg,), _kwargs = dispatcher._log_info.call_args
        text = _resolve(msg)
        assert re.search(r"\b3\b", text), (
            f"К2 нарушен: сводка обязана называть ЛИТЕРАЛ 3 (зарегистрировано "
            f"3 обработчика), число не должно быть вычислено из объекта под "
            f"тестом: {text!r}"
        )


class TestK3PerKeyDebugLineSurvivesTheMove:
    """К3 (unit-половина): текст строки НЕ удалён, а перенесён на ``_log_debug``.

    Это контроль/анкор для К1: «ноль на INFO» без этого теста неотличимо от
    «логгер отключили полностью». Живая половина критерия (реальный уровень
    DEBUG действительно показывает строку в файле процесса) — стадия лида,
    здесь недоступна (нет запущенного стенда у тестера).
    """

    def test_the_registered_successfully_text_reaches_log_debug(self, dispatcher) -> None:
        dispatcher._log_debug = MagicMock()

        dispatcher.register_handler("foo", lambda m: m)

        texts = [_resolve(c.args[0]) for c in dispatcher._log_debug.call_args_list]
        matches = [t for t in texts if "Handler 'foo' registered successfully" in t]
        assert matches, (
            "К3 нарушен: строка \"Handler 'foo' registered successfully\" не "
            f"найдена ни в одном вызове _log_debug — она обязана быть "
            f"ПЕРЕНЕСЕНА туда, а не удалена: {texts!r}"
        )


class TestK4TheDebugMessageIsADeferredCallable:
    """К4: сообщение в НОВОМ ``_log_debug`` — ``callable`` (Ф1.4/Ф7.1), не f-строка.

    **Выбранный вид проверки (см. бриф, «unit: подставить логгер, проверить
    callable(msg)»):** подставляем ``MagicMock`` вместо ``_log_debug`` и
    смотрим, ЧТО именно менеджер туда передал — это прямое наблюдение
    аргумента на границе, названной самим критерием (``_log_debug`` — это и
    есть точка, о которой К4 говорит), а не спай на постороннее имя метода.
    Секундный вариант из брифа («сентинел, считающий __str__») сознательно
    пропущен: он был бы избыточен — MagicMock и так НЕ вызывает переданный
    callable сам (лишь записывает объект в call_args), поэтому сам факт
    «объект остался callable, не строка» уже доказывает, что сборка НЕ
    произошла на call site. Присутствие ``_CountingArg``-подобного сентинела
    добавило бы только повторную проверку той же самой вещи через ``LoggerManager``
    целиком — на что уйдёт куда больше кода без нового сигнала.

    Анкор существования ПЕРЕД проверкой формы (правило проекта: негативное/
    производное утверждение без якоря существования вырождается в
    вычисление на пустом множестве) — без него ``candidates[0]`` на пустом
    списке дал бы ``IndexError`` без диагностического сообщения.
    """

    def test_the_new_debug_call_carries_a_callable_not_a_prebuilt_string(self, dispatcher) -> None:
        dispatcher._log_debug = MagicMock()

        dispatcher.register_handler("foo", lambda m: m)

        candidates = [
            c.args[0]
            for c in dispatcher._log_debug.call_args_list
            if "Handler 'foo' registered successfully" in _resolve(c.args[0])
        ]
        assert candidates, (
            "К3 (анкор существования) не выполнен здесь — К4 непроверяем без найденного вызова _log_debug"
        )
        raw_msg = candidates[0]
        assert callable(raw_msg) and not isinstance(raw_msg, str), (
            f"К4 нарушен: аргумент _log_debug обязан быть callable (Ф1.4 lambda), а не готовой строкой: {raw_msg!r}"
        )
        # Не «любой callable» — обязан резолвиться в ПРАВИЛЬНЫЙ текст.
        assert _resolve(raw_msg) == "Handler 'foo' registered successfully"
