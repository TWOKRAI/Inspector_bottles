"""
Конфигурация pytest для sql_module.

Запуск из корня проекта:
    pytest Services/sql/tests/ -v
"""

import pytest
from Services.sql import SQLManager, SQLManagerConfig


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
