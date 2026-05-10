#!/usr/bin/env python3
"""multiprocess_prototype launcher — auto-detect проектного .venv.

Логика:
  1. Находим Inspector_bottles/.venv/Scripts/python.exe (или bin/python).
  2. Если это НЕ текущий интерпретатор — re-exec через него.
  3. Прямой вызов main.main() (без subprocess).

Замечание о sys.path: добавление PROJECT_ROOT — это **намеренный bootstrap
launcher'а**, а не legacy-хак. При прямом запуске (`python multiprocess_prototype/run.py`)
Python кладёт в `sys.path[0]` директорию скрипта, а не корень проекта,
поэтому `from multiprocess_prototype.main import main` иначе не разрешается
без `pip install -e .`. validate.py знает об этом исключении (см. PRODUCTION_DIRS-фильтр).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
PROJECT_VENV = PROJECT_ROOT / ".venv"


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


def main() -> int:
    venv_py = _venv_python()
    current_py = Path(sys.executable)

    if not venv_py.exists():
        print(
            f"[run] ОШИБКА: не найден проектный venv: {venv_py}\n"
            f"       Создай его: cd {PROJECT_ROOT} && uv sync",
            file=sys.stderr,
        )
        return 1

    # Re-exec через проектный Python, если сейчас другой интерпретатор
    if not _same_interpreter(current_py, venv_py):
        print(f"[run] переключаюсь на {venv_py}", file=sys.stderr)
        os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])

    # Уже в проектном venv — добавляем корень проекта в sys.path
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from multiprocess_prototype.main import main as app_main

    return app_main(sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    sys.exit(main())
