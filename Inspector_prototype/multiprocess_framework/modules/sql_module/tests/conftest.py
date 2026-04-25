"""
Конфигурация pytest для sql_module.

Запуск из каталога refactored/modules:
    pytest sql_module/tests/ -v
"""
import sys
from pathlib import Path

_modules_dir = Path(__file__).resolve().parent.parent.parent
if str(_modules_dir) not in sys.path:
    sys.path.insert(0, str(_modules_dir))


import pytest
from multiprocess_framework.modules.sql_module import SQLManager, SQLManagerConfig


@pytest.fixture
def sql_config():
    """Конфиг для in-memory SQLite."""
    return SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite")


@pytest.fixture
def sql_manager(sql_config):
    """SQLManager с in-memory SQLite."""
    mgr = SQLManager(config=sql_config)
    mgr.initialize()
    yield mgr
    mgr.shutdown()
