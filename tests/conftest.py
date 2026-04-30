"""conftest для корневых тестов.

Подменяет multiprocess_prototype.frontend.widgets.tabs_setting
на stub-пакет чтобы обойти circular imports в его __init__.py.
Это позволяет импортировать processes_tab (и другие подпакеты)
напрямую без загрузки всего дерева.
"""

import sys
import types
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PKG_NAME = "multiprocess_prototype.frontend.widgets.tabs_setting"
_PKG_PATH = str(
    _PROJECT_ROOT / "multiprocess_prototype" / "frontend" / "widgets" / "tabs_setting"
)

if _PKG_NAME not in sys.modules:
    _mod = types.ModuleType(_PKG_NAME)
    _mod.__path__ = [_PKG_PATH]
    _mod.__package__ = _PKG_NAME
    sys.modules[_PKG_NAME] = _mod
