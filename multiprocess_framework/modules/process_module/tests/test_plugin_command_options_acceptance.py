"""Слепая приёмка SPI хаба, фреймворк: хук ``command_options`` плагина (строки А26, А27 из ``SPI.acceptance.md``).

Purpose:
    Автоматическая регистрация команд плагина (``_do_configure``) спрашивает у плагина необязательные опции
    регистрации (исполнитель, ключ). Плагин без хука регистрируется как раньше; плохие опции и чужое имя
    не роняют конфигурацию и называются одной строкой ERROR.

    Стенд — настоящие ``CommandManager`` и ``ExecutorManager``; ``CommandManager`` отдаёт вызовы ``register_command``
    подкласс-запись (границу фиксирует сам контракт А26: «ровно два позиционных аргумента, без именованных»);
    строки лога — фейк-логгер в слоте ``managers={"logger": ...}`` менеджера команд и ``ctx.log_*`` контекста.
    Ожидаемые значения — литералы файла приёмки.

Public API:
    Только тесты ``test_a26_*``, ``test_a27_*``.

Stability: lite
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.executor_manager import ExecutorManager

NOT_ACCEPTED = "исполнитель не принят"
_JOIN_S = 10.0


class Lines:
    """Все строки лога стенда: ``(уровень, текст)`` от ``ctx.log_*`` и от логгера менеджера команд."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.records: list[tuple[str, str]] = []

    def add(self, level: str, message: Any) -> None:
        text = str(message() if callable(message) else message)
        with self.guard:
            self.records.append((level, text))

    def of(self, level: str) -> list[str]:
        with self.guard:
            return [m for lvl, m in self.records if lvl == level]

    def containing(self, needle: str) -> list[tuple[str, str]]:
        with self.guard:
            return [(lvl, m) for lvl, m in self.records if needle in m]


