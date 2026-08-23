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
        base:         Фундамент — СПИСОК топологий always-on инфраструктуры (БЕЗ
                      презентации), склеиваемых по порядку. Пустой список —
                      фундамент не используется (запуск читает только ``pipeline``).

                      В манифесте допустимы обе формы, и это не «на всякий
                      случай»: одна строка — исторический вид, который читают все
                      существующие app.yaml; список — способ подключить ОТДЕЛЬНЫЙ
                      кирпич инфраструктуры, не трогая общий фундамент::

                          base: backend/topology/base.yaml          # как было
                          base:                                     # композиция
                            - backend/topology/base.yaml
                            - backend/topology/observability_sink.yaml

                      Зачем список, а не процесс, вписанный в ``base.yaml``:
                      вписанный платят ВСЕ сборки. Замерено 2026-08-23 — добавление
                      одного side-effect процесса в общий фундамент раздуло
                      golden-снимки рецептов на 375 строк каждый и удвоило состав
                      минимального ``hello_world``. Со списком не подключивший не
                      платит ничем, а подключение и отключение — одна строка.
        presentation: Презентационный overlay-ПАТЧ (GUI): подменяет процессу ``gui``
                      класс на Qt-шный. ``None`` — headless: тот же процесс живёт в
                      дренирующем воплощении, объявленном рецептом (план D8). См.
                      ``frontend/presentation.yaml``, ``SystemBuilder.from_manifest``.
    """

    source: Path
    system: Path
    styles: StylesRef | None = None
    pipeline: Path
    recipes: Path
    base: tuple[Path, ...] = ()
    presentation: Path | None = None


def _resolve_base(base_dir: Path, raw: object) -> tuple[Path, ...]:
    """Разобрать ключ ``base``: строка, список строк или отсутствие.

    Обе формы равноправны и обе обязаны работать — существующие манифесты
    написаны строкой, а композиция инфраструктуры требует списка. Порядок
    списка значим: фрагменты склеиваются слева направо, как ``base`` с
    ``pipeline``.

    Отказ громкий и с адресом ключа: молча проглоченный ``base: 42`` дал бы
    систему без фундамента, и заметили бы это по отсутствующему процессу, а не
    по конфигу.
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
        base=_resolve_base(base_dir, base_raw),
        presentation=_resolve(base_dir, presentation_raw) if presentation_raw else None,
    )
