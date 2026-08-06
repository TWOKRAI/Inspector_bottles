# -*- coding: utf-8 -*-
"""Тесты ObservabilityConfig + expand_observability (Phase 3, Task 3.1).

Контракт: expand раскладывает единую секцию в три manager-dict, валидных для
LoggerManagerConfig / ErrorManagerConfig / StatsManagerConfig; error всегда непустой.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs import (
    ObservabilityConfig,
    expand_observability,
)
from multiprocess_framework.modules.process_module.configs.managers_config import merge_managers
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.error_module.configs.error_manager_config import (
    ErrorManagerConfig,
)
from multiprocess_framework.modules.statistics_module.configs.stats_config import (
    StatsManagerConfig,
)


def test_expand_shape_default() -> None:
    """Дефолтная секция → четыре dict с ключами logger/error/stats/command."""
    out = expand_observability({})
    assert set(out) == {"logger", "error", "stats", "command"}
    assert out["error"], "error-секция обязана быть непустой (иначе ErrorManager не создаётся)"


def test_logger_dict_validates() -> None:
    out = expand_observability({"log_level": "DEBUG", "log_directory": "/tmp/logs"})
    cfg = LoggerManagerConfig.model_validate(out["logger"])
    assert cfg.default_level == "DEBUG"
    assert out["logger"]["log_directory"] == "/tmp/logs"  # явный — эмитится
    # Богатый дефолтный граф каналов сохранён (не затёрт при флагах по умолчанию).
    assert "console" in cfg.channels and "system_file" in cfg.channels


def test_log_directory_none_omitted() -> None:
    """log_directory=None НЕ эмитится — иначе overlay затрёт резолвнутый log_dir."""
    out = expand_observability({"log_level": "INFO"})
    assert "log_directory" not in out["logger"]


def test_error_dict_validates_and_nonempty() -> None:
    out = expand_observability({"errors": {"level": "ERROR", "include_stacktrace": False}})
    cfg = ErrorManagerConfig.model_validate(out["error"])
    assert cfg.default_level == "ERROR"
    assert cfg.include_stacktrace is False


def test_stats_dict_validates() -> None:
    out = expand_observability({"stats": {"aggregation_interval": 10.0, "enabled": False}})
    cfg = StatsManagerConfig.model_validate(out["stats"])
    assert cfg.aggregation_interval == 10.0
    assert cfg.enable_logging is False


class TestStatsFlushIntervalIsOperable:
    """Ф6.х.8 — ручка «реже» для snapshot-записей реально доезжает до менеджера.

    Реальный период записи = ``max(flush_interval, aggregation_interval)``
    (``stats_manager.py``); прежде ``flush_interval`` фасадом не прокидывался
    вовсе — менеджер всегда брал дефолт 10.0, и «реже» было невыразимо из
    конфига (только бинарный «выкл» для источника 64 % объёма логов).
    """

    def test_default_is_emitted_and_unchanged(self) -> None:
        """Литерал 10.0: дефолтный темп НЕ меняется до Ф7 (замеры сопоставимы)."""
        out = expand_observability({})
        assert out["stats"]["flush_interval"] == 10.0

    def test_explicit_value_validates_for_the_manager_config(self) -> None:
        out = expand_observability({"stats": {"flush_interval": 60.0}})
        assert out["stats"]["flush_interval"] == 60.0
        cfg = StatsManagerConfig.model_validate(out["stats"])
        assert cfg.flush_interval == 60.0

    def test_manager_window_respects_the_handle(self) -> None:
        """Сквозняк до окна: StatsManager строит период из max(flush, agg)."""
        from multiprocess_framework.modules.statistics_module.core.stats_manager import (
            StatsManager,
        )

        out = expand_observability({"stats": {"flush_interval": 60.0}})
        mgr = StatsManager(manager_name="FlushProbe", config=out["stats"])
        try:
            assert mgr._buffer._flush_interval == 60.0, "ручка не доехала до окна — max() снова съел настройку"
        finally:
            mgr.shutdown()


def test_default_section_creates_error_manager_config() -> None:
    """Пустая секция всё равно даёт валидный непустой error-dict."""
    out = expand_observability(None)
    cfg = ErrorManagerConfig.model_validate(out["error"])
    assert cfg.default_level == "WARNING"  # дефолт фасада


def test_partial_section_fills_defaults() -> None:
    """Частичная секция (только log_level) → остальное defaults."""
    out = expand_observability({"log_level": "WARNING"})
    assert out["logger"]["default_level"] == "WARNING"
    assert out["logger"]["enable_batching"] is True  # дефолт


def test_console_off_toggles_channel() -> None:
    """console=False → консольный канал disabled, файловые остаются, dict валиден."""
    out = expand_observability({"console": False})
    channels = out["logger"]["channels"]
    console_chs = [c for c in channels.values() if c["type"] == "console"]
    file_chs = [c for c in channels.values() if c["type"] == "file"]
    assert console_chs and all(not c["enabled"] for c in console_chs)
    assert file_chs and all(c["enabled"] for c in file_chs)
    LoggerManagerConfig.model_validate(out["logger"])  # не падает


def test_file_off_toggles_channels() -> None:
    """file=False → файловые каналы disabled, консоль остаётся."""
    out = expand_observability({"file": False})
    channels = out["logger"]["channels"]
    assert all(not c["enabled"] for c in channels.values() if c["type"] == "file")
    assert any(c["enabled"] for c in channels.values() if c["type"] == "console")


def test_unknown_keys_ignored() -> None:
    """Неизвестные ключи игнорируются (SchemaBase extra=ignore), не падает."""
    cfg = ObservabilityConfig.model_validate({"log_level": "INFO", "totally_unknown": 123})
    assert cfg.log_level == "INFO"


def test_accepts_config_instance() -> None:
    """expand принимает и готовый ObservabilityConfig, не только dict."""
    out = expand_observability(ObservabilityConfig(log_level="CRITICAL"))
    assert out["logger"]["default_level"] == "CRITICAL"


def test_commands_log_success_default_off() -> None:
    """По умолчанию log_success выключен — рутинный успех команд не логируется."""
    out = expand_observability({})
    assert out["command"] == {"log_success": False}


def test_commands_log_success_explicit_on() -> None:
    """observability.commands.log_success=true явно доезжает до command-секции (пара к тесту выше)."""
    out = expand_observability({"commands": {"log_success": True}})
    assert out["command"] == {"log_success": True}


class TestBufferCeilingIsOperable:
    """Ф0.3: потолок буфера доезжает из секции observability до обоих менеджеров.

    Без этого «ограничили BatchBuffer» означало бы зашитую константу: оператор
    не может ни поднять потолок под свою нагрузку, ни проверить срабатывание
    на живой системе через config.reload.
    """

    def test_defaults_are_emitted_for_logger_and_error(self) -> None:
        result = expand_observability({})
        for plane in ("logger", "error"):
            assert result[plane]["batch_max_pending"] == 10_000
            assert result[plane]["batch_overflow_policy"] == "drop_oldest"

    def test_explicit_values_reach_both_planes(self) -> None:
        result = expand_observability({"batch_max_pending": 25, "batch_overflow_policy": "drop_newest"})
        for plane in ("logger", "error"):
            assert result[plane]["batch_max_pending"] == 25
            assert result[plane]["batch_overflow_policy"] == "drop_newest"

    def test_emitted_keys_are_valid_for_the_manager_configs(self) -> None:
        """Секция обязана раскладываться в поля, которые конфиги реально принимают."""
        from multiprocess_framework.modules.error_module.configs.error_manager_config import (
            ErrorManagerConfig,
        )
        from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
            LoggerManagerConfig,
        )

        result = expand_observability({"batch_max_pending": 7})
        assert LoggerManagerConfig(**result["logger"]).batch_max_pending == 7
        assert ErrorManagerConfig(**result["error"]).batch_max_pending == 7


class TestMachineContextIsOverriddenOnlyByAnExplicitKey:
    """A-A4-2 (корзина 2 п.7): частичный слой не имеет права затирать env-уровень.

    Правило ADR-PM-020 — «молчание слоёв означает „решает нижний“» — было
    реализовано для секции ЦЕЛИКОМ (`layers_are_silent`) и для одного ключа
    (`log_directory` эмитится только явный), но не для `log_level`: expand
    материализовал дефолт L0 `INFO` ВСЕГДА. Достаточно было одного ключа
    `channels.*` в любом слое, чтобы уровень из `INSPECTOR_LOG_LEVEL` молча
    вернулся к дефолту. Здесь то же правило доводится до уровня ключа.
    """

    def test_absent_log_level_is_not_emitted(self) -> None:
        """Симметрия с `log_directory`: не задано → downstream-дефолт, а не L0 поверх."""
        out = expand_observability({"channels": {"messages_file": {"enabled": False}}})
        assert "default_level" not in out["logger"], out["logger"]

    def test_explicit_log_level_is_emitted(self) -> None:
        """Контроль: явный ключ по-прежнему доезжает — иначе слой перестал бы работать."""
        out = expand_observability({"log_level": "WARNING"})
        assert out["logger"]["default_level"] == "WARNING"

    def test_explicit_level_equal_to_the_l0_default_still_counts(self) -> None:
        """«Задано явно» и «не задано» различимы, даже когда значение совпало с дефолтом.

        Слить их — значит потерять намерение оператора, записавшего INFO руками
        поверх DEBUG из окружения (то же основание, что в ограничении ADR-PM-020).
        """
        out = expand_observability({"log_level": "INFO"})
        assert out["logger"]["default_level"] == "INFO"

    def test_partial_layer_does_not_clobber_the_env_level_in_the_merge(self) -> None:
        """Репро R7 ревьюера на продакшн-форме: overlay поверх базы из окружения."""
        base = {"logger": {"default_level": "DEBUG", "log_directory": "X:/logs"}}
        overlay = expand_observability({"channels": {"messages_file": {"enabled": False}}})
        merged = merge_managers(base, {"logger": overlay["logger"]})
        assert merged["logger"]["default_level"] == "DEBUG", "частичный слой вернул уровень окружения к дефолту L0"

    def test_an_explicit_level_in_the_layer_does_override_the_env(self) -> None:
        """Пара к предыдущему: слой, который ДЕЙСТВИТЕЛЬНО задаёт уровень, обязан победить."""
        base = {"logger": {"default_level": "DEBUG", "log_directory": "X:/logs"}}
        overlay = expand_observability({"log_level": "ERROR"})
        merged = merge_managers(base, {"logger": overlay["logger"]})
        assert merged["logger"]["default_level"] == "ERROR"


class TestSamplingKnobsReachTheLogger:
    """Ф7.1: четыре ручки дросселя обязаны доехать до менеджера.

    Ручка, которая есть в схеме и не доезжает до потребителя, — мёртвая: в
    файле она видна, в поведении её нет. Этот класс дефекта в проекте уже
    стоил дней поиска, поэтому путь от YAML до менеджера проверяется, а не
    предполагается.
    """

    def test_sampling_values_travel_to_the_logger_section(self) -> None:
        out = expand_observability(
            {
                "sampling_first_n": 5,
                "sampling_every_mth": 500,
                "sampling_burst_reset_sec": 30.0,
                "sampling_max_level": "INFO",
            }
        )
        assert out["logger"]["sampling_first_n"] == 5
        assert out["logger"]["sampling_every_mth"] == 500
        assert out["logger"]["sampling_burst_reset_sec"] == 30.0
        assert out["logger"]["sampling_max_level"] == "INFO"

    def test_sampling_is_off_by_default(self) -> None:
        """Механизм, сам решающий чего не останется, молча не включается."""
        assert expand_observability({})["logger"]["sampling_first_n"] == 0

    def test_error_plane_gets_no_sampling_knobs(self) -> None:
        """У плоскости ошибок дросселя нет — заявленная там ручка ничего бы не делала."""
        out = expand_observability({"sampling_first_n": 5})
        assert not [key for key in out.get("error", {}) if key.startswith("sampling")]
