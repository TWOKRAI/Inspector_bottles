# -*- coding: utf-8 -*-
"""Тесты честного config.reload: merge поверх живого + профиль уровня + readback.

Живая находка 2026-07-22 (webcam_sketch): частичный inline-reload
``{"log_level": "DEBUG"}``:
  1) МОЛЧА сбрасывал остальной конфиг логгера на дефолты (терялся ``log_directory``
     — файлы логов уезжали в чужой каталог, пересобирались каналы/скоупы);
  2) НЕ менял фильтрацию: ``default_level`` — лишь fallback для отсутствующих
     скоупов, а все стандартные скоупы всегда присутствуют → смена уровня была
     no-op (класс «сигнал не связан с реальностью»).

Контракт после Task 5.12 — **пересборка из слоёв**, а не дельта поверх живого:
  - применение = merge(база машинного контекста, раскрытые слои L1→L2→L3);
  - каталог логов приходит из ``managers_from_log_dir(машинный log_dir)`` и
    переопределяется ТОЛЬКО явным ``log_directory`` слоя — находка 2026-07-22
    передоказана здесь парой на новой семантике;
  - явный ``log_level`` переписывает пороги скоупов профилем (DEBUG → всё DEBUG +
    DEBUG-scope on; WARNING/ERROR → пороги подняты; INFO → штатный профиль);
  - ответ ``config.reload`` несёт ``effective`` — readback фактического состояния.

Почему разворот: дельта не умеет выразить «ключ удалён из слоя → вернись к
нижнему». Обратная сторона — живое состояние, которого нет ни в одном слое,
пересборку НЕ переживает; это не потеря, а условие работы сброса (см.
``test_live_scope_not_backed_by_any_layer_does_not_survive``).
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observability_layers,
    observability_effective,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    ObservabilityLayers,
)


def _apply_section(section, **kwargs):
    """Применить голую секцию ``observability`` — одноэтажный стек «сказал только L1».

    Раньше это была функция фреймворка ``apply_observability_reconfigure``. Продакшн-
    вызывающих у неё не было НИ ОДНОГО (ревью Ф5, корзина 2 п.10): поверхность
    выглядела входом в применение, обслуживала только эти тесты — и питала докстринги,
    утверждавшие, будто через неё идёт ``config.reload``. Помощник переехал туда, где
    живут его вызывающие; продакшн-путь (``apply_observability_layers`` со стеком
    процесса) тесты зовут напрямую.
    """
    # `origin` здесь с дефолтом — и это не послабление дисциплины аудита: стек
    # создаётся ПРЯМО В ВЫЗОВЕ и умирает вместе с ним, записывать некуда и некому
    # читать. Дефолт описывает ровно этот факт, а не прячет незнание источника.
    kwargs.setdefault("origin", "reconfigure")
    return apply_observability_layers(
        ObservabilityLayers(app=dict(section) if isinstance(section, dict) else {}),
        **kwargs,
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


class TestRebuildFromLayers:
    """Находка 2026-07-22, передоказанная на семантике пересборки."""

    def test_partial_section_keeps_logs_in_the_machine_directory(self, tmp_path) -> None:
        """Плечо «не разрушает»: частичная секция не уводит логи в чужой каталог.

        Держится это уже не merge'ем поверх живого, а базой: каталог приходит из
        машинного контекста (``log_dir``), а применяемая секция про него молчит.
        """
        logger = _FakeManagerWithConfig({"default_level": "INFO", "log_directory": str(tmp_path)})
        _apply_section({"log_level": "DEBUG"}, logger=logger, log_dir=str(tmp_path))
        applied = logger.calls[-1]
        assert applied["log_directory"] == str(tmp_path), "пересборка увела логи из машинного каталога"
        assert applied["default_level"] == "DEBUG"
        # Файлы плоскости ошибок — та же гарантия, второй менеджер.
        error = _FakeManagerWithConfig({})
        _apply_section({"log_level": "DEBUG"}, error=error, log_dir=str(tmp_path))
        assert str(tmp_path) in error.calls[-1]["error_file_path"]

    def test_explicit_log_directory_in_a_layer_wins_over_machine_context(self, tmp_path) -> None:
        """Плечо «слой всё ещё главнее»: явный ключ переопределяет базу."""
        custom = str(tmp_path / "chosen")
        logger = _FakeManagerWithConfig({})
        _apply_section(
            {"log_level": "DEBUG", "log_directory": custom},
            logger=logger,
            log_dir=str(tmp_path),
        )
        assert logger.calls[-1]["log_directory"] == custom

    def test_key_dropped_from_the_layer_falls_back_to_the_base(self, tmp_path) -> None:
        """Собственно причина разворота: удаление ключа возвращает нижнее значение.

        Дельта поверх живого этого не умеет — удаления в дельте не существует,
        и прежний ``log_directory`` жил бы вечно.
        """
        custom = str(tmp_path / "chosen")
        logger = _FakeManagerWithConfig({})
        _apply_section({"log_directory": custom}, logger=logger, log_dir=str(tmp_path))
        assert logger.calls[-1]["log_directory"] == custom

        _apply_section({}, logger=logger, log_dir=str(tmp_path))
        assert logger.calls[-1]["log_directory"] == str(tmp_path), "ключ удалён из слоя, а значение осталось"

    def test_no_config_manager_still_works(self) -> None:
        """Менеджер без .config (фейки/деградация) → применяется секция как есть."""

        class _Bare:
            def __init__(self) -> None:
                self.calls: List[Dict[str, Any]] = []

            def reconfigure(self, config: Dict[str, Any]) -> bool:
                self.calls.append(config)
                return True

        logger = _Bare()
        _apply_section({"log_level": "WARNING"}, logger=logger)
        assert logger.calls[-1]["default_level"] == "WARNING"


class TestLevelProfile:
    def test_debug_opens_all_scopes(self) -> None:
        """Плечо ON: log_level=DEBUG → все скоупы DEBUG, DEBUG-scope включён."""
        logger = _FakeManagerWithConfig({"default_level": "INFO"})
        _apply_section({"log_level": "DEBUG"}, logger=logger)
        scopes = logger.calls[-1]["scopes"]
        assert scopes, "профиль уровня не собрал scopes — уровень остаётся мёртвым параметром"
        for name, sc in scopes.items():
            assert sc["min_level"] == "DEBUG", f"скоуп {name} не опущен до DEBUG"
        assert scopes["DEBUG"]["enabled"] is True, "DEBUG-scope не включён при log_level=DEBUG"

    def test_warning_raises_thresholds_keeps_debug_scope_off(self) -> None:
        """Плечо OFF: log_level=WARNING → пороги подняты, DEBUG-scope выключен."""
        logger = _FakeManagerWithConfig({"default_level": "DEBUG"})
        _apply_section({"log_level": "WARNING"}, logger=logger)
        scopes = logger.calls[-1]["scopes"]
        for name in ("SYSTEM", "BUSINESS", "PERFORMANCE"):
            assert scopes[name]["min_level"] == "WARNING", f"скоуп {name} не поднят до WARNING"
        assert scopes["DEBUG"]["enabled"] is False, "DEBUG-scope не должен включаться на WARNING"

    def test_info_restores_tuned_defaults(self) -> None:
        """Возврат на INFO → штатный настроенный профиль (SYSTEM=WARNING и т.д.)."""
        logger = _FakeManagerWithConfig({"default_level": "DEBUG"})
        _apply_section({"log_level": "INFO"}, logger=logger)
        scopes = logger.calls[-1]["scopes"]
        assert scopes["SYSTEM"]["min_level"] == "WARNING"
        assert scopes["BUSINESS"]["min_level"] == "INFO"
        assert scopes["DEBUG"]["enabled"] is False

    def test_section_without_level_does_not_apply_the_profile(self) -> None:
        """Секция без log_level профиль НЕ включает: пороги остаются базовыми."""
        logger = _FakeManagerWithConfig({})
        _apply_section({"stats": {"enabled": False}}, logger=logger)
        applied = logger.calls[-1]
        # База (managers_from_log_dir) — настроенный профиль, не «всё DEBUG».
        assert applied["scopes"]["SYSTEM"]["min_level"] == "WARNING"
        assert applied["scopes"]["DEBUG"]["enabled"] is False

    def test_live_scope_not_backed_by_any_layer_does_not_survive(self) -> None:
        """Обратная сторона разворота — названа явно, а не обнаружена потом.

        Порог, выставленный кем-то в живом конфиге и не записанный НИ В ОДИН слой,
        пересборку не переживает. Это цена, которой куплен работающий сброс:
        сохрани его — и «вернуть как было» перестало бы возвращать.
        """
        current_scopes = {"SYSTEM": {"enabled": True, "min_level": "ERROR", "channels": [], "modules": []}}
        logger = _FakeManagerWithConfig({"default_level": "INFO", "scopes": current_scopes})
        _apply_section({"stats": {"enabled": False}}, logger=logger)
        assert logger.calls[-1]["scopes"]["SYSTEM"]["min_level"] != "ERROR"

    def test_scope_written_into_a_layer_survives_and_beats_the_profile(self) -> None:
        """Пара к предыдущему: то же значение, но записанное СЛОЕМ, доживает.

        И ложится ПОВЕРХ профиля уровня — адресная правка не должна стираться
        оптовой ручкой, применённой в том же вызове.
        """
        logger = _FakeManagerWithConfig({})
        _apply_section(
            {"log_level": "DEBUG", "scopes": {"SYSTEM": {"min_level": "ERROR"}}},
            logger=logger,
        )
        scopes = logger.calls[-1]["scopes"]
        assert scopes["SYSTEM"]["min_level"] == "ERROR", "адресная правка стёрта профилем уровня"
        assert scopes["BUSINESS"]["min_level"] == "DEBUG", "профиль уровня не применён к остальным"


class TestEffectiveReadback:
    def test_effective_reads_live_logger_state(self) -> None:
        """Readback отражает ЖИВОЙ LoggerManager после reconfigure (не эхо входа)."""
        from multiprocess_framework.modules.logger_module import LoggerManager

        logger = LoggerManager(manager_name="TestLoggerEffective")
        logger.initialize()
        try:
            _apply_section({"log_level": "DEBUG"}, logger=logger)
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
            _apply_section({"log_level": "DEBUG"}, logger=logger)
            assert logger.should_log(LogScope.BUSINESS, LogLevel.DEBUG, "probe") is True
            _apply_section({"log_level": "WARNING"}, logger=logger)
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


class TestDisabledSinksAreVisibleInReadback:
    """Приёмка 2.8: readback обязан отличать «снят оператором» от «не доставляет».

    Поле реализовано, но тестом покрыто НЕ было (находка ревью 2.9) — то есть
    единственный способ увидеть рантайм-ручку снаружи держался ни на чём.
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
                app_name="readback",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={},
                channels={
                    "a": LoggerChannelSchema(type="file", file_path="a.log"),
                    "b": LoggerChannelSchema(type="file", file_path="b.log"),
                },
                scopes={"SYSTEM": LoggerScopeSchema(min_level="INFO", channels=["a", "b"])},
            )
        )

    def test_a_disabled_sink_shows_up_and_a_reload_clears_it(self, tmp_path) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_effective,
        )

        logger = self._logger(tmp_path)
        try:
            before = observability_effective(logger=logger, error=None, stats=None)["logger"]
            assert before.get("sinks_disabled_by_operator", []) == []

            logger.set_sink_enabled("a", False)
            after = observability_effective(logger=logger, error=None, stats=None)["logger"]
            assert after["sinks_disabled_by_operator"] == ["a"]
            assert "a" not in after["channels_active"], "снятый приёмник не может быть активным"

            logger.reconfigure(logger.config.model_dump())
            restored = observability_effective(logger=logger, error=None, stats=None)["logger"]
            assert restored["sinks_disabled_by_operator"] == []
            assert "a" in restored["channels_active"]
        finally:
            logger.shutdown()
