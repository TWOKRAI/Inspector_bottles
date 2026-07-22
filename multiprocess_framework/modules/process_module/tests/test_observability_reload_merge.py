# -*- coding: utf-8 -*-
"""Тесты честного config.reload: merge поверх живого + профиль уровня + readback.

Живая находка 2026-07-22 (webcam_sketch): частичный inline-reload
``{"log_level": "DEBUG"}``:
  1) МОЛЧА сбрасывал остальной конфиг логгера на дефолты (терялся ``log_directory``
     — файлы логов уезжали в чужой каталог, пересобирались каналы/скоупы);
  2) НЕ менял фильтрацию: ``default_level`` — лишь fallback для отсутствующих
     скоупов, а все стандартные скоупы всегда присутствуют → смена уровня была
     no-op (класс «сигнал не связан с реальностью»).

Контракт после фикса:
  - применение = deep_merge(живой конфиг менеджера, раскрытая секция);
  - явный ``log_level`` переписывает пороги скоупов профилем (DEBUG → всё DEBUG +
    DEBUG-scope on; WARNING/ERROR → пороги подняты; INFO → штатный профиль);
  - ответ ``config.reload`` несёт ``effective`` — readback фактического состояния.
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observability_reconfigure,
    observability_effective,
)


class _CfgDump:
    """Мини-объект конфига с model_dump() (форма живого manager.config)."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> Dict[str, Any]:
        import copy

        return copy.deepcopy(self._data)


class _FakeManagerWithConfig:
    """Менеджер с живым конфигом: merge обязан стартовать от него, не от дефолтов."""

    def __init__(self, current: Dict[str, Any]) -> None:
        self.config = _CfgDump(current)
        self.calls: List[Dict[str, Any]] = []

    def reconfigure(self, config: Dict[str, Any]) -> bool:
        self.calls.append(config)
        return True


class TestMergeOverCurrent:
    def test_partial_section_preserves_log_directory(self) -> None:
        """Плечо «не разрушает»: log_directory живого конфига переживает reload."""
        logger = _FakeManagerWithConfig(
            {"default_level": "INFO", "log_directory": "D:/logs/seg", "app_name": "inspector"}
        )
        apply_observability_reconfigure({"log_level": "DEBUG"}, logger=logger)
        applied = logger.calls[-1]
        assert applied["log_directory"] == "D:/logs/seg", "merge потерял log_directory (сброс на дефолты)"
        assert applied["default_level"] == "DEBUG"

    def test_no_config_manager_still_works(self) -> None:
        """Менеджер без .config (фейки/деградация) → применяется секция как есть."""

        class _Bare:
            def __init__(self) -> None:
                self.calls: List[Dict[str, Any]] = []

            def reconfigure(self, config: Dict[str, Any]) -> bool:
                self.calls.append(config)
                return True

        logger = _Bare()
        apply_observability_reconfigure({"log_level": "WARNING"}, logger=logger)
        assert logger.calls[-1]["default_level"] == "WARNING"


class TestLevelProfile:
    def test_debug_opens_all_scopes(self) -> None:
        """Плечо ON: log_level=DEBUG → все скоупы DEBUG, DEBUG-scope включён."""
        logger = _FakeManagerWithConfig({"default_level": "INFO"})
        apply_observability_reconfigure({"log_level": "DEBUG"}, logger=logger)
        scopes = logger.calls[-1]["scopes"]
        assert scopes, "профиль уровня не собрал scopes — уровень остаётся мёртвым параметром"
        for name, sc in scopes.items():
            assert sc["min_level"] == "DEBUG", f"скоуп {name} не опущен до DEBUG"
        assert scopes["DEBUG"]["enabled"] is True, "DEBUG-scope не включён при log_level=DEBUG"

    def test_warning_raises_thresholds_keeps_debug_scope_off(self) -> None:
        """Плечо OFF: log_level=WARNING → пороги подняты, DEBUG-scope выключен."""
        logger = _FakeManagerWithConfig({"default_level": "DEBUG"})
        apply_observability_reconfigure({"log_level": "WARNING"}, logger=logger)
        scopes = logger.calls[-1]["scopes"]
        for name in ("SYSTEM", "BUSINESS", "PERFORMANCE"):
            assert scopes[name]["min_level"] == "WARNING", f"скоуп {name} не поднят до WARNING"
        assert scopes["DEBUG"]["enabled"] is False, "DEBUG-scope не должен включаться на WARNING"

    def test_info_restores_tuned_defaults(self) -> None:
        """Возврат на INFO → штатный настроенный профиль (SYSTEM=WARNING и т.д.)."""
        logger = _FakeManagerWithConfig({"default_level": "DEBUG"})
        apply_observability_reconfigure({"log_level": "INFO"}, logger=logger)
        scopes = logger.calls[-1]["scopes"]
        assert scopes["SYSTEM"]["min_level"] == "WARNING"
        assert scopes["BUSINESS"]["min_level"] == "INFO"
        assert scopes["DEBUG"]["enabled"] is False

    def test_section_without_level_does_not_touch_scopes(self) -> None:
        """Секция без log_level (например только stats) — скоупы живого конфига не переписываются профилем."""
        current_scopes = {"SYSTEM": {"enabled": True, "min_level": "ERROR", "channels": [], "modules": []}}
        logger = _FakeManagerWithConfig({"default_level": "INFO", "scopes": current_scopes})
        apply_observability_reconfigure({"stats": {"enabled": False}}, logger=logger)
        applied = logger.calls[-1]
        assert applied["scopes"]["SYSTEM"]["min_level"] == "ERROR", "merge перезаписал живые scopes без запроса"


