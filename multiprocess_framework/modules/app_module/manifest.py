"""``AppManifest`` — generic-манифест приложения (``app.yaml``), Ф5.11.

«Рыба»-контракт верхнего яруса: единственный файл, который читает точка входа
``run_app``. Пути ко всем частям приложения (system-конфиг, активный pipeline,
фундамент, каталог рецептов) + метаданные (``name``/``version``/``extras``) +
секция ``discovery`` (где искать плагины и сервисы).

**Задел под движок миграций с первого дня** (app-template-idea §3.4):
``version: int`` + ``extras: dict`` (pass-through). ``extras`` валидирует приложение,
НЕ framework — сюда складывается app-специфика (тема, брендинг), которую generic-ядро
не знает. Так через год не появится свой «unwrap_recipe» для манифеста.

Все относительные пути резолвятся от каталога манифеста (Dict-at-Boundary: на входе
YAML-dict, на выходе — Pydantic с абсолютными путями).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DiscoverySpec(BaseModel):
    """Где искать плагины и сервисы при старте (Ф5.11, директива владельца).

    Приложение декларирует папки в ``app.yaml``; ``run_app`` авто-сканирует их
    одним helper'ом (``discover``). Пути резолвятся от каталога манифеста в
    абсолютные при загрузке. Сервис распознаётся по маркер-файлу ``service.yaml``
    (симметрично ``plugin.py`` / манифесту плагина).
    """

    plugin_paths: list[str] = Field(default_factory=lambda: ["plugins"])
    service_paths: list[str] = Field(default_factory=lambda: ["services"])
    auto_discover: bool = True


class AppManifest(BaseModel):
    """Главный конфиг приложения — generic-ядро (без app-специфики).

    Attributes:
        source:    Путь, из которого загружен манифест (для логов/баннера).
        name:      Человекочитаемое имя приложения (идёт в startup-баннер, A8).
        version:   Версия схемы манифеста (задел движка миграций).
        extras:    App-специфика pass-through (тема/брендинг/…); framework не читает.
        system:    Системные настройки (``system.yaml``); ``None`` — приложение без них.
        pipeline:  Активный запускаемый pipeline (runnable-топология или рецепт).
        base:      Фундамент-топология (always-on); ``None`` — только ``pipeline``.
        recipes:   Каталог GUI-редактируемых рецептов; ``None`` — не используется.
        discovery: Пути авто-скана плагинов/сервисов (абсолютные после загрузки).
    """

    source: Path
    name: str = "app"
    version: int = 1
    extras: dict[str, Any] = Field(default_factory=dict)
    system: Path | None = None
    pipeline: Path
    base: Path | None = None
    recipes: Path | None = None
    discovery: DiscoverySpec = Field(default_factory=DiscoverySpec)


def _resolve(base_dir: Path, value: str) -> Path:
    """Резолвить путь из манифеста относительно каталога манифеста."""
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p).resolve()


def load_manifest(path: Path | str) -> AppManifest:
    """Загрузить и провалидировать ``app.yaml`` в :class:`AppManifest`.

    Относительные пути (``system``/``pipeline``/``base``/``recipes`` и
    ``discovery.*_paths``) резолвятся от ``path.parent``.

    Args:
        path: путь к манифесту.

    Returns:
        :class:`AppManifest` с абсолютными путями.

    Raises:
        FileNotFoundError: манифест не существует.
        KeyError: отсутствует обязательный ключ ``pipeline``.
    """
    path = Path(path)
    base_dir = path.parent
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    disc_raw = raw.get("discovery") or {}
    discovery = DiscoverySpec(
        plugin_paths=[str(_resolve(base_dir, p)) for p in disc_raw.get("plugin_paths", ["plugins"])],
        service_paths=[str(_resolve(base_dir, p)) for p in disc_raw.get("service_paths", ["services"])],
        auto_discover=bool(disc_raw.get("auto_discover", True)),
    )

    base_raw = raw.get("base")
    recipes_raw = raw.get("recipes")
    system_raw = raw.get("system")

    return AppManifest(
        source=path.resolve(),
        name=raw.get("name", "app"),
        version=int(raw.get("version", 1)),
        extras=dict(raw.get("extras") or {}),
        system=_resolve(base_dir, system_raw) if system_raw else None,
        pipeline=_resolve(base_dir, raw["pipeline"]),
        base=_resolve(base_dir, base_raw) if base_raw else None,
        recipes=_resolve(base_dir, recipes_raw) if recipes_raw else None,
        discovery=discovery,
    )
