# -*- coding: utf-8 -*-
"""
ErrorManagerConfig — плоская SchemaBase-схема (только поля + FieldMeta).

Сборка полного dict с severity-каналами — в ``core/error_config_assembly.expand_error_manager_config``.
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Optional

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

#: Ф8.1. Третий из трёх схлопнутых реестров: severity-маршруты плоскости ошибок.
#: Раньше это была лестница ``if has_critical: … elif has_errors: …`` внутри
#: ``ErrorManager._setup_level_routes`` — то есть завести уровень или приёмник
#: значило править код фреймворка, ровно как с кортежем ``GATED_METRICS``.
#:
#: Значение — приёмники **в порядке предпочтения**: действует первый, который
#: есть в реестре каналов. Порядок и есть то, что раньше кодировала лестница.
#:
#: **Запасной всегда к БОЛЕЕ важному файлу, никогда к менее важному.** ERROR
#: уходит в ``critical.log``, а не в ``warnings.log``: файл предупреждений
#: просматривают реже всех, и спрятать ошибку там значит потерять её на практике,
#: формально ничего не потеряв. Правило записано порядком, а не комментарием у
#: ветки — теперь его видно в readback конфига, а не только в исходнике.
DEFAULT_SEVERITY_ROUTES: Dict[str, List[str]] = {
    "CRITICAL": ["critical_file", "errors_file"],
    "ERROR": ["errors_file", "critical_file"],
    "WARNING": ["warnings_file", "errors_file", "critical_file"],
}


@register_schema("ErrorManagerConfig")
class ErrorManagerConfig(SchemaBase):
    """Конфигурация ErrorManager: пути к файлам и опциональные доп. каналы."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "ErrorManager"
    app_name: Annotated[str, FieldMeta("Имя приложения для логгера")] = "errors"

    critical_file_path: Annotated[str, FieldMeta("Файл критических ошибок")] = "logs/critical.log"
    error_file_path: Annotated[str, FieldMeta("Файл ошибок")] = "logs/errors.log"
    warnings_file_path: Annotated[
        Optional[str],
        FieldMeta("Файл предупреждений (None — не создавать)"),
    ] = "logs/warnings.log"

    default_level: Annotated[str, FieldMeta("Минимальный уровень")] = "WARNING"
    include_stacktrace: Annotated[bool, FieldMeta("Включать stacktrace")] = True
    channels: Annotated[
        Dict[str, dict],
        FieldMeta("Дополнительные каналы {имя: параметры}"),
    ] = Field(default_factory=dict)
    severity_routes: Annotated[
        Dict[str, List[str]],
        FieldMeta("Severity-маршруты: уровень → приёмники в порядке предпочтения"),
    ] = Field(default_factory=lambda: {level: list(chain) for level, chain in DEFAULT_SEVERITY_ROUTES.items()})
    """Ф8.1: лестница запасных приёмников — данные, а не ветвление в коде.

    Новый уровень или свой файл под него заводится конфигом; правок в
    ``multiprocess_framework/`` — ноль. Это третья строка приёмки задачи, рядом
    с каталогом метрик и уходом скоупов из гейта.

    ``default_factory`` с копией, а не общий словарь: :data:`DEFAULT_SEVERITY_ROUTES`
    хранит **списки**, и один общий экземпляр на все конфиги дал бы правку у одного
    менеджера, видимую всем остальным. Тот же приём, что у blueprint'ов
    ``ManagersConfig``, и та же причина.
    """
