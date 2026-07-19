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
``backend/launch.py::SystemBuilder.from_manifest`` подмешивает overlay к фундаменту
ПЕРЕД pipeline: ``merged = base ⊕ presentation ⊕ pipeline``.

Headless-флаг (``INSPECTOR_HEADLESS=1`` / ``--headless``, см. ``main.py``) остаётся
единственным резолвером и ПОБЕЖДАЕТ этот overlay, даже если тот включён здесь —
запуск ``frontend/run.py --headless`` поднимет систему БЕЗ окна (симметрия с
``main.py``/``run.py``, где headless-флаг перебивает presentation манифеста).

venv-guard — 1-в-1 с ``multiprocess_prototype/run.py`` (см. его докстринг про
``sys.path[0]`` при прямом запуске скрипта).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # .../multiprocess_prototype/frontend
PROTOTYPE_ROOT = HERE.parent  # .../multiprocess_prototype
PROJECT_ROOT = PROTOTYPE_ROOT.parent  # .../Inspector_bottles
PROJECT_VENV = PROJECT_ROOT / ".venv"

#: Прошитый overlay фронта — единственный презентационный файл, который знает
#: этот entry-point (хардкод-shell, не generic-конструктор — см. докстринг модуля).
PRESENTATION_PATH = HERE / "presentation.yaml"


def _venv_python() -> Path:
    """Путь к python в проектном venv."""
    if os.name == "nt":
        return PROJECT_VENV / "Scripts" / "python.exe"
    return PROJECT_VENV / "bin" / "python"


def _same_interpreter(a: Path, b: Path) -> bool:
    """Проверка что два пути указывают на один и тот же интерпретатор."""
    try:
        return a.resolve() == b.resolve()
    except (OSError, ValueError):
        return False


def launch() -> int:
    """venv-guard: переключиться на проектный .venv, включить presentation, запустить."""
    venv_py = _venv_python()
    current_py = Path(sys.executable)

    if not venv_py.exists():
        print(
            f"[frontend/run] ОШИБКА: не найден проектный venv: {venv_py}\n"
            f"       Создай его: cd {PROJECT_ROOT} && uv sync",
            file=sys.stderr,
        )
        return 1

    # Re-exec через проектный Python, если сейчас другой интерпретатор
    if not _same_interpreter(current_py, venv_py):
        print(f"[frontend/run] переключаюсь на {venv_py}", file=sys.stderr)
        # Re-exec в проектный venv — аргументы контролируемые (venv-python + этот файл + argv)
        os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])  # nosec B606

    # Уже в проектном venv — добавляем корень проекта в sys.path
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

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
