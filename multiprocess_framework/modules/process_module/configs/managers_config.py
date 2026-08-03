"""
ManagersConfig — корневая SchemaBase-сборка секций proc_dict['managers'].

Композиция конфигов модулей (logger, error, stats, router, command, console).
Эталонные экземпляры (blueprints) вверху файла — источник дефолтов через
``model_copy(deep=True)`` в ``default_factory``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import Field

from ...command_module.configs.command_manager_config import CommandManagerConfig
from ...console_module.configs.console_config import ConsoleConfig
from ...data_schema_module import SchemaBase
from ...error_module.configs.error_manager_config import ErrorManagerConfig
from ...logger_module.configs.logger_manager_config import LoggerManagerConfig, LoggerScopeSchema
from ...router_module.configs.router_manager_config import RouterManagerConfig
from ...statistics_module.configs.stats_config import StatsManagerConfig

# ---------------------------------------------------------------------------
# Blueprint defaults (копии через default_factory, без общей мутации)
# ---------------------------------------------------------------------------

_LOGGER_BLUEPRINT = LoggerManagerConfig(
    app_name="inspector",
    default_level="INFO",
    log_directory="logs",
)

_ERROR_BLUEPRINT = ErrorManagerConfig()

_STATS_BLUEPRINT = StatsManagerConfig()

_ROUTER_BLUEPRINT = RouterManagerConfig(
    duplicate_messages_to_logger=True,
)

_COMMAND_BLUEPRINT = CommandManagerConfig(
    enable_logging=True,
    enable_statistics=True,
)

_CONSOLE_BLUEPRINT = ConsoleConfig()


def _default_logger() -> LoggerManagerConfig:
    return _LOGGER_BLUEPRINT.model_copy(deep=True)


def _default_error() -> ErrorManagerConfig:
    return _ERROR_BLUEPRINT.model_copy(deep=True)


def _default_stats() -> StatsManagerConfig:
    return _STATS_BLUEPRINT.model_copy(deep=True)


def _default_router() -> RouterManagerConfig:
    return _ROUTER_BLUEPRINT.model_copy(deep=True)


def _default_command() -> CommandManagerConfig:
    return _COMMAND_BLUEPRINT.model_copy(deep=True)


def _default_console() -> ConsoleConfig:
    return _CONSOLE_BLUEPRINT.model_copy(deep=True)


TManagersConfig = TypeVar("TManagersConfig", bound="ManagersConfig")


def level_profile_scopes(level: str) -> dict[str, dict[str, Any]]:
    """Scopes-профиль под глобальный ``log_level`` — ОДИН на оба пути (Ф2.3a).

    ``default_level`` сам по себе не фильтрует: решение принимает ``min_level``
    КАЖДОГО скоупа, а все стандартные скоупы всегда присутствуют в конфиге —
    поэтому смена уровня переписывает их пороги:

      - ``INFO``  — штатный настроенный профиль (SYSTEM=WARNING на консоль,
        BUSINESS/PERFORMANCE=INFO, DEBUG-скоуп выключен);
      - ``DEBUG`` — все скоупы на DEBUG + DEBUG-скоуп включается (firehose осознанно);
      - ``WARNING``/``ERROR``/``CRITICAL`` — пороги всех скоупов поднимаются до уровня
        (DEBUG-скоуп остаётся выключенным).

    **Живёт здесь, а не рядом с пересборкой, потому что копий было две и они
    расходились.** Воспроизведено 2026-08-03: при ``INSPECTOR_LOG_LEVEL=DEBUG``
    стартовый путь опускал ОДИН скоуп из четырёх (SYSTEM оставался WARNING,
    PERFORMANCE — INFO, DEBUG-скоуп выключенным), а тот же ``DEBUG`` через
    ``config.reload`` опускал все четыре и будил выключенный. Одна ручка значила
    разное в зависимости от того, как её задали, — корень находки
    «``config_reload`` врёт про ``log_level``». Теперь профиль один, и путь
    пересборки импортирует его отсюда.

    **Изменение живого поведения, названное вслух:** ``INSPECTOR_LOG_LEVEL=DEBUG``
    на старте теперь открывает и SYSTEM (то есть консоль), чего раньше не делал.
    Это ровно то, что та же величина уже делала через ``config.reload``;
    унификация идёт на семантику пересборки, потому что обратная («уровень
    трогает один скоуп из четырёх») настройкой не является.

    Ф2.3b (после 2.4/2.5) заменит профиль корневым правилом иерархии — тогда
    переписывания потомков не станет вовсе. Сейчас это невозможно без разворота
    приоритета «адресная правка скоупа vs оптовая ручка»: правило имени сильнее
    скоупа (Р-2.2-А), и корневое правило перебило бы точечный ``scopes.X``.
    """
    lvl = str(level).upper()
    scopes: dict[str, dict[str, Any]] = {}
    for name, sc in LoggerManagerConfig().scopes.items():
        d = sc.model_dump()
        if lvl == "DEBUG":
            d["min_level"] = "DEBUG"
            d["enabled"] = True
        elif lvl != "INFO":
            d["min_level"] = lvl
        scopes[str(name)] = d
    return scopes


class ManagersConfig(SchemaBase):
    """Корневая схема конфигурации менеджеров процесса."""

    log_dir: str = "logs"
    logger: LoggerManagerConfig = Field(default_factory=_default_logger)
    error: ErrorManagerConfig = Field(default_factory=_default_error)
    stats: StatsManagerConfig = Field(default_factory=_default_stats)
    router: RouterManagerConfig = Field(default_factory=_default_router)
    command: CommandManagerConfig = Field(default_factory=_default_command)
    console: ConsoleConfig = Field(default_factory=_default_console)

    def managers_for_proc_dict(self) -> dict[str, Any]:
        """Секции proc_dict['managers'] без log_dir (Dict at Boundary)."""
        return managers_payload_for_proc(self)

    @classmethod
    def from_log_dir(
        cls: type[TManagersConfig],
        log_dir: str,
        log_level: str | None = None,
    ) -> TManagersConfig:
        """Собрать конфиг: дефолты LoggerManagerConfig + log_directory и профиль уровня log_level.

        Ф2.3a: раньше уровень доставался ровно скоупу BUSINESS — то есть три
        скоупа из четырёх настройку игнорировали. Теперь применяется тот же
        профиль, что и на пересборке (:func:`level_profile_scopes`).
        """
        return managers_from_log_dir(log_dir, log_level, model_cls=cls)


def managers_payload_for_proc(cfg: ManagersConfig) -> dict[str, Any]:
    """Секции ``proc_dict['managers']`` без ``log_dir`` (Dict at Boundary)."""
    d = cfg.model_dump()
    d.pop("log_dir", None)
    return d


def managers_from_log_dir(
    log_dir: str,
    log_level: str | None = None,
    *,
    model_cls: type[TManagersConfig] = ManagersConfig,
) -> TManagersConfig:
    """
    Собрать экземпляр корневой схемы менеджеров: логгер и error-секция под каталог логов.

    ``model_cls`` — подкласс :class:`ManagersConfig` (например прототипный lite), без дублирования тела фабрики.
    """
    level = (log_level or os.environ.get("INSPECTOR_LOG_LEVEL", "INFO")).upper()
    root = Path(log_dir).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    log_dir_s = str(root)

    base_logger = _LOGGER_BLUEPRINT.model_copy(
        update={
            "app_name": "inspector",
            "default_level": level,
            "log_directory": log_dir_s,
        }
    )
    # Ф2.3a: тот же профиль, что применяет пересборка. Прежде здесь правился
    # ровно один скоуп (BUSINESS) — см. :func:`level_profile_scopes` про то,
    # почему копий было две и чем это стоило.
    #
    # ``model_validate``, а не подстановка словарей: ``model_copy(update=…)``
    # НЕ валидирует и положил бы dict вместо схемы — гейт читает атрибуты, и
    # порог молча перестал бы действовать. Класс ошибки уже пойман в этой же
    # фазе, на правилах иерархии.
    scopes = {name: LoggerScopeSchema.model_validate(data) for name, data in level_profile_scopes(level).items()}
    logger = base_logger.model_copy(update={"scopes": scopes})
    error = ErrorManagerConfig(
        error_file_path=os.path.join(log_dir_s, "errors.log"),
        critical_file_path=os.path.join(log_dir_s, "critical.log"),
        warnings_file_path=os.path.join(log_dir_s, "warnings.log"),
    )
    return model_cls(
        log_dir=log_dir,
        logger=logger,
        error=error,
        stats=_default_stats(),
        router=_default_router(),
        command=_default_command(),
        console=_default_console(),
    )


def merge_managers(
    base: dict[str, Any],
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deep merge managers config: overlay overwrites base keys recursively."""
    import copy

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
