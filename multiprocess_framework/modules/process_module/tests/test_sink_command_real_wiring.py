# -*- coding: utf-8 -*-
"""Резидуал P4 — sink-адресация на НАСТОЯЩЕЙ проводке.

Соседний ``test_sink_command_addressing.py`` целиком построен на фейках:
``_FakeServices`` объявляет атрибуты ``logger_manager`` / ``error_manager`` /
``stats_manager`` сам, и переименование любого из них в ``ProcessModule``
оставило бы все десять тестов зелёными при мёртвой команде в проде. Это тот же
класс, что «тест-шпион за именем API» из ревью фазы Ф0.

Здесь проводка настоящая на всём пути:

  * носитель команд — реальный ``ProcessModule`` (именно ему в проде передаётся
    ``BuiltinCommands(self)``), а не дубль с удобными атрибутами;
  * менеджеры — реальные ``LoggerManager`` и ``ErrorManager`` с файловыми
    каналами;
  * диспетчер — реальный ``CommandManager``;
  * проверка — по РЕЕСТРУ КАНАЛОВ живого менеджера и по файлу на диске, а не по
    списку вызовов шпиона.

Тестов немного и они дорогие; исчерпывающая матрица значений ``manager``
остаётся на дешёвом фейковом харнессе. Задача этого файла — доказать, что
харнесс подключён к тому же, к чему подключён прод.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.command_module import CommandManager
from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    _SINK_ADDRESSABLE_MANAGERS,
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule


def _send(command_manager: CommandManager, command: str, data: dict) -> dict:
    """Отправить команду ТЕМ ЖЕ входом, которым её отправляет IPC.

    Не ``dispatch(command, data)``: такого метода у настоящего
    ``CommandManager`` нет вовсе — его придумал фейковый харнесс соседнего
    файла. Это и есть цена фейков: десять зелёных тестов ходили через вход,
    которого в проде не существует. Реальный вход — ``handle_command`` со
    словарём-сообщением, ровно как приходит из роутера.
    """
    return command_manager.handle_command({"command": command, "data": data})


@pytest.fixture
def wired(tmp_path: Path):
    """Реальный ProcessModule с реальными logger/error и реальным CommandManager."""
    process = ProcessModule("sink_wiring_probe")

    logger = LoggerManager(
        manager_name="logger_sink_wiring",
        config={
            "app_name": "sink_wiring",
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "modules": {},
            "channels": {
                "system_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": str(tmp_path / "system.log"),
                    "format": "%(message)s",
                },
            },
            "scopes": {"SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["system_file"]}},
        },
    )
    logger.initialize()

    error = ErrorManager(
        config=ErrorManagerConfig(
            app_name="sink_wiring_errors",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=str(tmp_path / "warnings.log"),
        ),
    )
    error.initialize()

    command_manager = CommandManager(manager_name="cmd_sink_wiring")
    command_manager.initialize()

    # Присваиваем ЧЕРЕЗ ту же карту, по которой команда ищет цель. Прямые
    # `process.error_manager = ...` тест бы прошёл даже после переименования
    # атрибута в проде: Python создаст атрибут с любым именем, и фикстура
    # молча воскресила бы то, что сломали (проверено слом-инъекцией B11 —
    # два теста из трёх остались зелёными при переименовании).
    #
    # Само переименование ловит ``TestAttributeContract`` на СВЕЖЕМ
    # ``ProcessModule``, и это единственная честная точка: имя должно
    # существовать у прод-класса, а не у харнесса.
    setattr(process, _SINK_ADDRESSABLE_MANAGERS["logger"], logger)
    setattr(process, _SINK_ADDRESSABLE_MANAGERS["error"], error)
    process.command_manager = command_manager

    builtin = BuiltinCommands(process)
    builtin._register_observability_commands()

    yield process, logger, error, command_manager

    command_manager.shutdown()
    error.shutdown()
    logger.shutdown()


class TestAttributeContract:
    """Имена, по которым команда ищет менеджеров, обязаны быть у прод-класса."""

    def test_process_module_exposes_every_addressable_attribute(self) -> None:
        """ЕДИНСТВЕННЫЙ страж переименования — и потому на СВЕЖЕМ объекте.

        Тесты ниже переименование не ловят и не могут: они сами кладут
        менеджеров в процесс, а Python создаст атрибут с любым именем. Ровно
        это показала слом-инъекция B11 (``self.error_manager`` →
        ``self.error_manager_renamed``): из трёх «настоящих» тестов умер один —
        этот. Отсюда разделение обязанностей: имя сторожится здесь, поведение —
        ниже, на живых реестрах.
        """
        process = ProcessModule("attr_probe")
        missing = [attr for attr in _SINK_ADDRESSABLE_MANAGERS.values() if not hasattr(process, attr)]
        assert missing == [], (
            f"команда sink-control адресует атрибуты, которых у ProcessModule нет: {missing}. "
            "Именно это фейковый харнесс поймать не может — он объявляет их сам"
        )


class TestRealSinkToggle:
    def test_disable_removes_the_channel_from_the_live_registry(self, wired: Any) -> None:
        _process, logger, _error, cm = wired
        assert logger._channel_registry.get("system_file") is not None

        res = _send(cm, "logger.sink.disable", {"sink": "system_file"})

        assert res["success"] is True and res["manager"] == "logger"
        assert logger._channel_registry.get("system_file") is None, (
            "команда отчиталась об успехе, а канал в живом реестре остался"
        )

    def test_disable_actually_stops_the_bytes(self, wired: Any, tmp_path: Path) -> None:
        """Проверка по диску: после команды строк в файле не прибавляется."""
        _process, logger, _error, cm = wired
        logger.warning("до снятия", module="wiring")
        logger.flush()
        before = (tmp_path / "system.log").read_text(encoding="utf-8")

        _send(cm, "logger.sink.disable", {"sink": "system_file"})
        logger.warning("после снятия", module="wiring")
        logger.flush()

        after = (tmp_path / "system.log").read_text(encoding="utf-8")
        assert "до снятия" in before
        assert after == before, "запись продолжает идти в снятый приёмник"

    def test_enable_brings_the_channel_back(self, wired: Any, tmp_path: Path) -> None:
        _process, logger, _error, cm = wired
        _send(cm, "logger.sink.disable", {"sink": "system_file"})

        res = _send(cm, "logger.sink.enable", {"sink": "system_file"})

        assert res["success"] is True
        assert logger._channel_registry.get("system_file") is not None
        logger.warning("после возврата", module="wiring")
        logger.flush()
        assert "после возврата" in (tmp_path / "system.log").read_text(encoding="utf-8")

    def test_manager_error_hits_the_error_manager_only(self, wired: Any) -> None:
        """Адресация разводит РАЗНЫЕ живые реестры, а не разные списки вызовов."""
        _process, logger, error, cm = wired

        res = _send(cm, "logger.sink.disable", {"sink": "errors_file", "manager": "error"})

        assert res["success"] is True and res["manager"] == "error"
        assert error._channel_registry.get("errors_file") is None
        assert logger._channel_registry.get("system_file") is not None, "manager='error' задел приёмник логгера"

    def test_severity_route_follows_the_command(self, wired: Any) -> None:
        """P2 через КОМАНДУ, а не через прямой вызов метода.

        Ровно этот путь ходит оператор: ``logger.sink.disable`` с
        ``manager="error"``. Маршрут уровня обязан перестроиться на живой канал.
        """
        _process, _logger, error, cm = wired
        assert error.get_stats()["level_routes"]["CRITICAL"] == "critical_file"

        _send(cm, "logger.sink.disable", {"sink": "critical_file", "manager": "error"})

        assert error.get_stats()["level_routes"]["CRITICAL"] == "errors_file"

    def test_unknown_manager_touches_nothing_real(self, wired: Any) -> None:
        _process, logger, error, cm = wired
        before_logger = sorted(logger._channel_registry.names())
        before_error = sorted(error._channel_registry.names())

        res = _send(cm, "logger.sink.disable", {"sink": "system_file", "manager": "router"})

        assert res["success"] is False and res.get("reason")
        assert sorted(logger._channel_registry.names()) == before_logger
        assert sorted(error._channel_registry.names()) == before_error
