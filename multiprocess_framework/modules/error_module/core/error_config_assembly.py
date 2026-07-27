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

#: Скоупы плоскости ошибок (резидуал P3). Все выключены — и это не «лишь бы
#: тише», а описание того, что плоскость делает: ErrorManager принимает только
#: WARNING/ERROR/CRITICAL, и они идут severity-маршрутом, который скоуп не
#: спрашивает вовсе (см. ``ErrorManager._route``). Записи ниже порога у него
#: приёмника нет ни одного.
#:
#: Пока поля не было, ErrorManager наследовал скоупы ЛОГГЕРА — с каналами
#: ``system_file`` / ``messages_file`` / ``console``, которых в его реестре не
#: существует. Собственный ``info("… initialized")`` на старте уходил в
#: несуществующие каналы, и счётчик-сигнал ``unresolved_channel_records``
#: в ПОКОЕ показывал 2 (воспроизведено: ``{'system_file': 1, 'messages_file': 1}``
#: после первого ``flush``). Сигнал «маршрут сломан» был загрязнён собственным
#: шумом менеджера — а по нему судят об инциденте.
_ERROR_PLANE_SCOPES: Dict[str, Any] = {
    scope: {"enabled": False, "min_level": "WARNING", "channels": []}
    for scope in ("SYSTEM", "BUSINESS", "PERFORMANCE", "AUDIT", "SECURITY", "DEBUG")
}


def expand_error_manager_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Слить severity-каналы из путей к файлам с дополнительными ``channels``.

    Порядок слияния: ``{**severity_channels, **extra}`` — дополнительные каналы
    перекрывают одноимённые severity-каналы.

    Здесь же (резидуал P3) подставляются умолчания плоскости ошибок для
    ``scopes`` и ``modules`` — но ТОЛЬКО если вызывающий их не задал. Обе
    настройки наследовались от ``LoggerManagerConfig`` и описывали плоскость
    ЛОГОВ, а не ошибок:

      * ``scopes`` — см. :data:`_ERROR_PLANE_SCOPES`;
      * ``modules`` — девять per-module файлов (``camera.log``, ``gui.log``,
        ``database.log`` …). ErrorManager открывал их все, писал в них ноль
        строк (severity-маршрут возвращает РОВНО один канал и module-каналов
        не касается) и делал это в том же каталоге, где те же файлы держит
        открытыми LoggerManager — то есть два хэндла на один ротируемый файл.
    """
    d = dict(data)
    # Не setdefault: явные ``None``/``{}`` тоже означают «своих скоупов нет».
    # Пустой словарь скоупов уводил бы гейт на fallback ``_scope_schema``, а тот
    # берёт ПЕРВЫЙ канал реестра — то есть INFO поехал бы в ``critical.log``.
    if not d.get("scopes"):
        d["scopes"] = _ERROR_PLANE_SCOPES
    if d.get("modules") is None:
        d["modules"] = {}
    else:
        d.setdefault("modules", {})
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
