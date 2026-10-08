"""Контрактный тест IConfigManager (k0 1.1).

Purpose: закрепить 16 абстрактных членов IConfigManager (7 своих + 9 от IBaseManager) и их реализацию.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite
"""

import pytest

from multiprocess_framework.modules.config_module.core.config_manager import ConfigManager
from multiprocess_framework.modules.config_module.interfaces import IConfigManager

__all__: list[str] = []

_OWN = frozenset(
    {"create_config", "get_config", "remove_config", "list_configs", "has_config", "sync_config",
     "load_config_from_storage"}
)  # fmt: skip
_INHERITED = frozenset(
    {"attach_adapter", "detach_adapter", "get_adapter", "get_debug_info", "get_stats", "has_adapter",
     "initialize", "list_adapters", "shutdown"}
)  # fmt: skip


def test_iconfig_manager_abstract_set_has_7_own_and_9_inherited_names():
    assert len(_OWN) == 7 and len(_INHERITED) == 9
    assert IConfigManager.__abstractmethods__ == _OWN | _INHERITED
    with pytest.raises(TypeError):
        IConfigManager()
    assert issubclass(ConfigManager, IConfigManager)
    assert ConfigManager.__abstractmethods__ == frozenset()
