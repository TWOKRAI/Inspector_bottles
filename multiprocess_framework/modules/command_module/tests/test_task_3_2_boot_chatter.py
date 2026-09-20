# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.2 плана ``observability-closure`` — К1-К4 на ``CommandManager``.

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t32-tester``) на коммите ``9d9cb8e1`` — ДО правки Task 3.2,
не видел diff/реализацию, не читал ``_impl/``. Источник критериев — раздел
«### Task 3.2» в ``plans/observability-closure/phase-3-store-and-signal.md``.

======================================================================
Что здесь проверяется — параллельно ``dispatch_module``'ному набору
======================================================================

Те же К1-К4, но на границе ``command_manager.py:213``
(``self._log_info(f"Command '{command_name}' registered successfully")``).

**Важная композиционная деталь, найденная прогоном (не догадка — проверено):**
``CommandManager.__init__`` строит СОБСТВЕННЫЙ внутренний ``self.dispatcher =
Dispatcher(...)`` и ``register_command()`` делегирует туда через
``self.dispatcher.register_handler(...)``. Значит один вызов
``register_command("foo", …)`` СЕГОДНЯ порождает ДВЕ разные INFO-строки на
ДВУХ разных объектах:

* ``mgr._log_info`` (сам ``CommandManager``) → ``"Command 'foo' registered
  successfully"``;
* ``mgr.dispatcher._log_info`` (вложенный ``Dispatcher``) → ``"Handler 'foo'
  registered successfully"``.

Этот файл проверяет ТОЛЬКО первую границу (``mgr._log_info``/``mgr._log_debug``
— то, что называет сам бриф для ``command_manager.py:213``). Вторая граница
(вложенный ``Dispatcher``) уже покрыта ОТДЕЛЬНО и полностью в
``dispatch_module/tests/test_task_3_2_boot_chatter.py`` (прямой вызов
``Dispatcher.register_handler``, без обёртки ``CommandManager``) — повторять
её здесь означало бы дублировать тот же самый контракт на том же самом
классе. Название находки — потому что бриф сам не проговаривал эту
композицию, и без прогона легко было бы спутать «ноль вызовов
``mgr._log_info``» с «ноль строк в сторе вообще» (в сторе, если процесс
регистрирует команды, всё ещё будет по ОДНОЙ строке от каждого измерения —
это и объясняет РАВЕНСТВО Handler/Command в измеренной базе плана: 71/71,
93/93 и т.д. — каждая команда даёт ОБЕ строки).

Что НЕ проверяется здесь: К5/К7 «живьём» (стадия лида); сквозной тест через
реальный ``ObservabilityStore`` — см.
``channel_routing_module/tests/test_task_3_2_boot_chatter_store.py``.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager


def _resolve(msg: Any) -> str:
    """Превратить сообщение (готовая строка ИЛИ Ф1.4-``callable``) в текст."""
    return msg() if callable(msg) else msg


@pytest.fixture
def command_manager():
    mgr = CommandManager("probe_commands")
    mgr.initialize()
    yield mgr
    mgr.shutdown()


class TestK1NoInfoRowForCommandRegisteredWording:
    """К1: ноль строк ``Command '…' registered successfully`` на INFO.

    Сегодня ``command_manager.py:213`` зовёт ``self._log_info(f"Command '"
    f"{command_name}' registered successfully", module=LOG_SOURCE)`` на
    каждую регистрацию.

    Анкор существования для этого «ноль» — ``TestK3…`` ниже в этом же файле.
    """

    def test_registering_a_command_does_not_log_info_wording(self, command_manager) -> None:
        command_manager._log_info = MagicMock()

        ok = command_manager.register_command("ping", lambda data: {"ok": True})
        assert ok is True, "предусловие теста: регистрация обязана пройти успешно"

        texts = [_resolve(c.args[0]) for c in command_manager._log_info.call_args_list]
        matches = [t for t in texts if "registered successfully" in t]
        assert matches == [], (
            "К1 нарушен: 'Command ... registered successfully' всё ещё уходит "
            f"в _log_info (должно быть DEBUG, см. К3): {texts!r}"
        )


