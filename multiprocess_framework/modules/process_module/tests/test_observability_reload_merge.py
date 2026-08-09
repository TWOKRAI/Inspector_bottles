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

import pytest

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


class TestRootLevelRule:
    """Ф8.1 (механизм 2.3b): ``log_level`` — ОДНО правило корня, а не профиль скоупов.

    Класс заменил ``TestLevelProfile``. Прежний профиль переписывал ``min_level``
    у каждого скоупа, и именно переписывание было дефектом: оптовая ручка стирала
    адресную правку, из-за чего «всё на DEBUG, кроме одного источника» не
    выражалось ни одним конфигом (репро 2026-08-04, повторено 2026-08-06).
    """

    def test_debug_lands_as_a_root_rule(self) -> None:
        """Плечо ON: log_level=DEBUG → корневое правило DEBUG, порог живой."""
        logger = _FakeManagerWithConfig({"default_level": "INFO"})
        _apply_section({"log_level": "DEBUG"}, logger=logger)
        applied = logger.calls[-1]
        assert applied["loggers"][""]["level"] == "DEBUG", "уровень не доехал корневым правилом"
        assert applied["default_level"] == "DEBUG"

    def test_warning_raises_the_root_threshold(self) -> None:
        """Плечо OFF: log_level=WARNING → корень поднят, и это тот же единственный ключ."""
        logger = _FakeManagerWithConfig({"default_level": "DEBUG"})
        _apply_section({"log_level": "WARNING"}, logger=logger)
        applied = logger.calls[-1]
        assert applied["loggers"][""]["level"] == "WARNING"
        assert applied["default_level"] == "WARNING"

    def test_the_level_no_longer_rewrites_scopes(self) -> None:
        """**Главное свойство Ф8.1.** Уровень не трогает скоупы вообще.

        Стережёт возврат снятого механизма: пока профиль переписывал пороги
        скоупов, адресная правка исчезала молча. Проверяется отсутствие ПОБОЧНОГО
        эффекта, а не наличие нового — такие свойства теряются первыми.
        """
        logger = _FakeManagerWithConfig({"default_level": "INFO"})
        _apply_section({"log_level": "DEBUG"}, logger=logger)
        для_скоупов = logger.calls[-1].get("scopes") or {}
        assert all("min_level" not in sc and "enabled" not in sc for sc in для_скоупов.values()), (
            "уровень снова полез в скоупы — вернулась вторая ось гейта"
        )

    def test_section_without_level_does_not_touch_the_root(self) -> None:
        """Секция без log_level корневое правило НЕ выставляет: база остаётся базой."""
        logger = _FakeManagerWithConfig({})
        _apply_section({"stats": {"enabled": False}}, logger=logger)
        applied = logger.calls[-1]
        assert applied["default_level"] == "INFO", "порог базы подменён без запроса"

    def test_a_live_rule_not_backed_by_any_layer_does_not_survive(self) -> None:
        """Обратная сторона разворота — названа явно, а не обнаружена потом.

        Порог, выставленный кем-то в живом конфиге и не записанный НИ В ОДИН слой,
        пересборку не переживает. Это цена, которой куплен работающий сброс:
        сохрани его — и «вернуть как было» перестало бы возвращать.
        """
        logger = _FakeManagerWithConfig({"default_level": "INFO", "loggers": {"живой": {"level": "ERROR"}}})
        _apply_section({"stats": {"enabled": False}}, logger=logger)
        assert "живой" not in (logger.calls[-1].get("loggers") or {})

    def test_an_addressed_rule_from_a_layer_survives_the_bulk_knob(self) -> None:
        """**Приёмка 2.3b.** Адресное правило переживает оптовую ручку в том же вызове.

        Ровно то, что до Ф8.1 было невыразимо: корневое правило DEBUG действует
        всем, а источник со своим правилом остаётся на ERROR. Раньше здесь
        побеждала одна ось из двух, и какая именно — зависело от того, кто
        сильнее, а не от того, что написал оператор.
        """
        logger = _FakeManagerWithConfig({})
        _apply_section(
            {"log_level": "DEBUG", "loggers": {"тихий.источник": {"level": "ERROR"}}},
            logger=logger,
        )
        rules = logger.calls[-1]["loggers"]
        assert rules["тихий.источник"]["level"] == "ERROR", "адресное правило стёрто оптовой ручкой"
        assert rules[""]["level"] == "DEBUG", "корневое правило не применено к остальным"