class FakeLogger:
    """Слот ``logger`` менеджера команд."""

    def __init__(self, lines: Lines) -> None:
        self.lines = lines

    def debug(self, message: Any, **kw: Any) -> None:
        self.lines.add("DEBUG", message)

    def info(self, message: Any, **kw: Any) -> None:
        self.lines.add("INFO", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self.lines.add("WARNING", message)

    def error(self, message: Any, **kw: Any) -> None:
        self.lines.add("ERROR", message)

    def critical(self, message: Any, **kw: Any) -> None:
        self.lines.add("ERROR", message)


class RecordingCommandManager(CommandManager):
    """Настоящий менеджер команд; каждый вызов ``register_command`` пишется как ``(args, kwargs)`` и исполняется."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.register_calls: list[tuple[tuple, dict]] = []

    def register_command(self, *args: Any, **kwargs: Any) -> bool:
        self.register_calls.append((args, dict(kwargs)))
        return super().register_command(*args, **kwargs)

    def calls_for(self, name: str) -> list[tuple[tuple, dict]]:
        out = []
        for args, kwargs in self.register_calls:
            given = args[0] if args else kwargs.get("command_name")
            if given == name:
                out.append((args, kwargs))
        return out


class Stand:
    """``WorkerManager`` + ``ExecutorManager`` (исполнитель ``io``) + ``CommandManager`` + контекст плагина."""

    def __init__(self) -> None:
        self.lines = Lines()
        self.wm = WorkerManager(manager_name="a26", process=None)
        assert self.wm.initialize() is True
        self.em = ExecutorManager("a26_executors", worker_manager=self.wm)
        assert self.em.initialize() is True
        self.em.load_config({"io": {}})
        self.cm = RecordingCommandManager("a26", managers={"logger": FakeLogger(self.lines)}, executors=self.em)
        assert self.cm.initialize() is True
        self.ctx = MagicMock()
        self.ctx.command_manager = self.cm
        self.ctx.config = {}
        for level in ("debug", "info", "warning", "error"):
            setattr(self.ctx, f"log_{level}", self._logger(level.upper()))

    def _logger(self, level: str) -> Any:
        return lambda message, *a, **kw: self.lines.add(level, message)

    def configure(self, plugin: ProcessModulePlugin) -> None:
        done = threading.Event()
        errors: list[BaseException] = []

        def run() -> None:
            try:
                plugin._do_configure(self.ctx)
            except BaseException as exc:  # noqa: BLE001 — разбирается в потоке теста
                errors.append(exc)
            finally:
                done.set()

        threading.Thread(target=run, daemon=True, name="a26-configure").start()
        assert done.wait(_JOIN_S), "_do_configure завис"
        assert errors == [], errors

    def close(self) -> None:
        for fn in (self.cm.shutdown, self.em.shutdown, self.wm.shutdown):
            done = threading.Event()

            def run(f: Any = fn) -> None:
                try:
                    f()
                except BaseException:  # noqa: BLE001 — уборка не маскирует провал теста
                    pass
                finally:
                    done.set()

            threading.Thread(target=run, daemon=True).start()
            done.wait(_JOIN_S)


@pytest.fixture
def stand():
    s = Stand()
    yield s
    s.close()


class PlainPlugin(ProcessModulePlugin):
    """Плагин без ``command_options``: одна команда ``alpha``."""

    name = "plain"
    commands = {"alpha": "cmd_alpha"}

    def configure(self, ctx: Any) -> None:
        return None

    def process(self, data: Any) -> Any:
        return data

    def cmd_alpha(self, data: dict) -> dict:
        return {"who": "plain"}


class BadOptionsPlugin(ProcessModulePlugin):
    """``command_options(name) -> {"handler": 1}`` — ключа ``handler`` нет среди опций регистрации."""

    name = "bad_options"
    commands = {"alpha": "cmd_alpha"}

    def configure(self, ctx: Any) -> None:
        return None

    def process(self, data: Any) -> Any:
        return data

    def command_options(self, name: str) -> dict:
        return {"handler": 1}

    def cmd_alpha(self, data: dict) -> dict:
        return {"who": "bad_options"}


class ExecutorPlugin(ProcessModulePlugin):
    """Просит исполнитель ``io`` с ключом ``device_id`` для обеих команд; ``alpha`` уже занята другим плагином."""

    name = "executor_owner"
    commands = {"alpha": "cmd_alpha", "beta": "cmd_beta"}

    def configure(self, ctx: Any) -> None:
        return None

    def process(self, data: Any) -> Any:
        return data

    def command_options(self, name: str) -> dict:
        return {"executor": "io", "key_from": "device_id"}

    def cmd_alpha(self, data: dict) -> dict:
        return {"who": "executor_owner"}

    def cmd_beta(self, data: dict) -> dict:
        return {"who": "executor_owner"}


def test_a26_plugin_without_command_options_registers_with_two_positional_args(stand: Stand) -> None:
    """А26: плагин без ``command_options`` — ``register_command(имя, метод)``: два позиционных, без именованных."""
    plugin = PlainPlugin()
    stand.configure(plugin)

    calls = stand.cm.calls_for("alpha")
    assert len(calls) == 1, calls
    args, kwargs = calls[0]
    assert len(args) == 2, args
    assert args[0] == "alpha"
    assert args[1] == plugin.cmd_alpha
    assert kwargs == {}


def test_a26_plugin_without_command_options_command_is_alive_and_silent(stand: Stand) -> None:
    """А26 (пара к предыдущему): команда зарегистрирована, исполняется, ERROR в логе нет («как до правки»)."""
    stand.configure(PlainPlugin())

    assert stand.cm.get_command_info("alpha") is not None
    assert stand.cm.handle_command({"command": "alpha", "data": {}}) == {"who": "plain"}
    assert stand.lines.of("ERROR") == []


def test_a26_bad_option_key_command_registered_without_option_one_error(stand: Stand) -> None:
    """А26: ``command_options -> {"handler": 1}`` — команда зарегистрирована без опции, ровно одна строка ERROR."""
    plugin = BadOptionsPlugin()
    stand.configure(plugin)

    info = stand.cm.get_command_info("alpha")
    assert info is not None, "команда должна быть зарегистрирована и при плохой опции"
    metadata = info.get("metadata") or {}
    assert "executor" not in metadata and "handler" not in metadata, metadata
    assert stand.cm.handle_command({"command": "alpha", "data": {}}) == {"who": "bad_options"}
    for args, kwargs in stand.cm.calls_for("alpha"):
        assert "handler" not in kwargs, kwargs
    assert len(stand.lines.of("ERROR")) == 1, stand.lines.records


def test_a27_name_taken_by_other_plugin_no_repeat_registration_one_error(stand: Stand) -> None:
    """А27: исполнитель для имени, уже занятого другим плагином, — повтора регистрации нет, одна строка ERROR."""
    first = PlainPlugin()
    stand.configure(first)
    assert len(stand.cm.calls_for("alpha")) == 1
    assert stand.lines.of("ERROR") == []

    second = ExecutorPlugin()
    stand.configure(second)

    assert len(stand.cm.calls_for("alpha")) == 1, f"повтор регистрации alpha: {stand.cm.calls_for('alpha')}"
    assert stand.cm.handle_command({"command": "alpha", "data": {}}) == {"who": "plain"}, "alpha перехвачена"
    assert len(stand.lines.of("ERROR")) == 1, stand.lines.records
    assert stand.lines.containing(NOT_ACCEPTED) == [], stand.lines.containing(NOT_ACCEPTED)


def test_a27_pair_other_name_of_same_plugin_gets_the_executor(stand: Stand) -> None:
    """А27 (пара, достижимость): свободное имя ``beta`` того же плагина получает исполнителя — хук вообще работает."""
    stand.configure(PlainPlugin())
    stand.configure(ExecutorPlugin())

    info = stand.cm.get_command_info("beta")
    assert info is not None
    metadata = info.get("metadata") or {}
    assert metadata.get("executor") == "io", metadata
    assert metadata.get("key_from") == "device_id", metadata
