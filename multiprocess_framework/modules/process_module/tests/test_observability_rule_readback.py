# -*- coding: utf-8 -*-
"""Ф2.6, шаг 6 — правила видны с пульта: что написано и что из этого вышло.

План: plans/observability-unified-routing.md, задача 2.6 (резидуал 2.2 №4).

Зачем. Механизм правил построен 2026-08-03, и до этой правки НИ ОДНА ручка наружу
его не показывала: ``effective_level``/``effective_channels`` существовали только в
коде. Живой прогон приходилось проверять размерами файлов на глаз — ровно тем
способом, которым 288 нулевых файлов не замечали три месяца.

Две секции отвечают на два разных вопроса, и обе нужны:

* ``effective.logger.loggers`` — **что написано** (аналог ``configuredLevel``);
* ``resolve`` — **что из этого вышло** для конкретного имени, с указанием
  победившего префикса (аналог ``effectiveLevel`` + происхождение).

Расхождение между ними и есть «правило написано, но не действует» — то самое, что
сегодня не видно ничем.

Тест водит НАСТОЯЩИЙ ``LoggerManager`` через настоящую команду процесса, а не
подставные объекты: фейковая обвязка доказала бы обвязку. Проверка идёт по ответу
команды — это и есть контракт, который увидит оператор.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_effective,
)

_RULES = {
    "": {"level": "WARNING", "channels": ["main"]},
    "multiprocess_framework.modules": {"level": "DEBUG"},
    "multiprocess_framework.modules.dispatch_module": {"channels_extra": ["own"]},
}


@pytest.fixture()
def logger(tmp_path) -> Any:
    manager = LoggerManager(
        config=LoggerManagerConfig(
            app_name="rb26",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "main": LoggerChannelSchema(type="file", enabled=True, file_path="main.log", rotate=False),
                "own": LoggerChannelSchema(type="file", enabled=True, file_path="own.log", rotate=False),
            },
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["main"])},
            loggers=_RULES,
        )
    )
    yield manager
    manager.shutdown()


class TestWhatIsWritten:
    """``effective.logger.loggers`` — таблица правил как она задана."""

    def test_rules_are_exposed(self, logger: Any) -> None:
        table = observability_effective(logger=logger)["logger"]["loggers"]

        assert set(table) == set(_RULES)
        assert table["multiprocess_framework.modules"]["level"] == "DEBUG"
        assert table["multiprocess_framework.modules.dispatch_module"]["channels_extra"] == ["own"]

    def test_silence_and_declared_emptiness_stay_distinguishable(self, tmp_path) -> None:
        """``None`` (ключа нет) и ``[]`` (объявленная пустота) — разные ответы.

        Схлопни их в readback — и оператор, увидев ``[]``, полез бы искать
        отсутствующее правило вместо того, чтобы найти своё.
        """
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="rb26b",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                loggers={"тихо": {"level": "INFO"}, "пусто": {"channels": []}},
            )
        )
        try:
            table = observability_effective(logger=manager)["logger"]["loggers"]
        finally:
            manager.shutdown()

        assert table["тихо"]["channels"] is None
        assert table["пусто"]["channels"] == []

    def test_empty_table_is_an_answer_not_a_gap(self, tmp_path) -> None:
        """Правил нет → пустой словарь, а НЕ отсутствие ключа."""
        manager = LoggerManager(
            config=LoggerManagerConfig(app_name="rb26c", log_directory=str(tmp_path), enable_batching=False)
        )
        try:
            section = observability_effective(logger=manager)["logger"]
        finally:
            manager.shutdown()

        assert section["loggers"] == {}


class TestWhatCameOut:
    """``resolve_rule`` — что действует для имени и какой префикс победил."""

    def test_origin_of_each_axis(self, logger: Any) -> None:
        got = logger.resolve_rule("multiprocess_framework.modules.dispatch_module.core.dispatcher")

        assert got["level"] == "DEBUG"
        assert got["level_from"] == "multiprocess_framework.modules"
        assert got["channels"] == ["main"]
        assert got["channels_from"] == ""
        assert got["channels_extra"] == ["own"]

    def test_answers_for_a_source_that_never_wrote(self, logger: Any) -> None:
        got = logger.resolve_rule("Plugins.ещё.не.существует")

        assert got["level"] == "WARNING"
        assert got["level_from"] == ""

    def test_readback_matches_what_the_gate_uses(self, logger: Any) -> None:
        """Несущее свойство: разбор не расходится с действующим порогом.

        Сравнивается с ``effective_level`` — публичной ручкой, которую спрашивает
        гейт. Readback, разошедшийся с гейтом, хуже отсутствующего: по нему
        принимают решения.
        """
        name = "multiprocess_framework.modules.command_module"

        assert logger.resolve_rule(name)["level"] == logger.effective_level(name)


class _Services:
    """Минимальный носитель менеджеров: команда читает их с сервисов процесса.

    Настоящий ``LoggerManager`` внутри — подставной доказал бы, что команда позвала
    метод с нужным именем, а нужно доказать, что оператор получит РАЗБОР. Ровно тот
    класс, из-за которого правило проекта требует хотя бы один тест на реальной
    обвязке рядом с фейковой.
    """

    def __init__(self, logger: Any) -> None:
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self.command_manager = None
        self.name = "проба"

    def get_config(self, key, default=None):
        return default

    def _log_info(self, *a, **k) -> None: ...

    def _log_debug(self, *a, **k) -> None: ...


def _introspect(logger: Any, **args) -> dict:
    from multiprocess_framework.modules.process_module.commands.builtin_commands import (
        BuiltinCommands,
    )

    return BuiltinCommands(_Services(logger))._cmd_introspect_observability(args or None)


class TestCommandSurface:
    """Проводка аргумента через саму команду — без неё её не сторожит ничто."""

    def test_resolve_section_appears_when_asked(self, logger: Any) -> None:
        name = "multiprocess_framework.modules.dispatch_module.core.dispatcher"
        answer = _introspect(logger, resolve=name)

        assert answer["resolve"][name]["level_from"] == "multiprocess_framework.modules"

    def test_several_names_at_once(self, logger: Any) -> None:
        """Оператор чаще сравнивает два соседних источника, чем смотрит один."""
        answer = _introspect(logger, resolve=["multiprocess_framework.modules", "чужой.источник"])

        assert answer["resolve"]["multiprocess_framework.modules"]["level"] == "DEBUG"
        assert answer["resolve"]["чужой.источник"]["level"] == "WARNING"

    def test_section_is_absent_without_the_argument(self, logger: Any) -> None:
        """Пара: панель дёргает команду постоянно, разбор на каждом опросе — мусор."""
        answer = _introspect(logger)

        assert "resolve" not in answer
        assert answer["effective"]["logger"]["loggers"]  # таблица правил при этом есть


class TestOutputIsSafeToSend:
    def test_everything_is_plain(self, logger: Any) -> None:
        """Ответ уходит на пульт через IPC — только dict/list/str/None."""
        payload = {
            "loggers": observability_effective(logger=logger)["logger"]["loggers"],
            "resolve": logger.resolve_rule("multiprocess_framework.modules"),
        }

        def _check(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    assert isinstance(key, str), key
                    _check(item)
            elif isinstance(value, list):
                for item in value:
                    _check(item)
            else:
                assert value is None or isinstance(value, str), repr(value)

        _check(payload)


class TestUnknownScopesAreVisibleFromThePult:
    """Ф2.4 — группы, в которые ПИСАЛИ, но которых в конфиге нет.

    Соседняя секция ``scopes`` показывает объявленные, то есть ровно то
    множество, в котором незаведённой группы нет по определению. Без этой
    ручки живой прогон 2.4 проверялся бы тем же способом, каким три месяца не
    замечали 288 пустых файлов, — глазами по каталогу.
    """

    def test_written_but_undeclared_group_shows_up(self, logger: Any) -> None:
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel

        logger.log("КОНВЕЙЕР", LogLevel.ERROR, "деталь", "мод")
        section = observability_effective(logger=logger)["logger"]

        assert section["unknown_scopes"] == ["КОНВЕЙЕР"]
        assert "КОНВЕЙЕР" not in section["scopes"], "объявленной она при этом не стала"

    def test_key_is_present_even_when_empty(self, logger: Any) -> None:
        """«Таких нет» — это ответ; отсутствие ключа отправило бы искать поломку readback."""
        assert observability_effective(logger=logger)["logger"]["unknown_scopes"] == []