class TestK2OneInfoSummaryWithTheLiteralCommandCount:
    """К2: сводка — РОВНО одна, с ЛИТЕРАЛЬНЫМ числом команд.

    **ДОГАДКА ТЕСТЕРА** — та же, что в ``dispatch_module``'ном файле, для
    консистентности одно и то же имя на обоих классах:
    ``log_registration_summary()``. ``grep -n "summary"
    command_manager.py`` — ноль совпадений; план Task 3.2 имени тоже не
    называет. ``AttributeError`` сегодня — ожидаемый красный именно для этой
    догадки (см. dispatch_module-файл, класс ``TestK2…``, за полным
    обоснованием техники).
    """

    def test_three_registrations_then_summary_mentions_the_literal_three(self, command_manager) -> None:
        command_manager.register_command("alpha", lambda data: data)
        command_manager.register_command("beta", lambda data: data)
        command_manager.register_command("gamma", lambda data: data)

        command_manager._log_info = MagicMock()  # сброс ПОСЛЕ регистраций

        command_manager.log_registration_summary()  # ДОГАДКА — см. докстринг класса

        command_manager._log_info.assert_called_once()
        (msg,), _kwargs = command_manager._log_info.call_args
        text = _resolve(msg)
        assert re.search(r"\b3\b", text), (
            f"К2 нарушен: сводка обязана называть ЛИТЕРАЛ 3 (зарегистрировано "
            f"3 команды), число не должно быть вычислено из объекта под "
            f"тестом: {text!r}"
        )


class TestK3PerKeyDebugLineSurvivesTheMove:
    """К3 (unit-половина): текст строки НЕ удалён, а перенесён на ``_log_debug``.

    Контроль/анкор для К1 — живая половина (реальный DEBUG в файле) за лидом.
    """

    def test_the_registered_successfully_text_reaches_log_debug(self, command_manager) -> None:
        command_manager._log_debug = MagicMock()

        command_manager.register_command("ping", lambda data: {"ok": True})

        texts = [_resolve(c.args[0]) for c in command_manager._log_debug.call_args_list]
        matches = [t for t in texts if "Command 'ping' registered successfully" in t]
        assert matches, (
            "К3 нарушен: строка \"Command 'ping' registered successfully\" не "
            f"найдена ни в одном вызове _log_debug — она обязана быть "
            f"ПЕРЕНЕСЕНА туда, а не удалена: {texts!r}"
        )


class TestK4TheDebugMessageIsADeferredCallable:
    """К4: сообщение в НОВОМ ``_log_debug`` — ``callable`` (Ф1.4/Ф7.1), не f-строка.

    Тот же выбор вида проверки, что в dispatch_module-файле (см. докстринг
    ``TestK4…`` там за полным обоснованием: почему MagicMock+``callable(msg)``,
    а не отдельный считающий сентинел через реальный ``LoggerManager``).
    """

    def test_the_new_debug_call_carries_a_callable_not_a_prebuilt_string(self, command_manager) -> None:
        command_manager._log_debug = MagicMock()

        command_manager.register_command("ping", lambda data: {"ok": True})

        candidates = [
            c.args[0]
            for c in command_manager._log_debug.call_args_list
            if "Command 'ping' registered successfully" in _resolve(c.args[0])
        ]
        assert candidates, (
            "К3 (анкор существования) не выполнен здесь — К4 непроверяем без найденного вызова _log_debug"
        )
        raw_msg = candidates[0]
        assert callable(raw_msg) and not isinstance(raw_msg, str), (
            f"К4 нарушен: аргумент _log_debug обязан быть callable (Ф1.4 lambda), а не готовой строкой: {raw_msg!r}"
        )
        assert _resolve(raw_msg) == "Command 'ping' registered successfully"
