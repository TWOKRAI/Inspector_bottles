# -*- coding: utf-8 -*-
"""Task 5.4, ось приёмников: узор в имени sink'а раскрывается внутри процесса.

По одному свойству на тест:

  * узор гасит N приёмников одной командой и называет все N поимённо;
  * узор, не поймавший ничего, — громкий отказ с каталогом (класс «тихий no-op»,
    закрытый 5.5, не воскресает через узор);
  * точное имя в ветку раскрытия не заходит вовсе — форма ответа прежняя;
  * узор не выходит за свою плоскость (``manager=error`` не трогает логгер);
  * каждое пойманное имя получает СВОЙ ключ сессии L3;
  * узор, поймавший только уже-снятые приёмники, — названный no-op, а не успех.

Последний тест ведёт узор до НАСТОЯЩЕГО ``LoggerManager``: фейк доказывает
обработчик, но не механизм — каталог у него подставной, и «узор ищет не в том
множестве» на фейке был бы невидим.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _Registry:
    def __init__(self, names) -> None:
        self._names = set(names)

    def names(self):
        return set(self._names)


class _Config:
    def __init__(self, channels) -> None:
        self.channels = {name: {} for name in channels}


class _CatalogLogger:
    """Менеджер с каталогом: реестр живых каналов + описания в конфиге."""

    manager_name = "LoggerManager"

    def __init__(self, active=(), configured=()) -> None:
        self._channel_registry = _Registry(active)
        self.config = _Config(configured or active)
        self._sinks_disabled_by_operator: set = set()
        self.calls: list = []

    def set_sink_enabled(self, name: str, enabled: bool) -> bool:
        self.calls.append((name, enabled))
        live = self._channel_registry._names
        if enabled:
            if name in live:
                return False
            live.add(name)
            self._sinks_disabled_by_operator.discard(name)
            return True
        if name not in live:
            return False
        live.discard(name)
        self._sinks_disabled_by_operator.add(name)
        return True

    def routes_using_sink(self, name: str):
        return [f"route_for_{name}"]


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeServices:
    def __init__(self, *, logger=None, error=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = logger
        self.error_manager = error
        self.stats_manager = None
        self.router_manager = None
        self.name = "camera_0"
        self._config: dict = {}

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    return svc, svc.command_manager


class TestPatternExpansion:
    def test_pattern_disables_every_matching_sink_and_names_them_all(self) -> None:
        logger = _CatalogLogger(active=["module_camera", "module_robot", "console", "system_file"])
        _svc, cm = _make(logger=logger)

        res = cm.dispatch("logger.sink.disable", {"sink": "module_*"})

        assert res["success"] is True
        assert res["matched"] == ["module_camera", "module_robot"]
        assert res["changed"] == ["module_camera", "module_robot"]
        assert set(res["results"]) == {"module_camera", "module_robot"}
        assert sorted(name for name, _en in logger.calls) == ["module_camera", "module_robot"]
        assert "console" not in logger._sinks_disabled_by_operator, "узор задел соседа вне выборки"

    def test_pattern_matching_nothing_is_a_loud_refusal_with_the_catalog(self) -> None:
        logger = _CatalogLogger(active=["console", "system_file"])
        _svc, cm = _make(logger=logger)

        res = cm.dispatch("logger.sink.disable", {"sink": "module_*"})

        assert res["success"] is False
        assert res["matched"] == []
        assert res["catalog"] == ["console", "system_file"]
        assert "console" in res["reason"], "отказ не назвал каталог, в котором искали"
        assert logger.calls == [], "пустое раскрытие всё-таки дёрнуло менеджер"

    def test_pattern_that_changes_nothing_is_a_named_noop_not_a_success(self) -> None:
        """Уже снятые приёмники: не успех и не сбой, а названный no-op."""
        logger = _CatalogLogger(active=["console"], configured=["console", "module_camera"])
        _svc, cm = _make(logger=logger)

        res = cm.dispatch("logger.sink.disable", {"sink": "module_*"})

        assert res["matched"] == ["module_camera"]
        assert res["changed"] == []
        assert res["unchanged"] == ["module_camera"]
        assert res["success"] is False
        assert "уже в требуемом состоянии" in res["reason"]

    def test_enable_reaches_sinks_that_left_the_registry(self) -> None:
        """Каталог для ``enable`` — конфиг и отметки оператора, а не живой реестр.

        Снятый приёмник из реестра ушёл; ищи узор только там — возврат группы
        приёмников был бы невыразим ровно после того, как её сняли.
        """
        logger = _CatalogLogger(active=["console"], configured=["console", "module_camera", "module_robot"])
        _svc, cm = _make(logger=logger)

        res = cm.dispatch("logger.sink.enable", {"sink": "module_*"})

        assert res["changed"] == ["module_camera", "module_robot"]


class TestExactNameUnchanged:
    def test_exact_name_answers_the_old_shape(self) -> None:
        logger = _CatalogLogger(active=["module_camera", "module_robot"])
        _svc, cm = _make(logger=logger)

        res = cm.dispatch("logger.sink.disable", {"sink": "module_camera"})

        assert "matched" not in res and "results" not in res, f"точное имя приобрело батч-форму: {res}"
        assert res["sink"] == "module_camera" and res["enabled"] is False
        assert logger.calls == [("module_camera", False)]


class TestPlaneIsolation:
    def test_pattern_stays_inside_the_addressed_plane(self) -> None:
        logger = _CatalogLogger(active=["module_camera", "module_robot"])
        error = _CatalogLogger(active=["errors_file"])
        _svc, cm = _make(logger=logger, error=error)

        res = cm.dispatch("logger.sink.disable", {"sink": "*", "manager": "error"})

        assert res["matched"] == ["errors_file"]
        assert logger.calls == [], "узор плоскости ошибок дотянулся до логгера"
        assert res["manager"] == "error"


class TestSessionKeys:
    def test_every_matched_sink_gets_its_own_key_in_the_real_session_layer(self) -> None:
        """Общий ключ на узор означал бы, что возврат одного воскрешает остальных.

        Проверяется НАБЛЮДАЕМЫЙ след — что реально легло в слой L3, — а не факт
        вызова ``_record_sink_in_session``. Первая редакция теста шпионила именно
        за именем метода и пережила бы подмену формулы ключа: инъекция «общий ключ
        на узор» её не убивала, потому что шпион и был вместо формулы.
        """
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            process_observability_layers,
        )

        logger = _CatalogLogger(active=["module_camera", "module_robot"])
        svc, cm = _make(logger=logger)

        res = cm.dispatch("logger.sink.disable", {"sink": "module_*"})

        keys = set(process_observability_layers(svc).session_keys())
        assert keys == {"channels.module_camera.enabled", "channels.module_robot.enabled"}, (
            f"в слой сессии легло не по ключу на приёмник: {sorted(keys)}"
        )
        assert {name: section["session_key"] for name, section in res["results"].items()} == {
            "module_camera": "channels.module_camera.enabled",
            "module_robot": "channels.module_robot.enabled",
        }

    def test_resetting_one_key_leaves_the_neighbours_alone(self) -> None:
        """Сброс одного пойманного имени не воскрешает остальных."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            process_observability_layers,
        )

        logger = _CatalogLogger(active=["module_camera", "module_robot"])
        svc, cm = _make(logger=logger)
        cm.dispatch("logger.sink.disable", {"sink": "module_*"})

        layers = process_observability_layers(svc)
        layers.session_reset("channels.module_camera.enabled", origin="test")

        assert set(layers.session_keys()) == {"channels.module_robot.enabled"}


