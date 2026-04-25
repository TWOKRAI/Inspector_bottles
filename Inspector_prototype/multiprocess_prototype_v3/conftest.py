# multiprocess_prototype_v3/conftest.py
"""Корневой conftest для multiprocess_prototype_v3.

После миграции импортов (фреймворк = каноничный пакет ``multiprocess_framework``)
дополнительный sys.path-хак для ``modules/`` больше не нужен. Оставлен только
``Inspector_prototype`` в путях — чтобы pytest видел пакет ``multiprocess_prototype_v3``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_paths() -> None:
    here = Path(__file__).resolve().parent  # multiprocess_prototype_v3/
    inspector_root = here.parent             # Inspector_prototype/
    for p in (here, inspector_root):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


_ensure_paths()
