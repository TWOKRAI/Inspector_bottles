"""Главный конфиг (манифест) прототипа — единственный файл, который читает точка входа.

`app.yaml` собирает в одном месте пути ко всем частям приложения:
системному конфигу, стилям, фундамент-топологии и активному pipeline.
Так из одного файла видно, что и из каких файлов запускается.

Все относительные пути в манифесте резолвятся от каталога самого манифеста
(`multiprocess_prototype/`). См. plans/config-driven-launch.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel

#: Env-overlay презентации (аналог INSPECTOR_MANIFEST для манифеста целиком) — задаёт
#: ``presentation`` поверх/вместо значения из ``app.yaml``. Читает ``frontend/run.py``
#: (включает GUI) — прототип-специфика, во framework не мигрирует (в отличие от
#: MULTIPROCESS_*/INSPECTOR_* пар в app_module.env, presentation — GUI-only концерн).
PRESENTATION_ENV = "INSPECTOR_PRESENTATION"


def _env_overlay() -> str | None:
    """Значение env-overlay презентации (``INSPECTOR_PRESENTATION``), если задано."""
    return os.environ.get(PRESENTATION_ENV) or None


class StylesRef(BaseModel):
    """Стили: каталог тем + активная тема (стилевой рецепт)."""

    dir: Path
    active: str = "innotech_theme"


class AppManifest(BaseModel):
    """Главный конфиг: пути ко всем частям приложения.

    Пути уже резолвнуты в абсолютные при загрузке (см. ``load_manifest``).

    Attributes:
        source:       Путь, из которого загружен манифест (для логов/баннера).
        system:       Системные настройки + defaults (``system.yaml``).
        styles:       Стилевые рецепты (темы) — презентационный концерн.
                      ``None`` — стили не заданы (допустимо для headless-бэкенда,
                      который их не читает; см. Ф2 frontend-constructor T2.3).
        pipeline:     Активный запускаемый pipeline (runnable-топология).
        recipes:      Каталог GUI-редактируемых рецептов (editor-слой).
        base:         Фундамент-топология (always-on инфра, БЕЗ презентации).
                      ``None`` — фундамент не используется (запуск читает
                      только ``pipeline``).
        presentation: Презентационный overlay-топология (GUI). ``None`` —
                      headless (GUI не подмешивается). См.
                      ``frontend/presentation.yaml``, ``SystemBuilder.from_manifest``.
    """

    source: Path
    system: Path
    styles: StylesRef | None = None
    pipeline: Path
    recipes: Path
    base: Path | None = None
    presentation: Path | None = None


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

    styles_raw = raw.get("styles")
    base_raw = raw.get("base")
    # Презентация: env-overlay (frontend/run.py) приоритетнее значения из app.yaml —
    # тот же паттерн, что INSPECTOR_MANIFEST для пути к самому манифесту.
    presentation_raw = _env_overlay() or raw.get("presentation")

    styles: StylesRef | None = None
    if styles_raw:
        styles_dir = styles_raw.get("dir")
        if not styles_dir:
            raise ValueError(
                f"{path}: styles.dir не задан явно — headless-бэкенд стили не читает, "
                "презентации нужен явный каталог тем (без скрытого дефолта)"
            )
        styles = StylesRef(
            dir=_resolve(base_dir, styles_dir),
            active=styles_raw.get("active", "innotech_theme"),
        )

    return AppManifest(
        source=path.resolve(),
        system=_resolve(base_dir, raw["system"]),
        styles=styles,
        pipeline=_resolve(base_dir, raw["pipeline"]),
        recipes=_resolve(base_dir, raw["recipes"]),
        base=_resolve(base_dir, base_raw) if base_raw else None,
        presentation=_resolve(base_dir, presentation_raw) if presentation_raw else None,
    )
