# -*- coding: utf-8 -*-
"""Task 5.12 — слой сессии (L3): ручка переживает reload, сброс пишет отсутствие.

Живая находка, ради которой задача заведена: ``logger.sink.disable messages_file``
→ ``config.reload`` → канал снова в ``channels_active``. Правка жила рантайм-
множеством, которого пересборка конфига не видела. Здесь она — запись слоя.

Тесты гоняют РЕАЛЬНЫЙ ``LoggerManager`` и реальные обработчики команд: проверка на
фейках доказала бы фейки (см. правило «fake-harness test proves the harness»).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    OVERRIDE_CONFIG_KEY,
    process_observability_layers,
)


class _Cm:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _Svc:
    """Минимальный процесс: живой LoggerManager + config со слоями L1/L2."""

    def __init__(self, logger: LoggerManager, config: Dict[str, Any] | None = None) -> None:
        self.command_manager = _Cm()
        self.name = "seg"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self._config = dict(config or {})
        self.log_calls: List[tuple] = []

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_debug(self, msg, **kw):
        self.log_calls.append(("DEBUG", msg, kw))

    def _log_info(self, msg, **kw):
        self.log_calls.append(("INFO", msg, kw))


@pytest.fixture
def wired(tmp_path):
    """Живой логгер на ДЕФОЛТНОМ наборе каналов + зарегистрированные команды.

    Именно дефолтный: пересборка собирает набор из ``managers_from_log_dir``, и
    кастомные имена, не объявленные ни одним слоем, её не переживают (см.
    ``test_channels_not_declared_by_any_layer_do_not_survive``). Живая находка
    была ровно про ``messages_file`` — берём её имена, а не выдуманные.
    """
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="session_layer",
            log_directory=str(tmp_path),
            enable_batching=False,
        )
    )
    svc = _Svc(logger)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    try:
        yield svc, svc.command_manager.handlers, tmp_path
    finally:
        logger.shutdown()


def _active(svc) -> list:
    from multiprocess_framework.modules.process_module.managers.observability_reload import (
        observability_effective,
    )

    return observability_effective(logger=svc.logger_manager)["logger"]["channels_active"]


class TestHandleSurvivesReload:
    def test_disabled_sink_stays_disabled_after_reload(self, wired) -> None:
        """ГЛАВНАЯ пара задачи: снял приёмник → перечитал конфиг → он всё ещё снят."""
        svc, handlers, tmp_path = wired

        assert "messages_file" in _active(svc)
        res = handlers["logger.sink.disable"]({"sink": "messages_file"})
        assert res["success"] is True
        assert res["session_key"] == "channels.messages_file.enabled"
        assert res["survives_reload"] is True
        assert "messages_file" not in _active(svc)

        reload_res = handlers["config.reload"]({"observability": {}, "path": None})
        assert reload_res["success"] is True
        assert "channels.messages_file.enabled" in reload_res["session_keys"]
        assert "messages_file" not in _active(svc), "приёмник воскрес: пересборка не видит слой сессии"
        # Сосед не задет — снятие адресное, а не «все файловые».
        assert "system_file" in _active(svc)
        # Приёмка 2.8 продолжает отвечать «я это выключил», а не «канал не поднялся».
        assert "messages_file" in sorted(svc.logger_manager._sinks_disabled_by_operator)

    def test_reset_returns_the_sink_to_inherited_state(self, wired) -> None:
        """Пара к предыдущей: сброс ключа → приёмник возвращается сам."""
        svc, handlers, _ = wired
        handlers["logger.sink.disable"]({"sink": "messages_file"})

        res = handlers["config.reload"]({"observability_reset": ["channels.messages_file.enabled"]})
        assert res["success"] is True
        assert res["reset"] == ["channels.messages_file.enabled"]
        assert res["session_keys"] == []
        assert "messages_file" in _active(svc), "сброс не вернул наследование"
        assert svc.logger_manager._sinks_disabled_by_operator == set()

    def test_reset_of_a_key_the_session_does_not_hold_is_loud(self, wired) -> None:
        """Тихий no-op = оператор уверен, что вернул как было."""
        svc, handlers, _ = wired
        res = handlers["config.reload"]({"observability_reset": ["log_level"]})
        assert res["reset_not_held"] == ["log_level"]
        assert "reset" not in res

    def test_inline_section_lands_in_the_session_not_in_l1(self, wired) -> None:
        """Ручка пишет в L3 — иначе следующий файловый reload её сотрёт."""
        svc, handlers, _ = wired
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})

        layers = process_observability_layers(svc)
        assert layers.session == {"log_level": "DEBUG"}
        assert layers.app == {}, "ручка оператора не имеет права переписывать слой system.yaml"

    def test_session_survives_a_file_reload_that_says_otherwise(self, wired, tmp_path) -> None:
        """Файл владеет L1, но не L3: ручка сильнее перечитанного файла."""
        svc, handlers, _ = wired
        cfg = tmp_path / "system.yaml"
        cfg.write_text("observability:\n  log_level: WARNING\n", encoding="utf-8")

        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        res = handlers["config.reload"]({"path": str(cfg)})

        layers = process_observability_layers(svc)
        assert layers.app == {"log_level": "WARNING"}, "файл не заменил L1"
        assert layers.session == {"log_level": "DEBUG"}, "файловый reload стёр слой сессии"
        assert res["applied"]["log_level"] == "DEBUG"


class TestRebuildDropsWhatNoLayerDeclares:
    """Цена разворота, названная явно — чтобы её не открыли потом как баг."""

    def test_channels_not_declared_by_any_layer_do_not_survive(self, tmp_path) -> None:
        """Канал, живущий только в объекте менеджера, пересборку не переживает.

        Это оборотная сторона работающего сброса: сохрани такой канал — и
        «вернуть как было» перестанет возвращать. Единственный способ закрепить
        его — объявить слоем (L1/L2), а не сконструировать менеджер руками.
        """
        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="custom",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={"bespoke": LoggerChannelSchema(type="file", file_path="bespoke.log")},
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["bespoke"])},
            )
        )
        svc = _Svc(logger)
        BuiltinCommands(svc)._register_observability_commands()
        try:
            assert "bespoke" in _active(svc)
            svc.command_manager.handlers["config.reload"]({"observability": {}})
            assert "bespoke" not in _active(svc)
        finally:
            logger.shutdown()


class TestRecipeLayerSurvivesFileReload:
    """boot ≡ reload при наличии L2 — зеркало telemetry-находки C."""

    def test_file_reload_keeps_the_recipe_delta(self, tmp_path) -> None:
        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="l2", log_directory=str(tmp_path), enable_batching=False, modules={})
        )
        svc = _Svc(
            logger,
            config={
                APP_CONFIG_KEY: {"log_level": "INFO"},
                OVERRIDE_CONFIG_KEY: {"log_level": "WARNING"},
            },
        )
        bc = BuiltinCommands(svc)
        bc._register_observability_commands()
        handlers = svc.command_manager.handlers
        try:
            cfg = tmp_path / "system.yaml"
            cfg.write_text("observability:\n  log_level: INFO\n", encoding="utf-8")

            res = handlers["config.reload"]({"path": str(cfg)})
            # Файл несёт только L1; дельта рецепта обязана пережить — иначе
            # настройка конвейера молча исчезает при первой перезагрузке.
            assert res["applied"]["log_level"] == "WARNING"
            assert res["effective"]["logger"]["default_level"] == "WARNING"
        finally:
            logger.shutdown()

    def test_layers_are_seeded_from_process_config(self, tmp_path) -> None:
        """L1/L2 приезжают в proc_dict — без них provenance приписал бы всё L0."""
        logger = LoggerManager(config=LoggerManagerConfig(app_name="l2b", log_directory=str(tmp_path), modules={}))
        svc = _Svc(
            logger,
            config={
                APP_CONFIG_KEY: {"enable_batching": False},
                OVERRIDE_CONFIG_KEY: {"log_level": "ERROR"},
                "observability_config_path": "system.yaml",
            },
        )
        try:
            layers = process_observability_layers(svc)
            assert layers.app == {"enable_batching": False}
            assert layers.recipe == {"log_level": "ERROR"}
            assert layers.app_source == "system.yaml"
            # Стек ОДИН на процесс: иначе ручка оператора терялась бы на каждой команде.
            assert process_observability_layers(svc) is layers
        finally:
            logger.shutdown()


class TestPlanesWithoutDeclarativeChannels:
    def test_stats_sink_toggle_admits_it_will_not_survive(self, tmp_path) -> None:
        """error/stats не выразимы в секции — ответ обязан это сказать, а не молчать."""
        from multiprocess_framework.modules.statistics_module import StatsManager

        logger = LoggerManager(config=LoggerManagerConfig(app_name="planes", log_directory=str(tmp_path), modules={}))
        stats = StatsManager()
        stats.initialize()
        svc = _Svc(logger)
        svc.stats_manager = stats
        bc = BuiltinCommands(svc)
        bc._register_observability_commands()
        try:
            names = list(getattr(stats, "_channel_registry").names())
            if not names:
                pytest.skip("у StatsManager нет каналов в этой конфигурации")
            res = svc.command_manager.handlers["logger.sink.disable"]({"sink": names[0], "manager": "stats"})
            assert res["session_key"] is None
            assert res["survives_reload"] is False
        finally:
            stats.shutdown()
            logger.shutdown()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])


class TestProvenanceInIntrospect:
    """«Почему у меня INFO» — вопрос, на который ответ обязан быть в команде."""

    @staticmethod
    def _svc_with_layers(tmp_path):
        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="prov", log_directory=str(tmp_path), enable_batching=False)
        )
        svc = _Svc(
            logger,
            config={
                APP_CONFIG_KEY: {"enable_batching": False},
                OVERRIDE_CONFIG_KEY: {"log_level": "WARNING"},
                "observability_config_path": "system.yaml",
            },
        )
        bc = BuiltinCommands(svc)
        bc._register_introspect_commands()
        bc._register_observability_commands()
        return svc, logger

    def test_all_four_layers_are_named(self, tmp_path) -> None:
        svc, logger = self._svc_with_layers(tmp_path)
        try:
            svc.command_manager.handlers["logger.sink.disable"]({"sink": "messages_file"})
            res = svc.command_manager.handlers["introspect.observability"]({})
            prov = res["provenance"]

            assert prov["enable_batching"] == {"layer": "app", "source": "system.yaml"}
            assert prov["log_level"]["layer"] == "recipe"
            assert prov["channels.messages_file.enabled"]["layer"] == "session"
            # Ключ, которого не назвал никто — дефолт фреймворка, а не пустота.
            assert prov["retention_days"] == {"layer": "framework", "source": "framework"}
        finally:
            logger.shutdown()

    def test_every_live_channel_is_explained_including_module_ones(self, tmp_path) -> None:
        """«Каждый действующий ключ» — это ВЕСЬ реестр каналов, а не секция `channels`.

        Ревью 5.12 (замечание 4): ``module_*``-каналы рождаются из секции
        ``modules`` и в ``config.channels`` не лежат — на девять живых каналов
        из двенадцати provenance молчал, притом что приёмка требует объяснения
        каждому. Источник истины — живой реестр.
        """
        svc, logger = self._svc_with_layers(tmp_path)
        try:
            res = svc.command_manager.handlers["introspect.observability"]({})
            prov = res["provenance"]
            active = res["effective"]["logger"]["channels_active"]
            module_channels = [n for n in active if n.startswith("module_")]
            assert module_channels, "ожидались module_*-каналы в живом реестре"
            missing = [n for n in active if f"channels.{n}.enabled" not in prov]
            assert not missing, f"без объяснения остались действующие каналы: {missing}"

            live_scopes = list(logger.config.scopes)
            assert live_scopes
            for name in live_scopes:
                assert f"scopes.{name}.min_level" in prov, name
        finally:
            logger.shutdown()

    def test_session_content_is_reported(self, tmp_path) -> None:
        svc, logger = self._svc_with_layers(tmp_path)
        try:
            svc.command_manager.handlers["logger.sink.disable"]({"sink": "messages_file"})
            res = svc.command_manager.handlers["introspect.observability"]({})
            assert res["layers"]["session_keys"] == ["channels.messages_file.enabled"]
            assert res["layers"]["app_source"] == "system.yaml"
        finally:
            logger.shutdown()

    def test_introspect_does_not_mutate(self, tmp_path) -> None:
        """Read-команда: два подряд вызова дают одно и то же и ничего не трогают."""
        svc, logger = self._svc_with_layers(tmp_path)
        try:
            handlers = svc.command_manager.handlers
            before = handlers["introspect.observability"]({})["effective"]
            after = handlers["introspect.observability"]({})["effective"]
            assert before == after
            assert process_observability_layers(svc).session == {}
        finally:
            logger.shutdown()


class TestSwitchClearsTheSession:
    """switch = новый конвейер = новая сессия (иначе лоскутное состояние)."""

    def test_session_clear_drops_everything_and_names_it(self, wired) -> None:
        svc, handlers, _ = wired
        handlers["logger.sink.disable"]({"sink": "messages_file"})
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})

        res = handlers["config.reload"]({"observability_session_clear": True})
        assert res["success"] is True
        assert sorted(res["reset"]) == ["channels.messages_file.enabled", "log_level"]
        assert res["session_keys"] == []
        # И это не «забыли применить»: приёмник вернулся, уровень откатился.
        assert "messages_file" in _active(svc)
        assert res["effective"]["logger"]["default_level"] != "DEBUG"

    def test_clear_on_an_empty_session_is_a_quiet_no_op(self, wired) -> None:
        svc, handlers, _ = wired
        res = handlers["config.reload"]({"observability_session_clear": True})
        assert res["success"] is True
        assert res["session_keys"] == []
        assert "reset" not in res
