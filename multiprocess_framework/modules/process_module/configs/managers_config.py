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
from ...logger_module.configs.logger_manager_config import LoggerManagerConfig, LoggerRuleSchema
from ...logger_module.core.name_hierarchy import ROOT_NAME
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


def root_level_rule(level: str) -> dict[str, dict[str, Any]]:
    """``log_level`` как КОРНЕВОЕ ПРАВИЛО иерархии — Ф8.1, механизм задачи 2.3b.

    Замена снятому ``level_profile_scopes``. Тот переписывал ``min_level``
    КАЖДОГО скоупа, потому что ``default_level`` сам по себе не фильтровал:
    решение принимал порог скоупа. Переписывание потомков и было дефектом —
    оптовая ручка стирала адресную правку, и намерение «всё на DEBUG, кроме
    SYSTEM» переставало быть выразимым (репро 2026-08-04 и 2026-08-06).

    После Ф8.1 порог у записи ровно один — от самого длинного совпавшего
    правила имени, а при их молчании от корня. Поэтому глобальный уровень
    выражается одним правилом на корне (ключ ``""``), а всё, что написано
    адреснее, **переживает смену глобального уровня**: у longest-prefix
    более длинное совпадение сильнее по построению, без разбора приоритетов.

    Returns:
        Кусок секции ``loggers`` — ``{"": {"level": <уровень>}}``. Словарь, а не
        схема: значение уезжает в конфиг через границу процесса (Dict at
        Boundary), а валидация происходит там, где секция собирается.

    **Уровень не нормализуется здесь.** Имя проверяет
    ``LoggerRuleSchema.level`` на границе конфига — то же место, где проверяются
    все остальные пороги. Своя проверка тут была бы второй позицией одной
    функции: разъехавшись, они дали бы «уровень принят в одном пути и отвергнут
    в другом».
    """
    return {ROOT_NAME: {"level": str(level).upper()}}


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

        Ф8.1: уровень едет корневым правилом иерархии. Раньше он доставался
        ровно скоупу BUSINESS (три из четырёх настройку игнорировали), потом —
        переписыванием всех четырёх, что стирало адресные правки. Применяется то же
        правило, что и на пересборке (:func:`root_level_rule`).
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
    # Ф8.1 (механизм 2.3b): уровень едет ОДНИМ корневым правилом, а не
    # переписыванием порогов у каждого скоупа. Тот же путь применяет пересборка
    # — копий по-прежнему одна, но теперь она ничего не стирает: правило,
    # написанное адреснее корня, переживает смену глобального уровня.
    #
    # Правила КОРНЯ, а не всей секции: ``loggers`` из blueprint'а (правила
    # приложения) обязаны остаться на месте. Замена словаря целиком снесла бы
    # их молча — класс «merge меняет ФОРМУ».
    #
    # ``model_validate``, а не подстановка словарей: ``model_copy(update=…)``
    # НЕ валидирует и положил бы dict вместо схемы — резолв читает атрибуты, и
    # порог молча перестал бы действовать. Класс ошибки уже пойман в этой же
    # фазе, на правилах иерархии.
    loggers = dict(base_logger.loggers)
    loggers.update({name: LoggerRuleSchema.model_validate(data) for name, data in root_level_rule(level).items()})
    logger = base_logger.model_copy(update={"loggers": loggers})
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
