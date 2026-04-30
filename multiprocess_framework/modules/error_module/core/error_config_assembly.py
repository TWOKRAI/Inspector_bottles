# -*- coding: utf-8 -*-
"""
Единая точка сборки runtime-dict для ErrorManager.

Плоские поля ``configs/ErrorManagerConfig`` (пути к файлам + опциональные ``channels``)
здесь превращаются в полный ``dict`` с ключом ``channels``, как ожидает
``LoggerManagerConfig`` / ChannelRoutingManager. Логика совпадает с прежним
``error_config.ErrorManagerConfig.build()`` до слияния с ``channels``.
"""
from __future__ import annotations

from typing import Any, Dict

_FILE_MAX = 10 * 1024 * 1024
_WARN_MAX = 5 * 1024 * 1024


def expand_error_manager_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Слить severity-каналы из путей к файлам с дополнительными ``channels``.

    Порядок слияния: ``{**severity_channels, **extra}`` — дополнительные каналы
    перекрывают одноимённые severity-каналы.
    """
    d = dict(data)
    critical = d.get("critical_file_path", "logs/critical.log")
    err = d.get("error_file_path", "logs/errors.log")
    warnings = d.get("warnings_file_path")

    severity_channels: Dict[str, Any] = {
        "critical_file": {
            "type": "file",
            "enabled": True,
            "file_path": critical,
            "format": "%(asctime)s [CRITICAL] %(name)s: %(message)s",
            "max_size": _FILE_MAX,
            "backup_count": 10,
        },
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": err,
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": _FILE_MAX,
            "backup_count": 5,
        },
    }

    if warnings:
        severity_channels["warnings_file"] = {
            "type": "file",
            "enabled": True,
            "file_path": warnings,
            "format": "%(asctime)s [WARNING] %(name)s: %(message)s",
            "max_size": _WARN_MAX,
            "backup_count": 3,
        }

    extra = dict(d.get("channels") or {})
    d["channels"] = {**severity_channels, **extra}
    return d