class TestOneLevelForBothPaths:
    """Ф2.3a, перенесённая на новый механизм: ``log_level`` значит ОДНО на обоих путях.

    Дефект был воспроизведён, а не выведен из кода (2026-08-03): при
    ``INSPECTOR_LOG_LEVEL=DEBUG`` стартовая сборка опускала ОДИН скоуп из
    четырёх, а тот же ``DEBUG`` через ``config.reload`` — все четыре. Одна ручка
    — два смысла, в зависимости от того, как её задали.

    Сравниваются ДВА ПУТИ между собой, а не путь с константой: константа
    зафиксировала бы сегодняшнюю раскладку и молчала бы ровно про то, что
    сломалось, — про их расхождение.
    """

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_boot_and_reload_agree_on_every_level(self, tmp_path, level: str) -> None:
        from multiprocess_framework.modules.process_module.configs.managers_config import (
            ManagersConfig,
            managers_from_log_dir,
        )
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            _root_level_rule,
        )

        boot = managers_from_log_dir(str(tmp_path), level, model_cls=ManagersConfig).logger.loggers[""].level
        reload_ = _root_level_rule(level)[""]["level"]
        assert boot == reload_, f"старт и пересборка разошлись на log_level={level}"

    def test_boot_puts_the_level_where_the_gate_reads_it(self, tmp_path) -> None:
        """Уровень обязан лечь туда, откуда его ЧИТАЕТ гейт, а не просто в конфиг.

        Проверяется поведением живого менеджера, а не формой конфига: правило,
        лежащее не в том ключе, конфиг проходит и гейт не меняет — класс
        «спека плана может врать», уже стрелявший в этой фазе.
        """
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.configs.managers_config import (
            ManagersConfig,
            managers_from_log_dir,
        )

        cfg = managers_from_log_dir(str(tmp_path), "DEBUG", model_cls=ManagersConfig).logger
        mgr = LoggerManager(manager_name="BootLevel81", config=cfg)
        mgr.initialize()
        try:
            assert mgr.should_log(LogScope.SYSTEM, LogLevel.DEBUG, "любой.источник") is True
        finally:
            mgr.shutdown()

    def test_boot_rules_are_schema_objects_not_dicts(self, tmp_path) -> None:
        """Правило кладётся ВАЛИДИРОВАННЫМ, иначе порог молча не действует.

        ``model_copy(update=…)`` не валидирует: словарь на месте схемы прошёл бы
        сборку молча, а резолв читает атрибуты — и ``level`` перестал бы
        существовать. Тот же класс ошибки уже пойман в этой фазе на правилах
        иерархии, поэтому здесь стоит страж, а не надежда.
        """
        from multiprocess_framework.modules.logger_module.configs import LoggerRuleSchema
        from multiprocess_framework.modules.process_module.configs.managers_config import (
            ManagersConfig,
            managers_from_log_dir,
        )

        rules = managers_from_log_dir(str(tmp_path), "WARNING", model_cls=ManagersConfig).logger.loggers
        assert all(isinstance(r, LoggerRuleSchema) for r in rules.values())


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
            # Ф8.1: порог виден там, где он теперь живёт, — в правиле корня.
            # Скоупы в readback остались, но отвечают только про приёмники.
            assert eff["logger"]["loggers"][""]["level"] == "DEBUG"
            assert "min_level" not in eff["logger"]["scopes"]["SYSTEM"]
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
                scopes={"SYSTEM": LoggerScopeSchema(channels=["a", "b"])},
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
