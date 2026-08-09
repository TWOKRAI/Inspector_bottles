# -*- coding: utf-8 -*-
"""Ф5.1, остаток: ``introspect.observability`` показывает НОВЫЙ резолв (после Ф2).

Команда заведена досрочно в Ф0.3, когда адресация была плоской. Остаток задачи —
сверить её с моделью, построенной Ф2.2/2.5/2.6/2.7, и ровно по двум пунктам:

  1. секция ``effective`` показывает резолв по иерархии — таблицу правил, ярлыки
     и каталог объявленных источников, а разбор имени (``resolve``) СОГЛАСЕН с
     горячим путём. Readback, расходящийся с гейтом, хуже отсутствующего: по нему
     принимают решения;
  2. команда не мутирует состояние при изменённой иерархии — включая то, что
     разбор гипотетического имени не записывает его в «источники, которые писали».

Проверяется на НАСТОЯЩЕМ ``LoggerManager``: у фейка иерархии нет вовсе, и оба
пункта на нём были бы утверждениями ни о чём.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeServices:
    def __init__(self, logger) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self.name = "camera_0"

    def get_config(self, key, default=None):
        return default

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


@pytest.fixture()
def real_logger(tmp_path):
    """LoggerManager с живой иерархией: правило поддерева, корень и ярлык-группа."""
    from multiprocess_framework.modules.logger_module.configs import (
        LoggerChannelSchema,
        LoggerManagerConfig,
        LoggerRuleSchema,
        LoggerScopeSchema,
    )
    from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="hierarchy_readback",
            log_directory=str(tmp_path),
            enable_batching=False,
            channels={
                "trace_file": LoggerChannelSchema(type="file", enabled=True, file_path="trace.log", rotate=False)
            },
            scopes={"BUSINESS": LoggerScopeSchema(channels=["trace_file"])},
            loggers={
                "": LoggerRuleSchema(level="WARNING"),
                "vision.capture": LoggerRuleSchema(level="DEBUG", channels=["trace_file"]),
            },
            logger_groups={"служебное": ["vision.capture.hikvision"]},
        )
    )
    logger.initialize()
    yield logger
    logger.shutdown()


def _dispatch(logger, data=None):
    svc = _FakeServices(logger)
    BuiltinCommands(svc)._register_introspect_commands()
    return svc, svc.command_manager.dispatch("introspect.observability", data or {})


class TestEffectiveShowsTheNewResolve:
    def test_rules_groups_and_declared_sources_are_in_the_readback(self, real_logger) -> None:
        _svc, res = _dispatch(real_logger)
        section = res["effective"]["logger"]

        assert section["loggers"][""]["level"] == "WARNING", "корневое правило не видно пульту"
        assert section["loggers"]["vision.capture"]["level"] == "DEBUG"
        assert section["groups"]["служебное"] == ["vision.capture.hikvision"]
        assert isinstance(section["declared_sources"], dict), "каталога объявленных источников нет в ответе"

    def test_resolve_agrees_with_the_hot_path(self, real_logger) -> None:
        """Разбор из пульта и порог, по которому реально судит гейт, — одно и то же.

        Лист ``vision.capture.hikvision`` собственного правила не имеет: DEBUG он
        обязан унаследовать по самому длинному совпавшему префиксу, а не от корня.
        """
        _svc, res = _dispatch(real_logger, {"resolve": ["vision.capture.hikvision", "router_module"]})

        leaf = res["resolve"]["vision.capture.hikvision"]
        assert leaf["level"] == real_logger.effective_level("vision.capture.hikvision")
        assert leaf["level"] == "DEBUG"
        assert leaf["level_from"] == "vision.capture", "победил не самый длинный префикс"

        stranger = res["resolve"]["router_module"]
        assert stranger["level"] == "WARNING"
        assert stranger["level_from"] == "", "правило корня обязано быть отличимо от «никто не сказал»"


class TestReadCommandDoesNotMutate:
    def test_two_calls_agree(self, real_logger) -> None:
        _svc, first = _dispatch(real_logger, {"resolve": "vision.capture.hikvision"})
        _svc2, second = _dispatch(real_logger, {"resolve": "vision.capture.hikvision"})

        assert first["effective"] == second["effective"]
        assert first["resolve"] == second["resolve"]

    def test_resolving_a_hypothetical_name_does_not_make_it_a_seen_source(self, real_logger) -> None:
        """Разбор гипотезы не имеет права пополнять «кто писал».

        Иначе read-команда меняла бы ровно то, о чём отчитывается: спросил про имя
        — и оно появилось в каталоге писавших, хотя не писало ничего.
        """
        _svc, before = _dispatch(real_logger)
        _svc2, _ = _dispatch(real_logger, {"resolve": "vision.capture.never_written"})
        _svc3, after = _dispatch(real_logger)

        assert "vision.capture.never_written" not in after["effective"]["logger"]["sources"]
        assert before["effective"]["logger"]["sources"] == after["effective"]["logger"]["sources"]
