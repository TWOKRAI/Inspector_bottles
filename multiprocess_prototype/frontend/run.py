#!/usr/bin/env python3
"""multiprocess_prototype/frontend/run.py — отдельная точка входа ФРОНТА (Ф2 frontend-constructor).

Хардкод-shell (см. ``plans/proto-frontend-carve.md``): единственная задача этого
скрипта — включить презентационный overlay (``frontend/presentation.yaml``) и
передать управление тому же launcher'у, что и обычный backend-only вход
(``multiprocess_prototype/run.py`` → ``main.main()``).

Механизм overlay — прошитый (не generic-конструктор): выставляем env
``INSPECTOR_PRESENTATION`` в путь к ``presentation.yaml`` ДО вызова ``main.main()``.
``backend/config/manifest.py::load_manifest`` читает этот env-overlay так же, как
``INSPECTOR_MANIFEST`` для пути к самому манифесту — приоритетнее значения из
``app.yaml`` (которое presentation по умолчанию не задаёт, headless-first).
``backend/launch.py::SystemBuilder.from_manifest`` накладывает overlay ПАТЧЕМ поверх
уже слитой топологии (план D8, 2026-08-10)::

    merged = merge_topologies(base, recipe)                      # рецепт объявил gui
    merged = apply_presentation_overlay(merged, presentation)    # gui → Qt-класс

То есть overlay не ДОБАВЛЯЕТ процесс презентации, а подменяет ему класс: сам процесс
объявляет рецепт, в headless-воплощении (``frontend/headless_process.py``).

Headless-флаг (``INSPECTOR_HEADLESS=1`` / ``--headless``, см. ``main.py``) остаётся
единственным резолвером и ПОБЕЖДАЕТ этот overlay, даже если тот включён здесь —
запуск ``frontend/run.py --headless`` поднимет систему БЕЗ окна: процесс ``gui``
останется, но будет дренировать data-трафик вместо рисования.

venv-guard — общий: ``multiprocess_prototype.run.venv_guard`` (одна реализация, C-55a);
бутстрап ``sys.path`` ниже нужен, чтобы импортировать его до re-exec (см. докстринг
``multiprocess_prototype/run.py`` про ``sys.path[0]`` при прямом запуске скрипта).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # .../multiprocess_prototype/frontend
PROTOTYPE_ROOT = HERE.parent  # .../multiprocess_prototype
PROJECT_ROOT = PROTOTYPE_ROOT.parent  # .../Inspector_bottles
PROJECT_VENV = PROJECT_ROOT / ".venv"

# При запуске скриптом sys.path[0] — каталог frontend/, а не корень проекта: без этой строки
# импорт общего guard'а ниже (он нужен ДО re-exec, под любым python) не разрешается.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multiprocess_prototype.run import default_relaunch, git_common_dir, venv_guard  # noqa: E402 — sys.path с корнем проекта выставлен строкой выше; импорт нужен до re-exec

#: Прошитый overlay фронта — единственный презентационный файл, который знает
#: этот entry-point (хардкод-shell, не generic-конструктор — см. докстринг модуля).
PRESENTATION_PATH = HERE / "presentation.yaml"


def launch(
    *,
    project_root: Path = PROJECT_ROOT,
    common_dir_of=git_common_dir,
    relaunch=default_relaunch,
) -> int:
    """venv-guard: переключиться на проектный .venv, включить presentation, запустить."""
    rc = venv_guard(
        Path(__file__),
        project_root=project_root,
        common_dir_of=common_dir_of,
        relaunch=relaunch,
        tag="[frontend/run]",
    )
    if rc is not None:
        return rc

    # Прошитый выбор overlay (хардкод-shell): фронт ВСЕГДА включает свою презентацию.
    # --headless / INSPECTOR_HEADLESS, если передан, всё равно победит (main._is_headless
    # — единственный резолвер headless, см. main.py).
    os.environ["INSPECTOR_PRESENTATION"] = str(PRESENTATION_PATH)

    from multiprocess_prototype.main import main as app_main

    argv = sys.argv[1:]
    headless_flag = "--headless" in argv
    if headless_flag:
        argv = [a for a in argv if a != "--headless"]

    return app_main(argv[0] if argv else None, headless=True if headless_flag else None)


if __name__ == "__main__":
    sys.exit(launch())
