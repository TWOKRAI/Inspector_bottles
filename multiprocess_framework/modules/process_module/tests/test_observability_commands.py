# -*- coding: utf-8 -*-
"""Тесты Ф1 Task 1.4: IPC config.reload / logger.sink.enable|disable.

Реализация ADR-CRM-006 п.3 поверх готовых reconfigure/sink-реестра. Проверяем:
  - команды регистрируются в CommandManager с описанием (для контактной книжки 1.9);
  - config.reload с inline-override меняет уровень логгера через reconfigure (тот же
    путь, что hot-reload watcher — apply_observability_layers);
  - logger.sink.enable|disable делегируют в LoggerManager.set_sink_enabled.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeLogger:
    """Логгер: фиксирует reconfigure(dict) и set_sink_enabled(name, bool)."""

    def __init__(self) -> None:
        self.reconfigured: list = []
        self.sink_calls: list = []
        self.sinks = {"errors_file"}  # «зарегистрированные» sink'и

    def reconfigure(self, config: dict) -> bool:
        self.reconfigured.append(config)
        return True

    def set_sink_enabled(self, name: str, enabled: bool) -> bool:
        self.sink_calls.append((name, enabled))
        if enabled:
            self.sinks.add(name)
            return True
        if name in self.sinks:
            self.sinks.discard(name)
            return True
        return False


class _FakeTapLogger:
    """Логгер с tap-API (add_tap / remove_tap)."""

    manager_name = "LoggerManager"

    def __init__(self) -> None:
        self.taps: dict = {}

    def add_tap(self, channel, *, min_level="ERROR", name=None) -> str:
        tap = name or getattr(channel, "name", "tap")
        self.taps[tap] = (channel, min_level)
        return tap

    def remove_tap(self, name) -> bool:
        return self.taps.pop(name, None) is not None


class _FakeRouter:
    def send_async(self, message, priority="normal") -> None: ...


class _FakeServices:
    def __init__(self, *, logger=None, config=None, router=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = router
        self.name = "preprocessor"
        self._config = config or {}

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    return svc, svc.command_manager


class TestRegistration:
    def test_registers_commands_with_descriptions(self) -> None:
        _svc, cm = _make(logger=_FakeLogger())
        for key in (
            "config.reload",
            "logger.sink.enable",
            "logger.sink.disable",
            "logger.sink.tail",
            "log.tail.subscribe",
            "log.tail.unsubscribe",
        ):
            assert key in cm.handlers
            assert cm.metadata[key].get("description"), f"{key}: нет description (нужно для 1.9)"

    def test_skips_without_command_manager(self) -> None:
        svc = _FakeServices(logger=_FakeLogger())
        svc.command_manager = None
        BuiltinCommands(svc)._register_observability_commands()  # не должно падать


class TestConfigReload:
    def test_inline_override_changes_log_level(self) -> None:
        logger = _FakeLogger()
        _svc, cm = _make(logger=logger)
        res = cm.dispatch("config.reload", {"observability": {"log_level": "DEBUG"}})
        assert res["success"] is True
        assert res["applied"]["log_level"] == "DEBUG"
        # reconfigure получил развёрнутый logger-конфиг с новым уровнем
        assert logger.reconfigured, "reconfigure не вызван"
        assert logger.reconfigured[-1].get("default_level") == "DEBUG"

    def test_no_section_no_path_returns_error(self) -> None:
        _svc, cm = _make(logger=_FakeLogger(), config={})
        res = cm.dispatch("config.reload", {})
        assert res["success"] is False
        assert "observability" in res["reason"]


class TestLoggerSink:
    def test_disable_then_enable_sink(self) -> None:
        logger = _FakeLogger()
        _svc, cm = _make(logger=logger)

        off = cm.dispatch("logger.sink.disable", {"sink": "errors_file"})
        assert off["success"] is True and off["enabled"] is False
        assert "errors_file" not in logger.sinks

        on = cm.dispatch("logger.sink.enable", {"sink": "errors_file"})
        assert on["success"] is True and on["enabled"] is True
        assert "errors_file" in logger.sinks

    def test_missing_sink_name_is_error(self) -> None:
        _svc, cm = _make(logger=_FakeLogger())
        res = cm.dispatch("logger.sink.enable", {})
        assert res["success"] is False

    def test_failed_enable_does_not_report_the_sink_as_enabled(self) -> None:
        """Живая находка 2026-07-28: поле ``enabled`` эхом возвращало ЗАПРОШЕННОЕ.

        Вживую это выглядело как ``{"success": false, "enabled": true}``: команда
        честно сообщала об отказе, а соседнее поле рядом убеждало оператора, что
        канал вернулся. Достигнутое состояние обязано совпадать с реальностью.
        """

        class _RefusingLogger(_FakeLogger):
            def set_sink_enabled(self, name: str, enabled: bool) -> bool:
                self.sink_calls.append((name, enabled))
                return False  # включить не смогли

        _svc, cm = _make(logger=_RefusingLogger())
        res = cm.dispatch("logger.sink.enable", {"sink": "module_trace"})
        assert res["success"] is False
        assert res["enabled"] is False, "отказ включения не имеет права рапортовать enabled=true"

    def test_sink_round_trip_on_a_REAL_logger(self, tmp_path) -> None:
        """Тот же круг, но на НАСТОЯЩЕМ LoggerManager, а не на фейке.

        Фейк выше доказывает обработчик, но не механизм: его ``set_sink_enabled``
        возвращает True всегда, поэтому дефект «канал не включается обратно» на
        нём был НЕВИДИМ и прожил до живого прогона. Этот тест проводит команду до
        реального менеджера — и до файла.

        **Переклассифицирован в Ф2.6.** Круг проверялся на per-module канале,
        потому что односторонней была именно эта ветка: описание жило в секции
        ``modules``, а команда искала его в ``channels``. Механизм снят, ветка
        одна — свойство «команда доходит до реального файла» осталось несущим и
        проверяется на обычном приёмнике.
        """
        from multiprocess_framework.modules.logger_module.configs import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="real_round_trip",
                log_directory=str(tmp_path),
                enable_batching=False,
                channels={
                    "trace_file": LoggerChannelSchema(type="file", enabled=True, file_path="trace.log", rotate=False)
                },
                scopes={"BUSINESS": LoggerScopeSchema(enabled=True, min_level="INFO", channels=["trace_file"])},
            )
        )
        try:
            _svc, cm = _make(logger=logger)
            off = cm.dispatch("logger.sink.disable", {"sink": "trace_file"})
            assert off["success"] is True and off["enabled"] is False

            on = cm.dispatch("logger.sink.enable", {"sink": "trace_file"})
            assert on["success"] is True and on["enabled"] is True

            logger.info("канал вернулся", module="trace")
            logger.flush()
        finally:
            logger.shutdown()

        assert "канал вернулся" in (tmp_path / "trace.log").read_text(encoding="utf-8")


class TestLoggerSinkTail:
    """2.9: чтение хвоста приёмника, хранящего записи у себя.

    Только на РЕАЛЬНОМ менеджере: на фейке проверялась бы связка «команда →
    метод с таким именем», а не то, что записи действительно достаются из
    живого процесса — ровно тот класс промаха, который выше стоил фазы
    живого прогона.
    """

    @staticmethod
    def _logger(tmp_path):
        from multiprocess_framework.modules.logger_module.configs import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        return LoggerManager(
            config=LoggerManagerConfig(
                app_name="tail29",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={"mem": LoggerChannelSchema(type="memory", capacity=20)},
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["mem"])},
            )
        )

    def test_command_returns_the_last_records_of_a_memory_sink(self, tmp_path) -> None:
        logger = self._logger(tmp_path)
        try:
            _svc, cm = _make(logger=logger)
            for i in range(5):
                logger.info(f"m{i}", module="m")

            res = cm.dispatch("logger.sink.tail", {"sink": "mem", "limit": 3})
            assert res["success"] is True
            assert [r["message"] for r in res["records"]] == ["m2", "m3", "m4"]
            assert res["manager"] == "logger"
        finally:
            logger.shutdown()

    def test_unknown_manager_is_refused_by_whitelist(self, tmp_path) -> None:
        logger = self._logger(tmp_path)
        try:
            _svc, cm = _make(logger=logger)
            res = cm.dispatch("logger.sink.tail", {"sink": "mem", "manager": "router"})
            assert res["success"] is False
            assert "router" in res["reason"]
        finally:
            logger.shutdown()

    def test_missing_sink_name_is_error(self, tmp_path) -> None:
        logger = self._logger(tmp_path)
        try:
            _svc, cm = _make(logger=logger)
            assert cm.dispatch("logger.sink.tail", {})["success"] is False
        finally:
            logger.shutdown()


class TestSinkToggleNamesWhatItTouches:
    """Приёмка 2.8: ответ обязан назвать затронутые маршруты.

    Пункт был объявлен закрытым, а реализован не был — поймано ревью 2.9.
    Снятие приёмника вслепую обнаруживается по отсутствию логов, то есть позже
    всего и не тем, кто снимал.
    """

    def test_logger_answers_with_scopes(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.configs import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="routes",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={"a": LoggerChannelSchema(type="file", file_path="a.log")},
                scopes={
                    "SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["a"]),
                    "BUSINESS": LoggerScopeSchema(min_level="INFO", channels=["другой"]),
                },
            )
        )
        try:
            _svc, cm = _make(logger=logger)
            res = cm.dispatch("logger.sink.disable", {"sink": "a"})
            assert res["success"] is True
            assert res["routes"] == ["SYSTEM"], "BUSINESS этот приёмник не адресует"
        finally:
            logger.shutdown()

    def test_the_error_plane_answers_with_severity_levels(self, tmp_path) -> None:
        """У плоскости ошибок маршрут не скоупный — перечислять скоупы значило бы врать."""
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager

        errors = ErrorManager(
            config={
                "app_name": "routes_err",
                "error_file_path": str(tmp_path / "errors.log"),
                "critical_file_path": str(tmp_path / "critical.log"),
                "enable_batching": False,
            }
        )
        try:
            _svc, cm = _make(logger=_FakeLogger())
            _svc.error_manager = errors
            res = cm.dispatch("logger.sink.disable", {"sink": "errors_file", "manager": "error"})
            assert res["success"] is True
            assert res["routes"] == ["severity:ERROR", "severity:WARNING"]
        finally:
            errors.shutdown()


class TestTailCrossesTheProcessBoundary:
    def test_an_unpicklable_extra_does_not_kill_the_whole_tail(self, tmp_path) -> None:
        """Находка ревью 2.9: одна запись с объектом в `extra` роняла ВЕСЬ ответ.

        `logger.sink.tail` едет обратно через очередь (pickle), а публичный API
        логирования класть объекты в `extra` не запрещает. Наблюдалось так:
        `TypeError: cannot pickle '_thread.lock' object` — оператор видел отказ
        транспорта далеко от причины и терял хвост целиком, а не одно поле.
        """
        import pickle
        import threading

        from multiprocess_framework.modules.logger_module.configs import (
            LoggerChannelSchema,
            LoggerManagerConfig,
            LoggerScopeSchema,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        logger = LoggerManager(
            config=LoggerManagerConfig(
                app_name="boundary",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={"ring": LoggerChannelSchema(type="memory", capacity=10)},
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["ring"])},
            )
        )
        try:
            _svc, cm = _make(logger=logger)
            logger.info("обычная", module="m")
            logger.info("с локом", module="m", lock=threading.Lock())

            res = cm.dispatch("logger.sink.tail", {"sink": "ring"})
            assert res["success"] is True
            assert [r["message"] for r in res["records"]] == ["обычная", "с локом"]
            pickle.dumps(res)  # не должно бросить
            assert "lock" in str(res["records"][1]["extra"])
        finally:
            logger.shutdown()


class TestLogTail:
    def test_subscribe_installs_tap(self) -> None:
        logger = _FakeTapLogger()
        svc, cm = _make(logger=logger, router=_FakeRouter())
        res = cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl", "level": "ERROR"})
        assert res["success"] is True
        assert res["level"] == "ERROR"
        assert res["tap"] == "log_tail::backend_ctl"
        assert "log_tail::backend_ctl" in logger.taps

    def test_subscribe_requires_subscriber(self) -> None:
        _svc, cm = _make(logger=_FakeTapLogger(), router=_FakeRouter())
        assert cm.dispatch("log.tail.subscribe", {})["success"] is False

    def test_subscribe_refuses_unknown_level(self) -> None:
        """Ф3.1: третий путь входа имени уровня — аргумент команды.

        Прежде опечатка давала порог «пропускать всё» при ``success=true``:
        подписчик просил ошибки, получал каждую запись и не мог этого узнать.
        Образец отказа уже стоял рядом, у ``health.report``, — расхождение двух
        команд одной поверхности и было «дефектом на одном пути из трёх».
        """
        logger = _FakeTapLogger()
        _svc, cm = _make(logger=logger, router=_FakeRouter())
        res = cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl", "level": "ERORR"})
        assert res["success"] is False
        assert "ERORR" in res["reason"]
        assert logger.taps == {}, "отвергнутая подписка не должна ставить tap"

    def test_subscribe_accepts_foreign_spelling_of_a_level(self) -> None:
        """``WARN`` — каноничное имя OTel, а не опечатка; ответ несёт канон."""
        logger = _FakeTapLogger()
        _svc, cm = _make(logger=logger, router=_FakeRouter())
        res = cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl", "level": "warn"})
        assert res["success"] is True
        assert res["level"] == "WARNING"

    def test_subscribe_requires_router(self) -> None:
        _svc, cm = _make(logger=_FakeTapLogger(), router=None)
        res = cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl"})
        assert res["success"] is False
        assert "router" in res["reason"]

    def test_unsubscribe_removes_tap(self) -> None:
        logger = _FakeTapLogger()
        _svc, cm = _make(logger=logger, router=_FakeRouter())
        cm.dispatch("log.tail.subscribe", {"subscriber": "backend_ctl"})
        res = cm.dispatch("log.tail.unsubscribe", {"subscriber": "backend_ctl"})
        assert res["success"] is True
        assert logger.taps == {}
