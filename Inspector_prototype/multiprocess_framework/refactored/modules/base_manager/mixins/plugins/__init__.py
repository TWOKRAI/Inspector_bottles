"""
Плагин-система для ObservableMixin.

Позволяет расширять функциональность миксина через плагины.
"""

from .plugin_registry import PluginRegistry
from .plugin_base import ObservablePlugin

__all__ = [
    'PluginRegistry',
    'ObservablePlugin',
]





