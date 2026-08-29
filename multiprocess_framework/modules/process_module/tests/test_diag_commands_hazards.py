# -*- coding: utf-8 -*-
"""Авторские hazard-тесты команд ``diag.*`` (Task 1.1 плана observability-closure, ревью Ф0).

Приёмка (``test_process_hooks_acceptance.py``, A8) сторожит счастливый путь: хуки
стоят, команда впрыскивает событие, ответ несёт форму контракта п.10. Здесь — три
опасности, которых у счастливого пути нет:

* T3 — команды вызваны на процессе, где хуки НЕ установлены (свежий процесс,
  упавшая установка, снятые хуки после ``shutdown``) — им некому отдать событие
  на счёт, и отказ обязан быть адресным, а не нулём, похожим на «событий не было»;
* T4 — предел ожидания ``diag.thread_raise`` (``DIAG_JOIN_TIMEOUT_SEC``) читается
  эффективным значением в ответе (``join_timeout_sec``), а не молчаливым
  потолком реализации — иначе «не дождались» неотличимо от «дождались мгновенно»;
* T5 — ``diag.warn`` пишет предупреждение со ``stacklevel=1``: адрес записи — сама
  команда (``builtin_commands.py``), а не диспетчер, который её вызвал.

Ни один тест здесь не заменяет приёмку A8 (правило трёх ролей авторства в
``.claude/CLAUDE.md``).
"""

from __future__ import annotations

import sys
import threading
import time
import warnings

import pytest

from multiprocess_framework.modules.process_module.commands import builtin_commands
from multiprocess_framework.modules.logger_module.core.process_hooks import (
    install_process_hooks,
    installed_hooks,
)


@pytest.fixture(autouse=True)
def _restore_global_hooks():
    """Страховка поверх ``hooks.uninstall()`` каждого теста (правило задачи)."""
    prev_threading = threading.excepthook
    prev_sys = sys.excepthook
    prev_warn = warnings.showwarning
    yield
    threading.excepthook = prev_threading
    sys.excepthook = prev_sys
    warnings.showwarning = prev_warn


class _FakeCommandManager:
    """Тот же приём, что в приёмочном файле: dispatch — обычный dict[command]."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None):
        return self.handlers[command](data or {})


class _BaseDiagServices:
    """``_log_debug`` — общий для всех фейков файла: ``_register_health_commands``
    зовёт его безусловно (строка регистрации), не имея отношения к предмету
    ни одного из трёх тестов ниже.
    """

    def _log_debug(self, *a, **k) -> None: ...


class _NoHooksServices(_BaseDiagServices):
    """Минимум, нужный ``_register_health_commands``: имя + command_manager.

    ``get_manager``/``report_error``/``_log_warning`` здесь намеренно нет — предмет
    T3 в том, что ``diag.*`` отказывает ДО обращения к чему-либо из этого: он
    смотрит на глобальный ``installed_hooks()``, а не на сам ``services``.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.command_manager = _FakeCommandManager()


# ---------------------------------------------------------------------------
# T3 — diag.* без установленных хуков
# ---------------------------------------------------------------------------


class TestDiagCommandsWithoutInstalledHooks:
    """T3 (находка ревью): ``diag.thread_raise``/``diag.warn`` без стоящих хуков
    отвечают адресным отказом (``success: False`` + непустой ``reason``), а не
    исключением и не «успехом» с нулевым счётчиком.
    """

    def test_diag_thread_raise_and_diag_warn_fail_cleanly_without_hooks(self) -> None:
        # Страховка: предмет теста — «хуков нет вовсе», а не то, что оставил сосед.
        leftover = installed_hooks()
        if leftover is not None:
            leftover.uninstall()
        assert installed_hooks() is None, "хуки стоят — тест проверяет не тот сценарий"

        services = _NoHooksServices("diag-no-hooks")
        bc = builtin_commands.BuiltinCommands(services)
        bc._register_health_commands()
        cm = services.command_manager

        for command, data in (
            ("diag.thread_raise", {"message": "no-hooks-probe"}),
            ("diag.warn", {"message": "no-hooks-probe"}),
        ):
            res = cm.dispatch(command, data)
            assert res["success"] is False, f"{command}: success должен быть False без установленных хуков"
            assert isinstance(res.get("reason"), str) and res["reason"], (
                f"{command}: reason должен быть непустой строкой, получено {res.get('reason')!r}"
            )


# ---------------------------------------------------------------------------
# T4 — readback предела ожидания join_timeout_sec
# ---------------------------------------------------------------------------


