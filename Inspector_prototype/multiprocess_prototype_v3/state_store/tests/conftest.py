# state_store/tests/conftest.py
"""conftest для тестов state_store: добавляет multiprocess_prototype_v3/ в sys.path."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    # multiprocess_prototype_v3/ — корень для import state_store.*
    v3_root = Path(__file__).resolve().parents[2]  # multiprocess_prototype_v3/
    # Inspector_prototype/ — корень для framework-модулей
    inspector_root = v3_root.parent
    modules = inspector_root / "multiprocess_framework" / "modules"
    for p in (v3_root, inspector_root, modules):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


_ensure_paths()
