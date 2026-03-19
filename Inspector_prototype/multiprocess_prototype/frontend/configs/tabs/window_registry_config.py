# multiprocess_prototype/frontend/configs/tabs/window_registry_config.py
"""
WindowRegistryConfig — реестр окон для WindowManager.

Каждая запись: {name: {factory_key}} — factory_key ищется в фабриках launcher.
"""

from typing import Any, Dict

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema


@register_schema("WindowRegistryEntry")
class WindowRegistryEntry(SchemaBase):
    """Запись реестра окон."""

    factory_key: str = "main"


def _default_window_registry() -> Dict[str, Dict[str, Any]]:
    return {
        "main": {"factory_key": "main"},
        "inspector": {"factory_key": "inspector"},
        "loading": {"factory_key": "loading"},
    }
