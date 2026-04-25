"""
Запуск unit-тестов пакетов multiprocess_framework (каталог modules/).

После миграции на каноничные импорты (`multiprocess_framework.modules.<X>`) пакет
доступен через editable installation Inspector_prototype. Скрипт оставлен как
удобная точка входа: testpaths определены в `modules/pytest.ini`.

Использование (из Inspector_prototype):

    python scripts/run_framework_tests.py
    python scripts/run_framework_tests.py base_manager/tests -q
    python scripts/run_framework_tests.py --maxfail=1

Дополнительные аргументы передаются в pytest как есть.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    base = Path(__file__).resolve().parent.parent
    modules = base / "multiprocess_framework" / "modules"
    cfg = modules / "pytest.ini"
    if not cfg.is_file():
        print(f"Не найден {cfg}", file=sys.stderr)
        return 2
    cmd = [sys.executable, "-m", "pytest", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=str(modules))


if __name__ == "__main__":
    raise SystemExit(main())
