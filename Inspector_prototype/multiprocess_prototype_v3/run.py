#!/usr/bin/env python3
"""multiprocess_prototype_v3 launcher — auto-detect проектного .venv.

Логика:
  1. Находим `Inspector_bottles/.venv/bin/python` (по дереву вверх).
  2. Если он есть и это НЕ текущий интерпретатор — re-exec через него
     (чтобы дочерние процессы фреймворка тоже подхватили правильный Python).
  3. Запускаем main.py.

Работает из любого CWD и из-под любого Python — сам переключается на проектный.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = HERE / "main.py"
PROJECT_ROOT = HERE.parent.parent
PROJECT_VENV = PROJECT_ROOT / ".venv"


def project_venv_python() -> Path:
    if os.name == "nt":
        return PROJECT_VENV / "Scripts" / "python.exe"
    return PROJECT_VENV / "bin" / "python"


def _same_interpreter(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except (OSError, ValueError):
        return False


def main() -> int:
    if not MAIN.exists():
        print(f"[run] не найден {MAIN}", file=sys.stderr)
        return 1

    venv_py = project_venv_python()
    current_py = Path(sys.executable)

    if not venv_py.exists():
        print(
            f"[run] ОШИБКА: не найден проектный venv: {venv_py}\n"
            f"       Создай его: cd {PROJECT_ROOT} && uv sync\n"
            f"       (или: ~/.local/bin/uv sync)",
            file=sys.stderr,
        )
        return 1

    # Re-exec через проектный Python, если сейчас запущены из другого
    if not _same_interpreter(current_py, venv_py):
        print(f"[run] переключаюсь на {venv_py}", file=sys.stderr)
        os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])

    # Уже в проектном venv — запускаем main.py как подпроцесс с тем же интерпретатором
    import subprocess  # noqa: PLC0415
    return subprocess.call(
        [sys.executable, str(MAIN), *sys.argv[1:]],
        cwd=str(HERE),
    )


if __name__ == "__main__":
    sys.exit(main())
