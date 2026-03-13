"""
Конфигурация pytest для unit тестов data_schema_module.
Добавляем каталог modules в path, чтобы пакет data_schema_module импортировался.
Запуск: из каталога refactored/modules выполнить pytest data_schema_module/tests/ -v
"""
import sys
from pathlib import Path

# ВАЖНО: Создаём заглушку для multiprocess_framework ДО любых других импортов
# Это предотвращает попытку импорта родительского пакета, который ссылается на несуществующие модули
if 'multiprocess_framework' not in sys.modules:
    import types
    _mock_framework = types.ModuleType('multiprocess_framework')
    _mock_framework.__file__ = None
    _mock_framework.__path__ = []
    sys.modules['multiprocess_framework'] = _mock_framework
    
    # Также создаём заглушку для вложенного пакета modules
    _mock_modules = types.ModuleType('multiprocess_framework.modules')
    _mock_modules.__file__ = None
    _mock_modules.__path__ = []
    sys.modules['multiprocess_framework.modules'] = _mock_modules

# Добавляем каталог modules в sys.path для импорта data_schema_module
_modules_dir = Path(__file__).resolve().parent.parent.parent  # refactored/modules
if str(_modules_dir) not in sys.path:
    sys.path.insert(0, str(_modules_dir))

