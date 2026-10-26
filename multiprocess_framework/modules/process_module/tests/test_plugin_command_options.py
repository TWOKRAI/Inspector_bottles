"""Тесты автора SPI.d1: хук ``ProcessModulePlugin.command_options`` в ``_auto_register_commands``.

Purpose:
    Гарантия для плагинов без хука (полоса Ф): ``register_command(имя, метод)`` — ровно два позиционных, без
    именованных (литерал вызова). Белый список опций, отказ занятого имени без повтора, запасной путь при непринятом
    исполнителе (INFO + регистрация с одним ``metadata``), запись опций двойниками ``testing`` / ``plugin_test_bench``.
    Один тест — с настоящим ``CommandManager``.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.testing import MockCommandManager


class _Log:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def of(self, level: str) -> list[str]:
        return [text for lvl, text in self.records if lvl == level]


class _Ctx:
    """Контекст плагина: менеджер команд и ``log_*`` в одну запись."""

    def __init__(self, command_manager: Any, log: _Log) -> None:
        self.command_manager = command_manager
        for level in ("debug", "info", "warning", "error"):
            setattr(self, f"log_{level}", lambda msg, *_a, _l=level.upper(), **_k: log.records.append((_l, str(msg))))


class _RecordingCM:
    """Двойник с сигнатурой ``CommandManager.register_command``: пишет ``(args, kwargs)``, отвечает ``result``."""

    def __init__(self, result: Any = True, taken: set[str] | None = None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.result = result
        self.taken = set(taken or ())

    def register_command(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.result if kwargs.get("executor") else True

    def get_command_info(self, name: str) -> dict | None:
        return {"name": name} if name in self.taken else None


class _Plugin(ProcessModulePlugin):
    name = "opts"
    commands = {"alpha": "cmd_alpha"}
    options: Any = None  # None — хук не переопределён (умолчание базы)

    def configure(self, ctx: Any) -> None:
        pass

    def process(self, data: Any) -> Any:
        return data

    def cmd_alpha(self, data: dict) -> dict:
        return {"ok": True}


def _plugin(options: Any = None) -> _Plugin:
    if options is None:
        return _Plugin()

    class WithOptions(_Plugin):
        def command_options(self, command_name: str) -> Any:
            return options

    return WithOptions()


def _register(plugin: _Plugin, cm: Any) -> _Log:
    log = _Log()
    plugin._auto_register_commands(_Ctx(cm, log))
    return log


def test_without_hook_exactly_two_positional_args_literal() -> None:
    """Гарантия полосы Ф: плагин без ``command_options`` — ``register_command("alpha", метод)``, kwargs пусты."""
    plugin = _plugin()
    cm = _RecordingCM()
    log = _register(plugin, cm)
    assert cm.calls == [(("alpha", plugin.cmd_alpha), {})]
    assert log.records == []
    assert ProcessModulePlugin.command_options(plugin, "alpha") == {}


def test_empty_or_none_options_register_as_without_hook() -> None:
    for empty in ({}, None):

        class P(_Plugin):
            def command_options(self, command_name: str, _e: Any = empty) -> Any:
                return _e

        plugin = P()
        cm = _RecordingCM()
        _register(plugin, cm)
        assert cm.calls == [(("alpha", plugin.cmd_alpha), {})]


def test_options_passed_as_keywords() -> None:
    options = {"executor": "io", "key_from": "device_id", "targets": "t", "metadata": {"description": "d"}}
    plugin = _plugin(options)
    cm = _RecordingCM()
    log = _register(plugin, cm)
    assert cm.calls == [(("alpha", plugin.cmd_alpha), options)]
    assert log.records == []


def test_unknown_keys_dropped_with_one_error() -> None:
    plugin = _plugin({"handler": 1, "executor": "io"})
    cm = _RecordingCM()
    log = _register(plugin, cm)
    assert cm.calls == [(("alpha", plugin.cmd_alpha), {"executor": "io"})]
    assert len(log.of("ERROR")) == 1 and "handler" in log.of("ERROR")[0]


def test_taken_name_no_registration_one_error() -> None:
    plugin = _plugin({"executor": "io"})
    cm = _RecordingCM(taken={"alpha"})
    log = _register(plugin, cm)
    assert cm.calls == []
    assert len(log.of("ERROR")) == 1 and "alpha" in log.of("ERROR")[0]


def test_executor_refused_fallback_with_metadata_one_info() -> None:
    meta = {"description": "d"}
    plugin = _plugin({"executor": "io", "key_from": "device_id", "metadata": meta})
    cm = _RecordingCM(result=False)
    log = _register(plugin, cm)
    assert cm.calls == [
        (("alpha", plugin.cmd_alpha), {"executor": "io", "key_from": "device_id", "metadata": meta}),
        (("alpha", plugin.cmd_alpha), {"metadata": meta}),
    ]
    assert log.of("INFO") == ["Plugin 'opts': команда alpha: исполнитель не принят — регистрация без исполнителя"]
    assert log.of("ERROR") == []


def test_stub_returning_none_is_not_a_refusal() -> None:
    """``testing.MockCommandManager`` возвращает None: это не отказ (``is False``), повтора нет; опции записаны."""
    plugin = _plugin({"executor": "io", "key_from": "device_id"})
    cm = MockCommandManager()
    log = _register(plugin, cm)
    assert cm.commands == {"alpha": plugin.cmd_alpha}
    assert cm.command_options == {"alpha": {"executor": "io", "key_from": "device_id"}}
    assert log.records == []


def test_real_command_manager_unknown_executor_falls_back_sync() -> None:
    """Настоящий ``CommandManager`` без реестра исполнителей: отказ -> запасной путь, команда жива, metadata цела."""
    cm = CommandManager("d1_options")
    assert cm.initialize() is True
    try:
        plugin = _plugin({"executor": "io", "key_from": "device_id", "metadata": {"description": "d"}})
        log = _register(plugin, cm)
        info = cm.get_command_info("alpha")
        assert info is not None
        metadata = info.get("metadata") or {}
        assert metadata.get("description") == "d" and "executor" not in metadata, metadata
        assert cm.handle_command({"command": "alpha", "data": {}}) == {"ok": True}
        assert len(log.of("INFO")) == 1 and log.of("ERROR") == []

        plain = _plugin()
        plain.commands = {"beta": "cmd_alpha"}
        _register(plain, cm)
        assert cm.get_command_info("beta") is not None
    finally:
        cm.shutdown()
