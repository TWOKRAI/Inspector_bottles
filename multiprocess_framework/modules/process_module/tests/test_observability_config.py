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
    """Дефолтная секция → три непустых dict с ключами logger/error/stats."""
    out = expand_observability({})
    assert set(out) == {"logger", "error", "stats"}
    assert out["error"], "error-секция обязана быть непустой (иначе ErrorManager не создаётся)"


def test_logger_dict_validates() -> None:
    out = expand_observability({"log_level": "DEBUG", "log_directory": "/tmp/logs"})
    cfg = LoggerManagerConfig.model_validate(out["logger"])
    assert cfg.default_level == "DEBUG"
    # Богатый дефолтный граф каналов сохранён (не затёрт при флагах по умолчанию).
    assert "console" in cfg.channels and "system_file" in cfg.channels


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
