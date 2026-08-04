# -*- coding: utf-8 -*-
"""Ф2.6, шаг 1 — имя источника объявлено ОДИН раз и штампуется из объявления.

План: plans/observability-unified-routing.md, задача 2.6, решение Р-2.6-В.

Зачем это отдельный файл. До Ф2.6 имя источника было напечатано дважды: в штампе
(двадцать один литерал ``module="..."`` внутри трёх модулей) и ещё раз — в правиле
маршрутизации. Расхождение между копиями и есть «правило написано неправильно», а
обнаружить его было нечем: непойманное правило ничего не теряет, значит счётчику
потерь расти не с чего — это тишина, и у тишины счётчика нет по построению. Ровно
этот механизм оставил на диске 288 нулевых файлов и не сказал об этом три месяца.

Проверяется НАБЛЮДАЕМЫЙ эффект — имя на записи, реально дошедшей до приёмника, а не
наличие атрибута ``LOG_SOURCE``. Спай на имя атрибута сторожил бы имя, а не свойство:
он остался бы зелёным ровно в том случае, ради которого файл написан — когда штамп и
объявление разошлись.

Ожидаемое значение записано ЛИТЕРАЛОМ. Сравнение штампа с константой, выведенной из
того же кода, согласилось бы с любым ответом, включая переименование обоих разом;
поэтому константа проверяется отдельным тестом, тоже против литерала.
"""

from __future__ import annotations

from typing import Any, Dict, Set

import pytest

from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.command_module.interfaces import LOG_SOURCE as COMMAND_SOURCE
from multiprocess_framework.modules.dispatch_module.core.dispatcher import Dispatcher
from multiprocess_framework.modules.dispatch_module.interfaces import LOG_SOURCE as DISPATCH_SOURCE
from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.statistics_module.channels.log_stats_channel import (
    LogStatsChannel,
)
from multiprocess_framework.modules.statistics_module.interfaces import LOG_SOURCE as STATS_SOURCE

#: Скоупы открыты все и на DEBUG: файл проверяет ШТАМП, а не гейт. Порог, закрывший
#: бы запись, дал бы зелёный тест при разошедшемся штампе — пустое множество имён
#: не противоречит ни одному утверждению вида «нужного имени нет».
_ALL_SCOPES = ("SYSTEM", "BUSINESS", "PERFORMANCE", "DEBUG")


@pytest.fixture()
def logger(tmp_path) -> Any:
    """Настоящий LoggerManager с кольцом в памяти вместо файла.

    Кольцо (приёмник ``memory``, задача 2.9), а не подставной объект-запоминалка:
    подставной доказал бы, что менеджер позвал метод с нужным аргументом, а нужно
    доказать, что имя дошло до приёмника через весь маршрут — гейт, резолв, запись.
    """
    manager = LoggerManager(
        config=LoggerManagerConfig(
            app_name="src26",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"ring": LoggerChannelSchema(type="memory", enabled=True, capacity=200)},
            scopes={
                name: LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["ring"]) for name in _ALL_SCOPES
            },
        )
    )
    yield manager
    manager.shutdown()


def _sources(manager: Any) -> Set[str]:
    """Имена источников на записях, ДОШЕДШИХ до кольца."""
    return {record.get("module") for record in manager.read_sink_tail("ring")["records"]}


def _snapshot() -> Dict[str, Any]:
    return {"metrics": [{"name": "fps", "value": 1}], "total_count": 1, "timestamp": 0.0}


class TestStampComesFromTheDeclaration:
    """Штамп на реальной записи равен объявленному имени."""

    def test_command_manager_stamps_command_manager(self, logger: Any) -> None:
        manager = CommandManager(manager_name="cm", managers={"logger": logger})
        manager.register_command("проба", lambda **_: None)

        assert "command_manager" in _sources(logger)

    def test_dispatcher_stamps_dispatcher(self, logger: Any) -> None:
        dispatcher = Dispatcher(manager_name="dp", managers={"logger": logger})
        dispatcher.register_handler("проба", lambda **_: None)

        assert "dispatcher" in _sources(logger)

    def test_stats_channel_stamps_stats(self, logger: Any) -> None:
        LogStatsChannel(logger_manager=logger, name="log_stats").write(_snapshot())

        assert "stats" in _sources(logger)


class TestConstantsHoldTheAddressedNames:
    """Значения объявлений — отдельно от штампа, тоже против литерала.

    Правило маршрутизации адресует ровно эти строки. Если бы файл сравнивал штамп
    только с константой, переименование константы прошло бы зелёным — и правило,
    написанное под старое имя, перестало бы ловить молча.
    """

    def test_declared_values(self) -> None:
        assert COMMAND_SOURCE == "command_manager"
        assert DISPATCH_SOURCE == "dispatcher"
        assert STATS_SOURCE == "stats"

    def test_declarations_do_not_collide(self) -> None:
        """Три имени различны — иначе два модуля делили бы одно правило молча."""
        assert len({COMMAND_SOURCE, DISPATCH_SOURCE, STATS_SOURCE}) == 3
