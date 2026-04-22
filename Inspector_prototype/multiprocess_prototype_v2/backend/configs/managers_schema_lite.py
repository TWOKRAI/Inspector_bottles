# -*- coding: utf-8 -*-
"""
Схемы managers и сборка proc_dict['managers'] (Dict at Boundary).

Дефолты — из фреймворка (ManagersConfig, LoggerManagerConfig, …);
здесь — алиасы прототипа и merge для overlay.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

from multiprocess_framework.modules.command_module import CommandManagerConfig
from multiprocess_framework.modules.error_module import ErrorManagerConfig
from multiprocess_framework.modules.logger_module import LoggerManagerConfig
from multiprocess_framework.modules.process_module import (
    ManagersConfig,
    managers_from_log_dir,
    managers_payload_for_proc,
)
from multiprocess_framework.modules.router_module import RouterManagerConfig
from multiprocess_framework.modules.statistics_module import StatsManagerConfig

# ---------------------------------------------------------------------------
# Алиасы имён прототипа → схемы фреймворка
# ---------------------------------------------------------------------------

LoggerConfigLite = LoggerManagerConfig
ErrorConfigLite = ErrorManagerConfig
StatsConfigLite = StatsManagerConfig
RouterConfigLite = RouterManagerConfig
CommandConfigLite = CommandManagerConfig


ManagersConfigLite = ManagersConfig

# Публичное имя для импорта из backend.configs.
DefaultManagersConfig = ManagersConfigLite


def get_log_dir() -> str:
    """Каталог логов: INSPECTOR_LOG_DIR или ``multiprocess_prototype_v2/logs``."""
    default = Path(__file__).resolve().parent.parent.parent / "logs"
    return os.environ.get("INSPECTOR_LOG_DIR") or str(default)


def build_default_managers_model(log_dir: str | None = None) -> ManagersConfigLite:
    """Экземпляр ManagersConfigLite с путями из ``managers_from_log_dir`` (фреймворк)."""
    ld = log_dir if log_dir is not None else get_log_dir()
    return managers_from_log_dir(ld, model_cls=ManagersConfigLite)


def merge_managers(
    base: Dict[str, Any],
    overlay: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Глубокий merge конфигов managers для proc_dict."""

    if not overlay:
        return copy.deepcopy(base)

    def _deep(a: dict, b: dict) -> dict:
        out = copy.deepcopy(a)
        for k, v in b.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deep(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
        return out

    return _deep(base, overlay)


def get_default_managers_config(log_dir: str | None = None) -> Dict[str, Any]:
    """
    Конфигурация менеджеров по умолчанию (пути внутри каталога логов).

    Каталог: INSPECTOR_LOG_DIR или ``<multiprocess_prototype_v2>/logs``.
    """
    if log_dir is None:
        log_dir = get_log_dir()
    return managers_payload_for_proc(
        managers_from_log_dir(log_dir, model_cls=ManagersConfigLite)
    )
