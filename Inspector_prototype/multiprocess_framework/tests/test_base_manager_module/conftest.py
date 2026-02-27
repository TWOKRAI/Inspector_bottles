"""
Конфигурация pytest для тестов Base_manager_module.

Добавляет корневую директорию проекта в sys.path для корректных импортов.
"""
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

