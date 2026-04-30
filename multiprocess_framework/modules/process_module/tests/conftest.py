"""Pytest: PYTHONPATH к каталогу modules + корень проекта."""
import sys
from pathlib import Path

_modules = Path(__file__).resolve().parent.parent.parent
_root = _modules.parent.parent
for p in (_modules, _root):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)
