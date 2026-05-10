"""Plugin system для GenericProcess — единый фасад для плагинов.

Публичный API плагина:
- ProcessModulePlugin — базовый класс плагина
- PluginContext — фасад над ProcessModule для плагинов
- Port — типизированный порт (вход/выход)
- PluginRegistry — глобальный каталог плагинов
- register_plugin — декоратор регистрации

Реэкспорт схем и конфига (чтобы плагины не тянули framework.data_schema_module
и framework.process_module.generic напрямую — это сокращает cross-module edges
и закрепляет «плагин знает только про process_module.plugins»):
- SchemaBase, FieldMeta, register_schema — из data_schema_module
- PluginConfig — из process_module.generic.generic_process_config
"""

from ..generic.generic_process_config import PluginConfig
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from .base import PluginContext, PluginState, ProcessModulePlugin, SubPluginContext, for_each
from .metrics import PluginMetrics
from .port import Port, are_ports_compatible, validate_chain
from .registry import PluginRegistry, register_plugin
from .test_bench import PluginTestBench

__all__ = [
    "ProcessModulePlugin",
    "PluginContext",
    "SubPluginContext",
    "PluginState",
    "PluginMetrics",
    "PluginTestBench",
    "Port",
    "are_ports_compatible",
    "validate_chain",
    "PluginRegistry",
    "register_plugin",
    "for_each",
    # Реэкспорт схем/конфига (фасад для плагинов)
    "SchemaBase",
    "FieldMeta",
    "register_schema",
    "PluginConfig",
]
