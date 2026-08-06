# -*- coding: utf-8 -*-
"""
Единая точка сборки runtime-dict для ErrorManager.

Плоские поля ``configs/ErrorManagerConfig`` (пути к файлам + опциональные ``channels``)
здесь превращаются в полный ``dict`` с ключом ``channels``, как ожидает
``LoggerManagerConfig`` / ChannelRoutingManager. Логика совпадает с прежним
``error_config.ErrorManagerConfig.build()`` до слияния с ``channels``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

_FILE_MAX = 10 * 1024 * 1024
_WARN_MAX = 5 * 1024 * 1024

#: Формат severity-каналов — ОДИН на все три, и уровень в нём подставляется,
#: а не зашит литералом.
#:
#: Литералы (``[CRITICAL]`` у critical_file, ``[WARNING]`` у warnings_file) были
#: безобидны ровно до тех пор, пока каждый канал принимал только свой уровень.
#: Ф1 достроила цепочку запасных маршрутов — и ERROR, попавший в ``critical.log``
#: при снятом ``errors_file``, стал НЕОТЛИЧИМ от настоящего критикала
#: (воспроизведено ревью: три записи разных уровней, все с меткой ``[CRITICAL]``).
#: То есть починка «ошибка не должна прятаться в warnings.log» породила зеркальное
#: «предупреждение выглядит критикалом», а ``critical.log`` — файл, по которому
#: поднимают тревогу.
_SEVERITY_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

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
#: Ф8.1: у скоупа остались только приёмники — ``enabled``/``min_level`` сняты
#: вместе со второй осью гейта. Смысл не изменился: записи ниже WARNING у этой
#: плоскости приёмника по-прежнему нет, но теперь это говорит ОДНА вещь — пустой
#: список каналов, — а не она же плюс выключатель плюс порог.
#: Молчание собственного ``info()`` менеджера держит порог корня
#: (``default_level="WARNING"`` плоскости ошибок), а не выключенный скоуп.
_ERROR_PLANE_SCOPES: Dict[str, Any] = {
    scope: {"channels": []} for scope in ("SYSTEM", "BUSINESS", "PERFORMANCE", "AUDIT", "SECURITY", "DEBUG")
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
    #
    # deepcopy обязателен: без него один и тот же module-level словарь (и те же
    # вложенные) раздавался бы ВСЕМ конфигам. Pydantic на ``model_validate``
    # строит новые схемы, поэтому сегодня это безопасно, — но любая правка
    # ``d["scopes"][...]`` до валидации утекла бы глобально (находка ревью Ф1).
    if not d.get("scopes"):
        d["scopes"] = deepcopy(_ERROR_PLANE_SCOPES)
    if not d.get("modules"):
        d["modules"] = {}
    critical = d.get("critical_file_path", "logs/critical.log")
    err = d.get("error_file_path", "logs/errors.log")
    warnings = d.get("warnings_file_path")

    severity_channels: Dict[str, Any] = {
        "critical_file": {
            "type": "file",
            "enabled": True,
            "file_path": critical,
            "format": _SEVERITY_FORMAT,
            "max_size": _FILE_MAX,
            "backup_count": 10,
        },
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": err,
            "format": _SEVERITY_FORMAT,
            "max_size": _FILE_MAX,
            "backup_count": 5,
        },
    }

    if warnings:
        severity_channels["warnings_file"] = {
            "type": "file",
            "enabled": True,
            "file_path": warnings,
            "format": _SEVERITY_FORMAT,
            "max_size": _WARN_MAX,
            "backup_count": 3,
        }

    # Task 5.10.a: слияние ГЛУБОКОЕ, а не поверхностное. Прежняя редакция
    # (`{**severity_channels, **extra}`) заменяла описание канала ЦЕЛИКОМ, и
    # частичная запись вида `{"errors_file": {"enabled": False}}` оставляла от
    # канала ровно этот один ключ — воспроизведено: `{'enabled': False}` вместо
    # шести полей, то есть без `type` и без `file_path`. Пока такую запись никто
    # не делал, дефект был спящим; симметрия namespace (5.10.b) делает её
    # штатным способом снять приёмник, и слияние обязано её пережить.
    #
    # Цена названа: одноимённый канал теперь ДОПОЛНЯЕТ severity-описание, а не
    # вытесняет его. Полная подмена (например, `errors_file` типа console)
    # сохранит ненужные `file_path`/`max_size` — они игнорируются сборщиком
    # канала своего типа. Обратное поведение (вытеснение) стоило бы того, что
    # частичную правку выразить нельзя вовсе.
    from multiprocess_framework.modules.data_schema_module import deep_merge

    extra = dict(d.get("channels") or {})
    d["channels"] = deep_merge(severity_channels, extra)
    return d
