"""Plugin system для GenericProcess.

Публичный API:
- ProcessModulePlugin — базовый класс плагина
- PluginContext — фасад над ProcessModule для плагинов
- Port — типизированный порт (вход/выход)
- PluginRegistry — глобальный каталог плагинов
- register_plugin — декоратор регистрации
"""

from .base import PluginContext, PluginState, ProcessModulePlugin, for_each
from .metrics import PluginMetrics
from .port import Port, are_ports_compatible, validate_chain
from .registry import PluginRegistry, register_plugin
from .test_bench import PluginTestBench

__all__ = [
    "ProcessModulePlugin",
    "PluginContext",
    "PluginState",
    "PluginMetrics",
    "PluginTestBench",
    "Port",
    "are_ports_compatible",
    "validate_chain",
    "PluginRegistry",
    "register_plugin",
    "for_each",
]
