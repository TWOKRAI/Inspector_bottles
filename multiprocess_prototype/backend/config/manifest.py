"""Главный конфиг (манифест) прототипа — единственный файл, который читает точка входа.

`app.yaml` собирает в одном месте пути ко всем частям приложения:
системному конфигу, стилям, фундамент-топологии и активному pipeline.
Так из одного файла видно, что и из каких файлов запускается.

Все относительные пути в манифесте резолвятся от каталога самого манифеста
(`multiprocess_prototype/`). См. plans/config-driven-launch.md.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class StylesRef(BaseModel):
    """Стили: каталог тем + активная тема (стилевой рецепт)."""

    dir: Path
    active: str = "innotech_theme"


class AppManifest(BaseModel):
    """Главный конфиг: пути ко всем частям приложения.

    Пути уже резолвнуты в абсолютные при загрузке (см. ``load_manifest``).

    Attributes:
        source:   Путь, из которого загружен манифест (для логов/баннера).
        system:   Системные настройки + defaults (``system.yaml``).
        styles:   Стилевые рецепты (темы).
        pipeline: Активный запускаемый pipeline (runnable-топология).
        recipes:  Каталог GUI-редактируемых рецептов (editor-слой).
        base:     Фундамент-топология (презентация + always-on). ``None`` —
                  фундамент не используется (запуск читает только ``pipeline``).
    """

    source: Path
    system: Path
    styles: StylesRef
    pipeline: Path
    recipes: Path
    base: Path | None = None


def _resolve(base_dir: Path, value: str) -> Path:
    """Резолвить путь из манифеста относительно каталога манифеста."""
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p).resolve()


def load_manifest(path: Path | str) -> AppManifest:
    """Загрузить и провалидировать ``app.yaml``.

    Args:
        path: Путь к манифесту. Относительные пути внутри резолвятся
            от ``path.parent`` (каталог манифеста).

    Returns:
        ``AppManifest`` с абсолютными путями.
    """
    path = Path(path)
    base_dir = path.parent
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    styles_raw = raw.get("styles") or {}
    base_raw = raw.get("base")

    return AppManifest(
        source=path.resolve(),
        system=_resolve(base_dir, raw["system"]),
        styles=StylesRef(
            dir=_resolve(base_dir, styles_raw.get("dir", "frontend/styles/themes")),
            active=styles_raw.get("active", "innotech_theme"),
        ),
        pipeline=_resolve(base_dir, raw["pipeline"]),
        recipes=_resolve(base_dir, raw["recipes"]),
        base=_resolve(base_dir, base_raw) if base_raw else None,
    )