class TestEffectiveReadback:
    def test_effective_reads_live_logger_state(self) -> None:
        """Readback отражает ЖИВОЙ LoggerManager после reconfigure (не эхо входа)."""
        from multiprocess_framework.modules.logger_module import LoggerManager

        logger = LoggerManager(manager_name="TestLoggerEffective")
        logger.initialize()
        try:
            apply_observability_reconfigure({"log_level": "DEBUG"}, logger=logger)
            eff = observability_effective(logger=logger)
            assert eff["logger"]["default_level"] == "DEBUG"
            assert eff["logger"]["scopes"]["DEBUG"]["enabled"] is True
            assert eff["logger"]["scopes"]["SYSTEM"]["min_level"] == "DEBUG"
            # Плечо реального эффекта: DEBUG-запись теперь проходит фильтр.
            from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope

            assert logger.should_log(LogScope.SYSTEM, LogLevel.DEBUG, "probe") is True
        finally:
            logger.shutdown()

    def test_effective_pair_off(self) -> None:
        """Пара OFF: возврат WARNING → DEBUG-запись снова режется (эффект, не эхо)."""
        from multiprocess_framework.modules.logger_module import LoggerManager
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope

        logger = LoggerManager(manager_name="TestLoggerPairOff")
        logger.initialize()
        try:
            apply_observability_reconfigure({"log_level": "DEBUG"}, logger=logger)
            assert logger.should_log(LogScope.BUSINESS, LogLevel.DEBUG, "probe") is True
            apply_observability_reconfigure({"log_level": "WARNING"}, logger=logger)
            assert logger.should_log(LogScope.BUSINESS, LogLevel.DEBUG, "probe") is False
            assert logger.should_log(LogScope.BUSINESS, LogLevel.INFO, "probe") is False
            assert logger.should_log(LogScope.BUSINESS, LogLevel.WARNING, "probe") is True
        finally:
            logger.shutdown()


class TestHealthReportLogEmission:
    """health.report(level=...) — детерминированный эмиттер лог/error-плоскости.

    Живая находка: errors-плоскость наблюдаемости было НЕЧЕМ проверить —
    health.report шёл только в HealthState→state-дерево, а ``level`` молча
    игнорировался.
    """

    @staticmethod
    def _make_bc():
        from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands

        class _Cm:
            def __init__(self) -> None:
                self.handlers: dict = {}

            def register_command(self, name, handler, metadata=None, tags=None) -> None:
                self.handlers[name] = handler

        class _Svc:
            def __init__(self) -> None:
                self.command_manager = _Cm()
                self.name = "seg"
                self.log_calls: List[tuple] = []

            def get_config(self, key, default=None):
                return default

            def _log_debug(self, msg, **kw):
                self.log_calls.append(("DEBUG", msg, kw))

            def _log_info(self, msg, **kw):
                self.log_calls.append(("INFO", msg, kw))

            def _log_warning(self, msg, **kw):
                self.log_calls.append(("WARNING", msg, kw))

            def _log_error(self, msg, **kw):
                self.log_calls.append(("ERROR", msg, kw))

            def _log_critical(self, msg, **kw):
                self.log_calls.append(("CRITICAL", msg, kw))

        svc = _Svc()
        bc = BuiltinCommands(svc)
        bc._register_health_commands()
        svc.log_calls.clear()  # регистрация сама пишет debug-лог — не входит в проверку
        return svc, svc.command_manager.handlers

    def test_level_emits_through_log_channel(self) -> None:
        svc, handlers = self._make_bc()
        res = handlers["health.report"]({"message": "smoke", "level": "ERROR"})
        assert res["success"] is True
        assert res["log_emitted"] is True
        assert svc.log_calls and svc.log_calls[-1][0] == "ERROR"
        assert "smoke" in svc.log_calls[-1][1]

    def test_without_level_no_log(self) -> None:
        svc, handlers = self._make_bc()
        res = handlers["health.report"]({"message": "smoke"})
        assert res["success"] is True
        assert res["log_emitted"] is False
        # HealthState.report_error сам пишет штатный "[health] ..." WARNING — это
        # не наша эмиссия; проверяем, что ДОПОЛНИТЕЛЬНОЙ записи "[health.report]" нет.
        assert not [c for c in svc.log_calls if "[health.report]" in c[1]]

    def test_unknown_level_is_loud_error(self) -> None:
        svc, handlers = self._make_bc()
        res = handlers["health.report"]({"message": "smoke", "level": "LOUD"})
        assert res["success"] is False
        assert "level" in res["reason"]
