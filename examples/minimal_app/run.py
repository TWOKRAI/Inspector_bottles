#!/usr/bin/env python3
"""examples/minimal_app — точка входа «рыбы». Вся сборка — в app_module.run_app.

Второе приложение на фреймворке = данные + декларации + ~3 строки bootstrap.
Запуск:  python examples/minimal_app/run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap sys.path: корень репозитория, чтобы резолвились
# `multiprocess_framework.*` и `examples.minimal_app.*` (plugin_class-путь).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multiprocess_framework.modules.app_module import run_app  # noqa: E402


def main() -> int:
    return run_app(Path(__file__).resolve().parent / "app.yaml")


if __name__ == "__main__":
    sys.exit(main())
