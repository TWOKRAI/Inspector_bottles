"""Загрузчик displays.yaml — читает, валидирует, наполняет DisplayRegistry.

Отдельный модуль для изоляции IO-логики от чистых Pydantic-схем (``schemas.py``).

Публичный API:
    - ``load_displays_config``       — читает YAML, возвращает ``DisplaysConfig``
    - ``displays_config_to_registry`` — конвертирует ``DisplaysConfig`` → ``DisplayRegistry``

Слой: prototype.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry
from multiprocess_prototype.backend.config.schemas import DisplayEntrySchema, DisplaysConfig  # noqa: F401

_logger = logging.getLogger(__name__)


def load_displays_config(path: Path) -> DisplaysConfig:
    """Загрузить и валидировать displays.yaml.

    Покрывает все граничные случаи без пробрасывания исключений:
    - файл не существует → ``DisplaysConfig()``
    - YAML-ошибка разбора → лог + ``DisplaysConfig()``
    - пустой файл → ``DisplaysConfig()``
    - ValidationError → лог + ``DisplaysConfig()``

    Args:
        path: Путь к YAML-файлу реестра дисплеев.

    Returns:
        Валидированный ``DisplaysConfig``.
        При любой ошибке — пустой ``DisplaysConfig(displays=[])``.
    """
    if not path.exists():
        _logger.debug("displays_loader: файл не найден '%s' — используем пустой конфиг", path)
        return DisplaysConfig()

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        _logger.error("displays_loader: ошибка разбора YAML '%s': %s", path, exc)
        return DisplaysConfig()

    if raw is None:
        # Пустой файл — корректная ситуация
        _logger.debug("displays_loader: файл '%s' пустой — используем пустой конфиг", path)
        return DisplaysConfig()

    try:
        return DisplaysConfig.model_validate(raw)
    except ValidationError as exc:
        _logger.error("displays_loader: ошибка валидации '%s': %s", path, exc)
        return DisplaysConfig()


def displays_config_to_registry(config: DisplaysConfig, registry: DisplayRegistry) -> None:
    """Наполнить ``DisplayRegistry`` записями из ``DisplaysConfig``.

    Для каждой записи ``DisplayEntrySchema`` в ``config.displays``:
    - конвертирует в ``DisplayEntry`` через ``model_dump()``
    - вызывает ``registry.register(entry)``
    - при дубликате (``ValueError``) — логирует warning и продолжает

    Args:
        config:   Загруженная и валидированная конфигурация дисплеев.
        registry: Реестр, в который добавляются записи.
    """
    for schema_entry in config.displays:
        entry = DisplayEntry(**schema_entry.model_dump())
        try:
            registry.register(entry)
        except ValueError:
            _logger.warning(
                "displays_loader: дисплей '%s' уже зарегистрирован — пропускаем",
                entry.id,
            )
