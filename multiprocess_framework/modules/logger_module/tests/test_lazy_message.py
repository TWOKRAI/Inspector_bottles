# -*- coding: utf-8 -*-
"""Ф1.4-1.5 — цена сообщения платится только за принятую запись.

Заявленные свойства и как каждое ломается отдельно:

  1.4a  ``Callable`` не вызывается при закрытом гейте;
  1.4b  ``Callable`` вызывается РОВНО ОДИН раз, сколько бы каналов ни было;
  1.4c  ``%``-формат применяется один раз и тоже после гейта;
  1.5   ``StdLoggerFacade`` не склеивает строку до гейта — то есть ``__str__``
        аргументов не выполняется на отклонённой записи.

Все счётчики — на САМОМ аргументе (``__str__``, вызов lambda), а не на шпионе
за именем метода: шпион за ``apply_format`` сторожил бы имя функции, а не
свойство «дорогое не вычисляется». Это прямой урок ревью фазы Ф0 про тест,
следивший за ``Path.rglob``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.adapters import std_facade
from multiprocess_framework.modules.logger_module.adapters.std_facade import StdLoggerFacade
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class _CountingArg:
    """Аргумент, который считает, сколько раз его превращали в строку."""

    def __init__(self, value: str = "значение") -> None:
        self.value = value
        self.str_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return self.value

    __repr__ = __str__


def _manager(tmp_path: Path, **overrides: Any) -> LoggerManager:
    config: Dict[str, Any] = {
        "app_name": "lazy",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {
            "a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")},
            "b": {"type": "file", "enabled": True, "file_path": str(tmp_path / "b.log")},
        },
        "scopes": {
            "BUSINESS": {"enabled": True, "min_level": "INFO", "channels": ["a", "b"]},
            "SYSTEM": {"enabled": True, "min_level": "WARNING", "channels": ["a"]},
            "DEBUG": {"enabled": False, "min_level": "DEBUG", "channels": ["a"]},
        },
    }
    config.update(overrides)
    mgr = LoggerManager(manager_name="LazyProbe", config=config)
    mgr.initialize()
    return mgr


@pytest.fixture
def logger(tmp_path: Path):
    mgr = _manager(tmp_path)
    yield mgr
    mgr.shutdown()


class TestCallableMessage:
    def test_not_called_when_gate_closed(self, logger: LoggerManager) -> None:
        """1.4a — выключенный DEBUG-скоуп не платит за сборку сообщения."""
        calls: List[int] = []

        logger.debug(lambda: calls.append(1) or "дорогая строка", module="probe")

        assert calls == [], "сообщение вычислено, хотя запись отклонена гейтом"
        assert logger.get_stats()["messages_skipped"] >= 1

    def test_called_once_regardless_of_channel_count(self, logger: LoggerManager) -> None:
        """1.4b — два канала, но одно вычисление.

        Проверяется именно на скоупе с ДВУМЯ приёмниками: реализация, собирающая
        сообщение внутри цикла по каналам, здесь и умирает.
        """
        calls: List[int] = []

        logger.info(lambda: calls.append(1) or "однажды", module="probe")

        assert len(calls) == 1
        assert logger._route(LogScope.BUSINESS, LogLevel.INFO, "probe") == ["a", "b"], (
            "предусловие теста: приёмников должно быть больше одного"
        )

    def test_result_reaches_the_channel(self, logger: LoggerManager, tmp_path: Path) -> None:
        logger.info(lambda: "текст из callable", module="probe")
        logger.flush()
        assert "текст из callable" in (tmp_path / "a.log").read_text(encoding="utf-8")


class TestPercentArgs:
    def test_not_formatted_when_gate_closed(self, logger: LoggerManager) -> None:
        """1.4c — аргументы не приводятся к строке на отклонённой записи."""
        arg = _CountingArg()

        logger.debug("значение: %s", "probe", arg)

        assert arg.str_calls == 0, "аргумент отформатирован, хотя запись отклонена"

    def test_formatted_once_for_two_channels(self, logger: LoggerManager) -> None:
        arg = _CountingArg()

        logger.info("значение: %s", "probe", arg)

        assert arg.str_calls == 1

    def test_formatted_text_on_disk(self, logger: LoggerManager, tmp_path: Path) -> None:
        logger.info("процесс '%s' код %d", "probe", "pult", 42)
        logger.flush()
        assert "процесс 'pult' код 42" in (tmp_path / "a.log").read_text(encoding="utf-8")

    def test_broken_format_keeps_message_and_args(self, logger: LoggerManager, tmp_path: Path) -> None:
        """Кривой шаблон не имеет права съесть запись — правило пережило переезд."""
        logger.info("без плейсхолдеров", "probe", "лишний")
        logger.flush()
        text = (tmp_path / "a.log").read_text(encoding="utf-8")
        assert "без плейсхолдеров" in text and "лишний" in text

    def test_module_stays_positional(self, logger: LoggerManager, tmp_path: Path) -> None:
        """Четвёртый позиционный аргумент — по-прежнему ``module``, а не формат.

        Совместимость: во фреймворке сотни вызовов вида
        ``log(scope, level, msg, "имя_модуля")``. Если бы ``*args`` встали
        раньше, имя модуля молча уехало бы в аргументы формата.
        """
        logger.log(LogScope.BUSINESS, LogLevel.INFO, "позиционный модуль", "probe")
        logger.flush()
        assert "probe" in (tmp_path / "a.log").read_text(encoding="utf-8")


class TestStdFacadeGatesBeforeFormatting:
    """1.5 — фасад отдаёт шаблон менеджеру, а не готовую строку."""

    def test_rejected_record_costs_no_formatting(self, logger: LoggerManager, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(std_facade, "get_logger", lambda: logger)
        arg = _CountingArg()

        # debug → LogScope.DEBUG, выключен в конфиге фикстуры.
        assert StdLoggerFacade("probe").debug("дорогое: %s", arg) is True

        assert arg.str_calls == 0, "фасад склеил строку до гейта — Ф1.5 не работает"

    def test_accepted_record_is_formatted_exactly_once(
        self, logger: LoggerManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(std_facade, "get_logger", lambda: logger)
        arg = _CountingArg("готово")

        StdLoggerFacade("probe").info("итог: %s", arg)
        logger.flush()

        assert arg.str_calls == 1
        assert "итог: готово" in (tmp_path / "a.log").read_text(encoding="utf-8")

    def test_module_still_reaches_manager(self, logger: LoggerManager, monkeypatch: pytest.MonkeyPatch) -> None:
        """Имя модуля не должно потеряться при переходе на позиционную передачу."""
        seen: List[Any] = []
        monkeypatch.setattr(std_facade, "get_logger", lambda: logger)
        original = logger.info

        def _spy(message: Any, module: str = "main", *args: Any, **extra: Any) -> None:
            seen.append((message, module, args))
            return original(message, module, *args, **extra)

        monkeypatch.setattr(logger, "info", _spy)

        StdLoggerFacade("trace_probe").info("x=%s", 1)

        assert seen == [("x=%s", "trace_probe", (1,))], (
            "фасад обязан отдать шаблон и аргументы РАЗДЕЛЬНО, с именем модуля вторым"
        )

    def test_fallback_without_manager_still_formats(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Без менеджера фасад форматирует сам — иначе stdlib получил бы шаблон."""
        monkeypatch.setattr(std_facade, "get_logger", lambda: None)
        with caplog.at_level("WARNING"):
            assert StdLoggerFacade("probe").warning("код %d", 7) is False
        assert "код 7" in caplog.text
