"""
Конфигурация pytest для config_module.

Запуск из каталога refactored/modules:
    pytest config_module/tests/ -v
"""
import sys
from pathlib import Path

_modules_dir = Path(__file__).resolve().parent.parent.parent  # refactored/modules
if str(_modules_dir) not in sys.path:
    sys.path.insert(0, str(_modules_dir))