class _SlowDeliveryServices(_BaseDiagServices):
    """``report_error`` держит гибнущий поток на ``delay`` секунд."""

    def __init__(self, name: str, delay: float) -> None:
        self.name = name
        self.command_manager = _FakeCommandManager()
        self._delay = delay
        self.reports: list = []

    def report_error(self, exc, context=None, **fields) -> None:
        time.sleep(self._delay)
        self.reports.append((exc, context, fields))

    def _log_warning(self, message, **kwargs) -> None:
        pass

    def get_manager(self, name: str):
        return None


class TestDiagThreadRaiseJoinTimeoutReadback:
    """T4 (находка ревью, план §1.2): потолок ожидания читается эффективным
    значением константы, а не молчит — раньше в ответе жил только ``joined``.
    """

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_slow_delivery_reports_joined_false_and_the_effective_timeout(self, monkeypatch) -> None:
        monkeypatch.setattr(builtin_commands, "DIAG_JOIN_TIMEOUT_SEC", 0.01)

        services = _SlowDeliveryServices("diag-slow", delay=0.5)
        hooks = install_process_hooks(services)
        try:
            bc = builtin_commands.BuiltinCommands(services)
            bc._register_health_commands()
            cm = services.command_manager

            thread_name = "t4-slow-worker"
            res = cm.dispatch("diag.thread_raise", {"message": "slow", "thread_name": thread_name})

            assert res["success"] is True
            assert res["joined"] is False, "поток не должен был успеть завершиться за 0.01 с при доставке 0.5 с"
            assert res["join_timeout_sec"] == 0.01

            # Поток продолжает жить (доставка ещё спит) — дождаться его, чтобы
            # не течь: зависший daemon-поток тест не роняет, но проверка "не
            # утекли" — часть правила задачи (join с пределом, не бесконечно).
            leaked = next((t for t in threading.enumerate() if t.name == thread_name), None)
            assert leaked is not None, "поток не найден среди живых — уже завершился раньше срока?"
            leaked.join(timeout=2.0)
            assert not leaked.is_alive(), "поток не завершился даже с запасом в 2 с — доставка зависла"
        finally:
            hooks.uninstall()

    @pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
    def test_normal_delivery_joins_within_the_timeout(self) -> None:
        """Контрольная половина: без медленной доставки — ``joined`` истинно."""
        services = _SlowDeliveryServices("diag-fast", delay=0.0)
        hooks = install_process_hooks(services)
        try:
            bc = builtin_commands.BuiltinCommands(services)
            bc._register_health_commands()
            cm = services.command_manager

            res = cm.dispatch("diag.thread_raise", {"message": "fast"})

            assert res["success"] is True
            assert res["joined"] is True
            assert res["join_timeout_sec"] == builtin_commands.DIAG_JOIN_TIMEOUT_SEC
        finally:
            hooks.uninstall()


# ---------------------------------------------------------------------------
# T5 — diag.warn: stacklevel=1, адрес записи — сама команда
# ---------------------------------------------------------------------------


class _RecordingWarningServices(_BaseDiagServices):
    def __init__(self, name: str) -> None:
        self.name = name
        self.command_manager = _FakeCommandManager()
        self.warnings: list = []

    def report_error(self, exc, context=None, **fields) -> None:
        pass

    def _log_warning(self, message, **kwargs) -> None:
        self.warnings.append(kwargs)

    def get_manager(self, name: str):
        return None


class TestDiagWarnStacklevel:
    """T5 (находка ревью): ``diag.warn`` вызывает ``warnings.warn`` со
    ``stacklevel=1`` — адрес записи (``filename`` в kwargs ``_log_warning``)
    называет саму команду, а не того, кто её позвал.

    Фейковый диспетчер (``_FakeCommandManager.dispatch``) вызывает обработчик
    НАПРЯМУЮ, поэтому «тот, кто позвал» при ``stacklevel=2`` — не боевой
    ``dispatch_module/core/dispatcher.py`` (как в проде, см. докстринг
    ``_cmd_diag_warn``), а этот тестовый файл. Свойство теста от этого не
    страдает: различить 1 и 2 достаточно того, что при 2 адрес перестаёт быть
    ``builtin_commands.py`` — а именно это и проверяется.
    """

    def test_warning_record_is_attributed_to_the_command_not_the_caller(self) -> None:
        services = _RecordingWarningServices("diag-stacklevel")
        hooks = install_process_hooks(services)
        try:
            bc = builtin_commands.BuiltinCommands(services)
            bc._register_health_commands()
            cm = services.command_manager

            res = cm.dispatch("diag.warn", {"message": "stacklevel-probe"})
            assert res["success"] is True

            assert len(services.warnings) == 1, f"ожидалась одна запись предупреждения, получено {services.warnings}"
            filename = str(services.warnings[0].get("filename", ""))
            assert filename.endswith("builtin_commands.py"), (
                f"адрес записи указывает не на саму команду diag.warn: {filename}"
            )
        finally:
            hooks.uninstall()
