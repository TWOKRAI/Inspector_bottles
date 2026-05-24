"""Plugin system для GenericProcess — единый фасад для плагинов.

Публичный API плагина:
- ProcessModulePlugin — базовый класс плагина
- PluginContext — фасад над ProcessModule для плагинов
- Port — типизированный порт (вход/выход)
- PluginRegistry — глобальный каталог плагинов
- register_plugin — декоратор регистрации

Реэкспорт схем, конфига и worker-примитивов (чтобы плагины не тянули
framework.data_schema_module / framework.process_module.generic /
framework.worker_module напрямую — это сокращает cross-module edges
и закрепляет «плагин знает только про process_module.plugins»):
- SchemaBase, FieldMeta, register_schema — из data_schema_module
- PluginConfig — из process_module.generic.generic_process_config
- ExecutionMode, ThreadConfig — из worker_module (для плагинов, которым
  нужно явно задать режим/конфиг потока worker'а)
- RegistersManager — из registers_module (для тестов плагинов с регистрами)
"""

from ..generic.generic_process_config import PluginConfig
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ...registers_module import RegistersManager
from ...worker_module import ExecutionMode, ThreadConfig
from .base import PluginContext, PluginState, ProcessModulePlugin, SubPluginContext, for_each
from .manager import PluginDiscoveryResult, PluginManager
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
    "PluginManager",
    "PluginDiscoveryResult",
    "for_each",
    # Реэкспорт схем/конфига (фасад для плагинов)
    "SchemaBase",
    "FieldMeta",
    "register_schema",
    "PluginConfig",
    # Worker-примитивы и registers (фасад для плагинов и их тестов)
    "ExecutionMode",
    "ThreadConfig",
    "RegistersManager",
]
