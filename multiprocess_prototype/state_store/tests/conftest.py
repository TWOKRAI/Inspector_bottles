# state_store/tests/conftest.py
"""conftest для тестов state_store: добавляет multiprocess_prototype/ в sys.path."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    # multiprocess_prototype/ — корень для import state_store.*
    v3_root = Path(__file__).resolve().parents[2]  # multiprocess_prototype/
    # Inspector_bottles/ — корень проекта для framework-модулей
    project_root = v3_root.parent
    modules = project_root / "multiprocess_framework" / "modules"
    for p in (v3_root, project_root, modules):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


_ensure_paths()
