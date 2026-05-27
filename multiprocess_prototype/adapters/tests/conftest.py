# -*- coding: utf-8 -*-
"""
adapters/tests/conftest.py — базовые фикстуры для тестов adapter-слоя.

Пока минимальный набор. Расширяется в Task C.2 и последующих Phase C Tasks.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.display_module.registry import DisplayRegistry
from multiprocess_framework.modules.service_module.registry import ServiceRegistry
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry


@pytest.fixture(autouse=False)
def clean_service_registry():
    """Очистить ServiceRegistry до и после теста для изоляции.

    ServiceRegistry — singleton, поэтому тесты могут влиять друг на друга.
    """
    ServiceRegistry().clear()
    yield
    ServiceRegistry().clear()


@pytest.fixture(autouse=False)
def clean_display_registry():
    """Очистить DisplayRegistry до и после теста для изоляции.

    DisplayRegistry — singleton, поэтому тесты могут влиять друг на друга.
    """
    DisplayRegistry().clear()
    yield
    DisplayRegistry().clear()


@pytest.fixture(autouse=False)
def clean_plugin_registry():
    """Очистить PluginRegistry до и после теста для изоляции.

    PluginRegistry — глобальный экземпляр _PluginRegistry.
    """
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
