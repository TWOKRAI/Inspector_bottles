# multiprocess_prototype_v3/backend/configs/managers_schema.py
"""
Пресеты proc_dict['managers'] для этапов v3.

minimal — только stdout, без error manager, тихая статистика.
standard / pipeline — как в прототипе: файлы в logs/, error, stats в памяти.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

from multiprocess_framework.modules.command_module import CommandManagerConfig
from multiprocess_framework.modules.console_module.configs.console_config import ConsoleConfig
from multiprocess_framework.modules.logger_module import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.process_module import (
    ManagersConfig,
    managers_from_log_dir,
    managers_payload_for_proc,
)
from multiprocess_framework.modules.router_module import RouterManagerConfig
from multiprocess_framework.modules.statistics_module import StatsManagerConfig


_STD_FMT = "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s"


def get_log_dir() -> str:
    """Каталог логов: INSPECTOR_LOG_DIR или ``multiprocess_prototype_v3/logs``."""
    default = Path(__file__).resolve().parent.parent.parent / "logs"
    return os.environ.get("INSPECTOR_LOG_DIR") or str(default)


def merge_managers(
    base: Dict[str, Any],
    overlay: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Глубокий merge конфигов managers."""

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


def _minimal_managers_payload() -> Dict[str, Any]:
    logger = LoggerManagerConfig(
        app_name="v3",
        default_level="INFO",
        log_directory=None,
        enable_batching=False,
        channels={
            "console": LoggerChannelSchema(
                type="console",
                enabled=True,
                format=_STD_FMT,
            ),
        },
        scopes={
            "SYSTEM": LoggerScopeSchema(
                enabled=True,
                min_level="INFO",
                channels=["console"],
            ),
            "BUSINESS": LoggerScopeSchema(
                enabled=True,
                min_level="INFO",
                channels=["console"],
            ),
            "PERFORMANCE": LoggerScopeSchema(
                enabled=True,
                min_level="INFO",
                channels=["console"],
            ),
            "DEBUG": LoggerScopeSchema(
                enabled=True,
                min_level="DEBUG",
                channels=["console"],
            ),
        },
        modules={},
    )
    stats = StatsManagerConfig(enable_logging=False)
    router = RouterManagerConfig(duplicate_messages_to_logger=False)
    command = CommandManagerConfig(enable_logging=True, enable_statistics=False)
    console = ConsoleConfig(enabled=False)
    d = {
        "logger": logger.model_dump(),
        "stats": stats.model_dump(),
        "router": router.model_dump(),
        "command": command.model_dump(),
        "console": console.model_dump(),
    }
    return d


def _standard_managers_payload() -> Dict[str, Any]:
    ld = get_log_dir()
    root = Path(ld)
    root.mkdir(parents=True, exist_ok=True)
    model = managers_from_log_dir(str(root), model_cls=ManagersConfig)
    payload = managers_payload_for_proc(model)
    payload.setdefault("router", {})
    if isinstance(payload["router"], dict):
        payload["router"] = {
            **payload["router"],
            "duplicate_messages_to_logger": False,
        }
    return payload


def _pipeline_managers_payload() -> Dict[str, Any]:
    """Стандартные логи + severity/error как в плане для стадий 4–6."""
    base = _standard_managers_payload()
    err = base.get("error")
    if isinstance(err, dict):
        err = {
            **err,
            "default_level": "WARNING",
        }
        base["error"] = err
    st = base.get("stats")
    if isinstance(st, dict):
        base["stats"] = {**st, "enable_logging": True}
    return base


def get_default_managers_config(preset: str = "standard") -> Dict[str, Any]:
    """
    Секция managers для merge в proc_assembly.

    preset: minimal | standard | pipeline
    """
    p = (preset or "standard").lower()
    if p == "minimal":
        return _minimal_managers_payload()
    if p == "pipeline":
        return _pipeline_managers_payload()
    return _standard_managers_payload()
