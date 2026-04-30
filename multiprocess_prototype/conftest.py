# multiprocess_prototype/conftest.py
"""Корневой conftest для multiprocess_prototype.

После миграции импортов (фреймворк = каноничный пакет ``multiprocess_framework``)
дополнительный sys.path-хак для ``modules/`` больше не нужен. Оставлен только
корень проекта в путях — чтобы pytest видел пакет ``multiprocess_prototype``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    here = Path(__file__).resolve().parent  # multiprocess_prototype/
    project_root = here.parent              # Inspector_bottles/ (project root)
    for p in (here, project_root):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


_ensure_paths()
