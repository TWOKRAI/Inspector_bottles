"""
Конфигурация pytest для unit тестов data_schema.
"""
import sys
from pathlib import Path

# Добавляем путь к модулям
project_root = Path(__file__).parent.parent.parent.parent.parent.parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

