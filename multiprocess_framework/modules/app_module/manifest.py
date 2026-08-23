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

    Тип — ``list[str]`` (а не ``list[Path]``, в отличие от одиночных путей
    ``pipeline``/``base``): значения потребляются как строки — ``PluginRegistry.discover``
    принимает ``*str``, ``discover_services`` делает ``Path(str)`` сам. Список путей
    остаётся log/JSON-дружелюбным (Dict-at-Boundary), без ранней конвертации в Path.
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
        base:      Фундамент — КОРТЕЖ топологий always-on инфраструктуры,
                   склеиваемых по порядку. Пустой кортеж — только ``pipeline``.
                   В манифесте допустимы обе формы: строка (исторический вид,
                   так написаны все существующие app.yaml) и список (композиция
                   инфраструктуры без правки общего фундамента).
        recipes:   Каталог GUI-редактируемых рецептов; ``None`` — не используется.
        discovery: Пути авто-скана плагинов/сервисов (абсолютные после загрузки).
    """

    source: Path
    name: str = "app"
    version: int = 1
    extras: dict[str, Any] = Field(default_factory=dict)
    system: Path | None = None
    pipeline: Path
    base: tuple[Path, ...] = ()
    recipes: Path | None = None
    discovery: DiscoverySpec = Field(default_factory=DiscoverySpec)


def _resolve_base(base_dir: Path, raw: object) -> tuple[Path, ...]:
    """Разобрать ключ ``base``: строка, список строк или отсутствие.

    Обе формы равноправны и обе обязаны работать: существующие манифесты
    написаны строкой, а подключение инфраструктурного кирпича (сток истории,
    рекордер, профайлер) требует списка. Порядок значим — фрагменты склеиваются
    слева направо, как ``base`` с ``pipeline``.

    Зачем список, а не процесс, вписанный в общий ``base.yaml``: вписанный
    платят ВСЕ сборки. Замерено 2026-08-23 — один side-effect процесс в общем
    фундаменте раздул golden-снимки рецептов на 375 строк каждый и удвоил
    состав минимального ``hello_world``.

    Отказ громкий и с адресом ключа: молча проглоченный ``base: 42`` дал бы
    систему БЕЗ фундамента, и заметили бы это по отсутствующему процессу на
    стенде, а не по конфигу.
    """
    if raw is None or raw == "" or raw == []:
        return ()
    if isinstance(raw, str):
        return (_resolve(base_dir, raw),)
    if isinstance(raw, (list, tuple)):
        bad = [x for x in raw if not isinstance(x, str) or not x]
        if bad:
            raise ValueError(f"base: элементы списка должны быть непустыми строками-путями, получено: {bad!r}")
        return tuple(_resolve(base_dir, x) for x in raw)
    raise ValueError(f"base: ожидалась строка или список строк, получено {type(raw).__name__}: {raw!r}")


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
        base=_resolve_base(base_dir, base_raw),
        recipes=_resolve(base_dir, recipes_raw) if recipes_raw else None,
        discovery=discovery,
    )
