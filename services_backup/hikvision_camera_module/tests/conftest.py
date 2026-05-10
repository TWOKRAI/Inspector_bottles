# -*- coding: utf-8 -*-
"""Pytest conftest — добавляет пути для импорта framework modules."""

import sys
from pathlib import Path

# Inspector_bottles (project root)
_root = Path(__file__).resolve().parent.parent.parent
_modules = _root / "multiprocess_framework" / "refactored" / "modules"
for _p in (_root, _modules):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
