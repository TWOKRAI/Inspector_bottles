# -*- coding: utf-8 -*-
"""Тесты прокидки секции observability из system.yaml в managers (Phase 3, Task 3.2).

Проверяется: секция есть в схеме и в реальном yaml; overlay из секции мержится в
managers процесса (Logger/Error/Stats непусты, пользовательские значения применяются).
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import process
from multiprocess_framework.modules.process_module.configs import expand_observability
from multiprocess_framework.modules.process_module.configs.managers_config import merge_managers
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
)
from multiprocess_framework.modules.process_module.generic.generic_process_config import (
    GenericProcessConfig,
)

from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config


def _merged_managers(sys_config: SystemConfig) -> dict:
    """Повторяет логику launch.build(): process() → merge observability overlay."""
    overlay = expand_observability(sys_config.observability.model_dump())
    cfg = GenericProcessConfig(process_name="probe", log_dir="logs/test")
    _name, proc_dict = process(cfg)
    return merge_managers(proc_dict.get("managers", {}), overlay)


def test_schema_has_observability_default() -> None:
    sc = SystemConfig()
    assert isinstance(sc.observability, ObservabilityConfig)
    assert sc.observability.log_level == "INFO"


def test_yaml_observability_loaded() -> None:
    """Реальный system.yaml прототипа содержит валидную секцию observability."""
    sc = load_system_config()
    assert sc.observability.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert sc.observability.errors.enabled is True
    assert sc.observability.stats.enabled is True


def test_managers_have_logger_error_stats() -> None:
    """После merge у процесса непустые logger/error/stats (ErrorManager создаётся)."""
    managers = _merged_managers(SystemConfig())
    for key in ("logger", "error", "stats"):
        assert key in managers and managers[key], f"секция {key} пуста"


def test_overlay_applies_log_level() -> None:
    """Пользовательский log_level из секции применяется к logger.default_level."""
    sc = SystemConfig()
    sc.observability.log_level = "DEBUG"
    managers = _merged_managers(sc)
    assert managers["logger"]["default_level"] == "DEBUG"


def test_overlay_preserves_resolved_log_directory() -> None:
    """observability.log_directory=None НЕ затирает резолвнутый log_directory дефолтов."""
    managers = _merged_managers(SystemConfig())  # log_directory не задан
    assert managers["logger"].get("log_directory")  # непустой (из managers_from_log_dir)


def test_overlay_console_toggle() -> None:
    """console=False в секции → консольный канал disabled в итоговом logger."""
    sc = SystemConfig()
    sc.observability.console = False
    managers = _merged_managers(sc)
    console_chs = [c for c in managers["logger"]["channels"].values() if c["type"] == "console"]
    assert console_chs and all(not c["enabled"] for c in console_chs)
