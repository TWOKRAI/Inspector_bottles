"""multiprocess_prototype — точка входа приложения.

Запуск управляется главным конфигом (манифестом) ``app.yaml``::

    main() → load_manifest(app.yaml) → SystemBuilder.from_manifest(app).build() → run()

Вся сборка системы (фундамент ⊕ pipeline → SystemLauncher) живёт в
``backend/launch.py::SystemBuilder``. Здесь — только точка входа и тонкие
back-compat обёртки (``bootstrap``, публичные пути), которые импортируются снаружи
(``frontend/app.py``, презентеры, тесты, README фреймворка).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )

    from multiprocess_prototype.backend.config.manifest import AppManifest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# Корень проекта в sys.path для импортов фреймворка и prototype
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = HERE / "backend" / "config" / "system.yaml"
DEFAULT_MANIFEST = HERE / "app.yaml"
# Дефолтный pipeline для legacy bootstrap() и тестов — РЕЦЕПТ (load_topology_dict
# разворачивает blueprint:). Основной выбор — через app.yaml.
DEFAULT_BLUEPRINT = HERE / "recipes" / "region_pipeline.yaml"


def resolve_manifest_path() -> Path:
    """Путь к главному конфигу: env ``INSPECTOR_MANIFEST`` > ``app.yaml`` рядом с модулем.

    Общий источник для backend (``main``) и GUI-процесса (``app.py``), чтобы
    оба читали один и тот же манифест.
    """
    return Path(os.environ.get("INSPECTOR_MANIFEST") or DEFAULT_MANIFEST)


#: Headless-флаг основного входа (Ф2 T2.2): ``INSPECTOR_HEADLESS=1``/``true``/``yes``
#: ИЛИ CLI ``--headless`` (см. ``__main__`` ниже, ``run.py``). Перебивает presentation,
#: даже если тот задан в манифесте/env-overlay (``INSPECTOR_PRESENTATION``, см.
#: ``frontend/run.py``) — симметрично: фронт-энтри ВКЛЮЧАЕТ presentation, headless-флаг
#: его ВЫКЛЮЧАЕТ, и побеждает headless.
HEADLESS_ENV = "INSPECTOR_HEADLESS"
_HEADLESS_TRUE_VALUES = {"1", "true", "yes"}


def _is_headless(explicit: bool | None) -> bool:
    """Единственный резолвер headless: явный флаг (CLI/API) > env ``INSPECTOR_HEADLESS``.

    ``explicit=None`` — флаг не передан явно вызывающей стороной → смотрим env.
    """
    if explicit is not None:
        return explicit
    return os.environ.get(HEADLESS_ENV, "").strip().lower() in _HEADLESS_TRUE_VALUES


def build_launcher(
    app: "AppManifest",
    pipeline_override: str | None = None,
    *,
    include_presentation: bool = True,
) -> "SystemLauncher":
    """Собрать систему из главного конфига (манифеста). Тонкая обёртка над SystemBuilder."""
    from multiprocess_prototype.backend.launch import SystemBuilder

    return SystemBuilder.from_manifest(app, pipeline_override, include_presentation=include_presentation).build()


def bootstrap(topology_path: Path | str | None = None) -> "SystemLauncher":
    """LEGACY: собрать систему из явного пути топологии + ``CONFIG_PATH``.

    Сохранено для тестов и README фреймворка. Новый код — ``build_launcher``.
    """
    from multiprocess_prototype.backend.launch import SystemBuilder

    bp_path = Path(topology_path) if topology_path else DEFAULT_BLUEPRINT
    return SystemBuilder.from_topology_path(CONFIG_PATH, bp_path).build()


def _prototype_launcher_factory(manifest, pipeline_override: str | None, *, headless: bool = False):
    """``launcher_factory`` для ``app_module.run_app`` (factory-шов Ф5.11).

    Вход прототипа выражен через ``run_app`` (generic-контур: env-алиасы
    ``MULTIPROCESS_*``, единая загрузка манифеста через ``ManifestStore``), а
    сложившийся ``SystemBuilder.build()`` остаётся источником истины сборки —
    характеризационный снапшот 5.1 не трогаем, back-compat полный. Прототипный
    манифест (со стилями/темой) грузится по ``manifest.source``.

    ``headless`` (Ф2 T2.2) — привязывается ``main()`` через ``functools.partial`` ДО
    того, как ``run_app``/``AppSpec`` вызовет фабрику своим фиксированным контрактом
    ``factory(manifest, pipeline_override)`` (framework, не расширяем). Дефолт
    ``False`` сохраняет back-compat для прямых вызовов (тесты вызывают фабрику без
    partial — presentation включена, как было до Ф2).
    """
    from multiprocess_prototype.backend.config.manifest import load_manifest

    app = load_manifest(manifest.source)
    return build_launcher(app, pipeline_override, include_presentation=not headless)


def main(pipeline_override: str | None = None, *, headless: bool | None = None) -> int:
    """Запуск приложения через ``app_module.run_app`` (Ф5.11).

    CLI-аргумент (`run.py <recipe>`) трактуется как «сделать этот рецепт
    активным»: он пишется в манифест (``app.yaml: pipeline``) через ``ManifestStore``
    (NEW-1 — единая сериализованная точка, гонка backend↔GUI закрыта) ДО сборки.
    Тогда и бэкенд, и дочерний GUI-процесс читают ОДИН активный рецепт. При ошибке
    записи — graceful fallback (override только в бэкенд).

    ``headless`` (Ф2 T2.2) — явный backend-only режим (см. ``_is_headless``): ``None``
    смотрит env ``INSPECTOR_HEADLESS``; явный ``True``/``False`` (CLI ``--headless``,
    см. ``__main__``) приоритетен. Перебивает presentation, даже если тот задан.
    """
    from functools import partial

    from multiprocess_framework.modules.app_module import AppSpec, apply_env_aliases, run_app

    # Env-алиасы ПЕРВЫМ делом (до resolve_manifest_path/persist): resolve_manifest_path
    # читает только INSPECTOR_MANIFEST, а persist пишет по нему же — при заданном лишь
    # MULTIPROCESS_MANIFEST без раннего алиаса backend собрал бы дефолтный app.yaml, а
    # GUI-ребёнок (run_app → apply_env_aliases → spawn с алиасом) — кастомный (split-brain).
    apply_env_aliases()

    is_headless = _is_headless(headless)

    manifest_path = resolve_manifest_path()
    effective_override = pipeline_override
    if pipeline_override:
        from multiprocess_prototype.backend.launch import persist_pipeline_choice

        try:
            written = persist_pipeline_choice(manifest_path, pipeline_override)
            print(f"[run] активный рецепт записан в манифест: pipeline: {written}")
            effective_override = None  # манифест уже указывает на нужный рецепт
        except Exception as exc:  # noqa: BLE001 — persist не должен валить запуск
            print(
                f"[run] не удалось записать рецепт в манифест ({exc}); запускаю бэкенд "
                "с CLI-override (GUI может взять рецепт из старого app.yaml)",
                file=sys.stderr,
            )

    spec = AppSpec(
        manifest_path=manifest_path,
        pipeline_override=effective_override,
        launcher_factory=partial(_prototype_launcher_factory, headless=is_headless),
    )
    return run_app(spec)


if __name__ == "__main__":
    _argv = sys.argv[1:]
    _headless_flag = "--headless" in _argv
    if _headless_flag:
        _argv = [a for a in _argv if a != "--headless"]
    sys.exit(main(_argv[0] if _argv else None, headless=True if _headless_flag else None))