class TestOnARealLoggerManager:
    def test_pattern_reaches_real_channels_and_stops_the_files(self, tmp_path) -> None:
        """Узор на НАСТОЯЩЕМ менеджере: каталог берётся из живого реестра и конфига.

        Фейк выше проверяет обработчик; здесь проверяется, что узор ищет в том же
        множестве, которое менеджер реально держит, — то есть что каталог назван
        правильными атрибутами, а не правдоподобными.
        """
        from multiprocess_framework.modules.logger_module.configs import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="glob_round_trip",
                log_directory=str(tmp_path),
                enable_batching=False,
                channels={
                    "module_camera": LoggerChannelSchema(
                        type="file", enabled=True, file_path="module_camera.log", rotate=False
                    ),
                    "module_robot": LoggerChannelSchema(
                        type="file", enabled=True, file_path="module_robot.log", rotate=False
                    ),
                    "keep_me": LoggerChannelSchema(type="file", enabled=True, file_path="keep_me.log", rotate=False),
                },
                scopes={"BUSINESS": LoggerScopeSchema(channels=["module_camera", "module_robot", "keep_me"])},
            )
        )
        logger.initialize()
        try:
            svc = _FakeServices(logger=logger)
            bc = BuiltinCommands(svc)
            bc._register_observability_commands()

            res = svc.command_manager.dispatch("logger.sink.disable", {"sink": "module_*"})

            assert res["success"] is True
            assert res["matched"] == ["module_camera", "module_robot"]
            live = set(logger._channel_registry.names())
            assert "keep_me" in live, "узор снял приёмник за пределами выборки"
            assert not (live & {"module_camera", "module_robot"}), "узор не снял то, что назвал"
        finally:
            logger.shutdown()
