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


def build_launcher(app: "AppManifest", pipeline_override: str | None = None) -> "SystemLauncher":
    """Собрать систему из главного конфига (манифеста). Тонкая обёртка над SystemBuilder."""
    from multiprocess_prototype.backend.launch import SystemBuilder

    return SystemBuilder.from_manifest(app, pipeline_override).build()


def bootstrap(topology_path: Path | str | None = None) -> "SystemLauncher":
    """LEGACY: собрать систему из явного пути топологии + ``CONFIG_PATH``.

    Сохранено для тестов и README фреймворка. Новый код — ``build_launcher``.
    """
    from multiprocess_prototype.backend.launch import SystemBuilder

    bp_path = Path(topology_path) if topology_path else DEFAULT_BLUEPRINT
    return SystemBuilder.from_topology_path(CONFIG_PATH, bp_path).build()


def main(pipeline_override: str | None = None) -> int:
    """Запуск приложения: главный конфиг → сборка → run.

    CLI-аргумент (`run.py <recipe>`) трактуется как «сделать этот рецепт
    активным»: он пишется в манифест (``app.yaml: pipeline``) ДО сборки. Тогда и
    бэкенд, и дочерний GUI-процесс читают ОДИН и тот же активный рецепт из
    конфига (он же «последний» — для следующего запуска без аргумента). Без записи
    override доходил только до бэкенда, а GUI читал старый ``app.yaml`` →
    рассинхрон рецептов (дисплеи не грузились). При ошибке записи — graceful
    fallback на прежнее поведение (override только в бэкенд).
    """
    from multiprocess_prototype.backend.config.manifest import load_manifest

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

    app = load_manifest(manifest_path)
    build_launcher(app, effective_override).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
