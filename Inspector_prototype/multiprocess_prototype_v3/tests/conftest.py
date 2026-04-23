# multiprocess_prototype_v3/tests/conftest.py
"""Общий conftest для тестов v3: sys.path для плоских модулей фреймворка + корень Inspector_prototype."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_inspector_paths() -> None:
    root = Path(__file__).resolve().parents[2]  # Inspector_prototype/
    v3_root = Path(__file__).resolve().parents[1]  # multiprocess_prototype_v3/
    modules = root / "multiprocess_framework" / "modules"
    for p in (root, v3_root, modules):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


_ensure_inspector_paths()
